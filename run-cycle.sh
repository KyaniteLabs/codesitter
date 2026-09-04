#!/bin/bash
# fl4write (Fl4wRite) runner — deployed on nucbox
# Audit 2026-09-01 (lane F): set -uo pipefail, flock against overlapping crons,
# per-repo budget 900s (the old 300s was smaller than any inner timeout — every
# real fix attempt guaranteed a mid-flight kill), self-update failures logged,
# ERR tails widened, ALERT lines surfaced unconditionally, log capped.
set -uo pipefail

LOG=~/workspaces/fl4write/runner.log

# One runner at a time (worst case 31 x 900s can exceed the hourly cron interval).
# MECE round-1 (glm F1-5): the lock lived in WORLD-WRITABLE /tmp — any local
# user could hold or symlink it and silently suppress every cycle. It now
# lives in the runner's own ~/.fl4write state dir.
mkdir -p ~/.fl4write
exec 9>~/.fl4write/runner.lock
flock -n 9 || exit 0

export CODESITTER_GITHUB_TOKEN=$(gh auth token 2>/dev/null)
if [ -z "$CODESITTER_GITHUB_TOKEN" ]; then
    echo "$(date -Iseconds) ERROR: no gh token available" >> "$LOG"
    exit 1
fi

# MECE round-6 (sol F6-E05): a failed cd silently ran the cycle from an
# unintended directory (or 'check-dirty clean' certified a MISSING checkout)
cd ~/workspaces/fl4write || { echo "$(date -Iseconds) ERR: cannot cd to ~/workspaces/fl4write" >> "$LOG"; exit 1; }

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
# The scheduler is invoked EXACTLY ONCE (Sol#2: three invocations = 3x the
# probe cost + fragile grep-splitting); its JSON envelope carries due files,
# alerts, and counts; scheduler FAILURE is a loud exit, never 0-ok/0-err
# (Sol#1: a dead scheduler used to look like a healthy empty cycle).
mkdir -p logs
mkdir -p ~/.fl4write
python3 -m fl4write.tiers --plan *.fl4write.yaml > ~/.fl4write/plan.json 2>>"$LOG"
PLAN_RC=$?
PLAN=$(cat ~/.fl4write/plan.json 2>/dev/null)
# MECE round-2 (sol F2-001): keep the scheduler's OWN exit status; also
# refuse output that is not JSON at all
# MECE rounds 2-3 (sol F2-001 report; luna F3-001 CRITICAL reopen): the arm
# BELOW once CLEARED valid JSON plans (arm body PLAN="") — every hourly cycle
# died with "tier scheduler failed" since 720f6b9. Valid JSON must be KEPT;
# only non-JSON output is cleared.
case "$PLAN" in
    ""|'{'*) ;;
    *) PLAN="" ;;
esac
# MECE round-4 (terra F4-401): "starts with {" is not JSON — "{not-json"
# slipped past and the downstream parsers silently produced an empty plan
# (quiet no-op, breaking the loud-failure contract)
echo "$PLAN" | python3 -c 'import json,sys; json.load(sys.stdin)' 2>>"$LOG" || PLAN=""
if [ $PLAN_RC -ne 0 ] || [ -z "$PLAN" ]; then
    echo "$(date -Iseconds) ERR: tier scheduler failed — fleet NOT cycled this hour" >> "$LOG"
    exit 1
fi
# MECE round-6 (sol F6-E04): valid JSON with the WRONG SHAPE ({"due": null})
# used to pass syntax validation and silently become an empty successful
# cycle — validate the envelope: due/alerts must be string lists, summary str
if ! echo "$PLAN" | python3 -c 'import json,sys
p = json.load(sys.stdin)
ok = isinstance(p, dict) \
     and isinstance(p.get("due"), list) and all(isinstance(d, str) for d in p["due"]) \
     and isinstance(p.get("alerts"), list) \
     and isinstance(p.get("summary"), str)
sys.exit(0 if ok else 1)' 2>>"$LOG"; then
    echo "$(date -Iseconds) ERR: tier scheduler plan MALFORMED (shape) — fleet NOT cycled this hour" >> "$LOG"
    exit 1
fi
PLAN_ALERTS=$(echo "$PLAN" | python3 -c "import json,sys; [print('ALERT: '+a) for a in json.load(sys.stdin).get('alerts',[])]" 2>/dev/null)
PLAN_SUMMARY=$(echo "$PLAN" | python3 -c "import json,sys; print(json.load(sys.stdin).get('summary',''))" 2>/dev/null)
[ -n "$PLAN_SUMMARY" ] && echo "$(date -Iseconds) $PLAN_SUMMARY" >> "$LOG"
if [ -n "$PLAN_ALERTS" ]; then
    echo "$PLAN_ALERTS" | while read -r line; do echo "$(date -Iseconds) $line" >> "$LOG"; done
fi

# mapfile = no word-splitting on filenames with spaces (Sol#3)
mapfile -t DUE_FILES < <(echo "$PLAN" | python3 -c "import json,sys; [print(f) for f in json.load(sys.stdin).get('due',[])]" 2>/dev/null)

# stale result files cleared BEFORE dispatch (the Critic's amendment)
for f in "${DUE_FILES[@]}"; do
    rm -f "logs/$(echo "$f" | tr '/' '_').result"
done

# pool: nproc once; the env override is CAPPED, never bypassed (Sol#11)
NPROC=$(nproc 2>/dev/null || echo 4)
POOL_REQ=${FL4WRITE_POOL:-4}
[[ "$POOL_REQ" =~ ^[0-9]+$ ]] || POOL_REQ=4
POOL_REQ=$((10#$POOL_REQ))  # MECE round-3 (luna F3-003): 08 is invalid octal in $(( ))
POOL=$(( POOL_REQ < NPROC ? (POOL_REQ < 4 ? POOL_REQ : 4) : (NPROC < 4 ? NPROC : 4) ))
# MECE round-1 (glm F1-2): FL4WRITE_POOL=0 validated as numeric but made
# xargs -P 0 run UNLIMITED workers — floor the pool at 1
[ "$POOL" -lt 1 ] && POOL=1

run_one() {
    f="$1"
    exec 9>&-  # NEVER inherit the flock fd — orphaned workers must not
               # silently block the next cycle (the Architect's trap)
    slug=$(echo "$f" | tr '/' '_')
    OUT=$(timeout 900 python3 -m fl4write.cli "$f" --fixes --issues 2>&1)
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
        echo 1 > "logs/$slug.result"
    fi
}
export -f run_one
export LOG

# MECE round-2 (sol F2-002): an empty due list must not feed xargs a NUL
# empty record (phantom worker error); the aggregate below prints the line
if [ "${#DUE_FILES[@]}" -gt 0 ]; then
    printf '%s\0' "${DUE_FILES[@]}" | xargs -0 -P "$POOL" -I{} bash -c 'run_one "$@"' _ {}
fi

# aggregate: MISSING result file = ERR, never silence (the Critic's law)
OK=0; ERR=0
for f in "${DUE_FILES[@]}"; do
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
