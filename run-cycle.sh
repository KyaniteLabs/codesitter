#!/bin/bash
# fl4write (Fl4wRite) runner — deployed on nucbox
export CODESITTER_GITHUB_TOKEN=$(gh auth token 2>/dev/null)
if [ -z "$CODESITTER_GITHUB_TOKEN" ]; then
    echo "$(date -Iseconds) ERROR: no gh token available" >> ~/workspaces/fl4write/runner.log
    exit 1
fi

cd ~/workspaces/fl4write
git pull -q origin main 2>/dev/null

OK=0; ERR=0
for f in *.fl4write.yaml; do
    OUT=$(timeout 300 python3 -m fl4write.cli "$f" --fixes --issues 2>&1)
    if echo "$OUT" | grep -q "cycle:"; then
        OK=$((OK+1))
    else
        ERR=$((ERR+1))
        echo "$(date -Iseconds) ERR: $f — $(echo "$OUT" | tail -3)" >> ~/workspaces/fl4write/runner.log
    fi
done
echo "$(date -Iseconds) cycle: $OK ok / $ERR errors" >> ~/workspaces/fl4write/runner.log
