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

OK=0; ERR=0
for f in *.fl4write.yaml; do
    OUT=$(timeout 900 python3 -m fl4write.cli "$f" --fixes --issues 2>&1)
    if echo "$OUT" | grep -q "cycle:"; then
        OK=$((OK+1))
    else
        ERR=$((ERR+1))
        echo "$(date -Iseconds) ERR: $f — $(echo "$OUT" | tail -5)" >> "$LOG"
    fi
    # ALERT lines surface unconditionally — including from cycles that also errored.
    echo "$OUT" | grep "ALERT" | while read -r line; do
        echo "$(date -Iseconds) $line" >> "$LOG"
    done
done
echo "$(date -Iseconds) cycle: $OK ok / $ERR errors" >> "$LOG"

# Cap the log (slow growth, but nothing trimmed it ever).
tail -c 1M "$LOG" > "$LOG.tmp" 2>/dev/null && mv "$LOG.tmp" "$LOG" || rm -f "$LOG.tmp"
