#!/usr/bin/env bash
# C2 guard: the runner reads this dir via git pull. Uncommitted files = invisible.
set -u
# MECE round-6 (sol F6-E05): never certify a MISSING checkout as clean
cd ~/workspaces/fl4write || { echo "ALERT: cannot cd to ~/workspaces/fl4write — checkout missing"; exit 1; }
# MECE rounds 1-3: ANY porcelain line is a hazard (MM/AM/UU included);
# report honest untracked vs modified counts (luna F3-005)
STATUS=$(git status --porcelain 2>&1)
RC=$?
if [ $RC -ne 0 ]; then
  # F8-E002: a FAILED git command must never certify 'clean' — checkout
  # integrity is unknown, fail loudly
  echo "ALERT: git status failed (rc=$RC) — checkout integrity UNKNOWN"
  echo "$STATUS" | head -5
  exit 1
fi
U=$(printf '%s\n' "$STATUS" | grep -c '^??' || true)
M=$(printf '%s\n' "$STATUS" | grep -v '^??' | grep -c . || true)
TOTAL=$((U + M))
if [ "$TOTAL" -gt 0 ]; then
  echo "ALERT: $U untracked + $M changed files (modified/added/deleted/renamed) in the runner config home — invisible to the nucbox runner until committed"
  git status --porcelain | head -8
  exit 1
fi
echo "clean"
