#!/bin/bash
# fl4write (Fl4wRite) runner — deployed on nucbox
# Audit 2026-09-01 (lane F): set -uo pipefail, flock against overlapping crons,
# per-repo budget 900s (the old 300s was smaller than any inner timeout — every
# real fix attempt guaranteed a mid-flight kill), self-update failures logged,
# ERR tails widened, ALERT lines surfaced unconditionally, log capped.
set -uo pipefail

LOG=~/workspaces/fl4write/runner.log

# One runner at a time (worst case 31 x 900s can exceed the hourly cron interval).
exec 9>/tmp/fl4write-runner.lock
flock -n 9 || exit 0

export CODESITTER_GITHUB_TOKEN=$(gh auth token 2>/dev/null)
if [ -z "$CODESITTER_GITHUB_TOKEN" ]; then
    echo "$(date -Iseconds) ERROR: no gh token available" >> "$LOG"
    exit 1
fi

cd ~/workspaces/fl4write

# Self-update — failures are VISIBLE (silent staleness would run green forever).
if ! git pull -q origin main 2>>"$LOG"; then
    echo "$(date -Iseconds) ALERT: self-update (git pull) failed — running stale code" >> "$LOG"
fi

# Hosts without ~/.sinter/config.json read the model key from .bashrc.
# Non-interactive shells never reach .bashrc exports, so pull it here.
# (.bashrc wraps the value in literal quotes — strip them or auth 401s.)
if [ -z "${CODESITTER_DEEPSEEK_KEY:-}" ]; then
    export CODESITTER_DEEPSEEK_KEY=$(grep "^export CODESITTER_DEEPSEEK_KEY=" ~/.bashrc 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"')
fi
# Forgejo fleet (2026-09-01, CEO-approved): same .bashrc-invisible-to-cron
# extraction for the Forgejo bot token — inert until the key exists (empty
# export + zero active forgejo configs = never called).
if [ -z "${CODESITTER_FORGEJO_TOKEN:-}" ]; then
    export CODESITTER_FORGEJO_TOKEN=$(grep "^export CODESITTER_FORGEJO_TOKEN=" ~/.bashrc 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"')
fi

# SCALE Phase 2: tiered due-list + process pool (consensus-gated, #6).
# The tier scheduler derives the due list (NEVER writes state); every due
# repo gets a worker; results land as per-repo files where MISSING = ERR
# (a worker dying pre-write must never inherit last cycle's result — the
# Critic's stale-file amendment).
mkdir -p logs
DUE=$(python3 -m fl4write.tiers *.fl4write.yaml 2>/dev/null)
echo "$(date -Iseconds) $DUE" | grep "^..*tiers:" >> "$LOG" || true
# duplicate-config ALERTs + tier lines from the scheduler reach runner.log
python3 -m fl4write.tiers *.fl4write.yaml 2>/dev/null | grep -E "^(ALERT|tiers:)" | while read -r line; do
    echo "$(date -Iseconds) $line" >> "$LOG"
done
DUE_FILES=$(python3 -m fl4write.tiers *.fl4write.yaml 2>/dev/null | grep -v -E "^(ALERT|tiers:)")
# stale result files cleared BEFORE dispatch (the amendment)
for f in $DUE_FILES; do
    rm -f "logs/$(echo "$f" | tr '/' '_').result"
done

POOL=${FL4WRITE_POOL:-$(( $(nproc 2>/dev/null || echo 4) > 4 ? 4 : $(nproc 2>/dev/null || echo 4) ))}

run_one() {
    f="$1"
    exec 9>&-  # NEVER inherit the flock fd — orphaned workers must not
               # silently block the next cycle (the Architect's trap)
    slug=$(echo "$f" | tr '/' '_')
    OUT=$(timeout 900 python3 -m fl4write.cli "$f" --fixes --issues 2>"logs/$slug.err")
    rc=$?
    # full detail to the per-repo log; runner.log keeps the aggregate surface
    echo "$OUT" >> "logs/$slug.log" 2>/dev/null || true
    tail -c 100k "logs/$slug.log" > "logs/$slug.log.tmp" 2>/dev/null && mv "logs/$slug.log.tmp" "logs/$slug.log" || rm -f "logs/$slug.log.tmp"
    # the grep contract survives: ALERTs + cycle lines + ERR tails -> runner.log
    echo "$OUT" | grep "ALERT" | while read -r line; do
        echo "$(date -Iseconds) $line" >> "$LOG"
    done
    echo "$OUT" | grep "^fl4write cycle:" | while read -r line; do
        echo "$(date -Iseconds) $line" >> "$LOG"
    done
    if [ $rc -eq 0 ] && echo "$OUT" | grep -q "cycle:"; then
        echo 0 > "logs/$slug.result"
    else
        echo "$(date -Iseconds) ERR: $f — $(echo "$OUT" | tail -5)" >> "$LOG"
        cat "logs/$slug.err" | tail -3 >> "$LOG" 2>/dev/null || true
        echo 1 > "logs/$slug.result"
    fi
}
export -f run_one
export LOG

echo "$DUE_FILES" | xargs -P "$POOL" -I{} bash -c 'run_one "$@"' _ {}

# aggregate: MISSING result file = ERR, never silence (the Critic's law)
OK=0; ERR=0
for f in $DUE_FILES; do
    slug=$(echo "$f" | tr '/' '_')
    if [ -f "logs/$slug.result" ] && [ "$(cat logs/$slug.result)" = "0" ]; then
        OK=$((OK+1))
    else
        ERR=$((ERR+1))
        [ -f "logs/$slug.result" ] || echo "$(date -Iseconds) ERR: $f — NO RESULT FILE (worker died)" >> "$LOG"
    fi
done
echo "$(date -Iseconds) cycle: $OK ok / $ERR errors" >> "$LOG"

# Cap the log (slow growth, but nothing trimmed it ever).
tail -c 1M "$LOG" > "$LOG.tmp" 2>/dev/null && mv "$LOG.tmp" "$LOG" || rm -f "$LOG.tmp"
