#!/usr/bin/env bash
# C2 guard: the runner reads this dir via git pull. Uncommitted files = invisible.
set -u
cd ~/workspaces/fl4write
# MECE round-1 (glm F1-3): staged/renamed/deleted states were invisible to
# the C2 guard — the runner pulls with rebase; ANY porcelain line is a hazard
N=$(git status --porcelain | grep -cE '^(\?\?| M|M |A | D|D |R |R )' || true)
M=$N
if [ "$N" -gt 0 ] || [ "$M" -gt 0 ]; then
  echo "ALERT: $N untracked + $M modified files in the runner config home — invisible to the nucbox runner until committed"
  git status --porcelain | head -8
  exit 1
fi
echo "clean"
