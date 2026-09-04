#!/usr/bin/env bash
# C2 guard: the runner reads this dir via git pull. Uncommitted files = invisible.
set -u
cd ~/workspaces/fl4write
# MECE rounds 1-3: ANY porcelain line is a hazard (MM/AM/UU included);
# report honest untracked vs modified counts (luna F3-005)
U=$(git status --porcelain | grep -c '^??' || true)
M=$(git status --porcelain | grep -v '^??' | grep -c . || true)
TOTAL=$((U + M))
if [ "$TOTAL" -gt 0 ]; then
  echo "ALERT: $U untracked + $M modified files in the runner config home — invisible to the nucbox runner until committed"
  git status --porcelain | head -8
  exit 1
fi
echo "clean"
