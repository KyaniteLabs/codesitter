#!/usr/bin/env bash
# C2 guard: the runner reads this dir via git pull. Uncommitted files = invisible.
set -u
cd ~/workspaces/fl4write
# MECE rounds 1-2 (glm F1-3, sol F2-003): ANY porcelain line is a hazard —
# including MM/AM/UU two-column states the column-anchored regex missed
N=$(git status --porcelain | grep -c . || true)
M=$N
if [ "$N" -gt 0 ] || [ "$M" -gt 0 ]; then
  echo "ALERT: $N untracked + $M modified files in the runner config home — invisible to the nucbox runner until committed"
  git status --porcelain | head -8
  exit 1
fi
echo "clean"
