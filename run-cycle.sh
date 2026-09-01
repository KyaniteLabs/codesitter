#!/bin/bash
# codesitter runner — deployed on nucbox
export CODESITTER_GITHUB_TOKEN=$(gh auth token 2>/dev/null)
if [ -z "$CODESITTER_GITHUB_TOKEN" ]; then
    echo "$(date -Iseconds) ERROR: no gh token available" >> ~/workspaces/codesitter/runner.log
    exit 1
fi

cd ~/workspaces/codesitter
git pull -q origin main 2>/dev/null

OK=0; ERR=0
for f in *.codesitter.yaml; do
    OUT=$(timeout 300 python3 -m codesitter.cli "$f" --fixes --issues 2>&1)
    if echo "$OUT" | grep -q "cycle:"; then
        OK=$((OK+1))
    else
        ERR=$((ERR+1))
        echo "$(date -Iseconds) ERR: $f — $(echo "$OUT" | tail -3)" >> ~/workspaces/codesitter/runner.log
    fi
done
echo "$(date -Iseconds) cycle: $OK ok / $ERR errors" >> ~/workspaces/codesitter/runner.log
