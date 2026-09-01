#!/usr/bin/env bash
# make-gauntlet-pr — full-tree FL4WRITE review vehicle for a published repo.
# Usage: make-gauntlet-pr.sh <owner>/<repo> [local-workdir]
# Construction (09-01 hard-won): GitHub refuses orphan<->main PRs (no common
# history) and single-commit repos yield "no commits between" — so: base =
# empty tree COMMITTED WITH the repo root as parent (common history ✓);
# head = marker commit carrying the default-branch tree with both parents.
# Diff base->head = the ENTIRE published tree. The PR NEVER MERGES.
# After fixes on the default branch, refresh: re-run this script with --refresh
# to rebuild the target marker (new SHA -> fl4write re-reviews).
set -euo pipefail
R="${1:?usage: make-gauntlet-pr.sh <owner>/<repo> [workdir]}"
WD="${2:-$(mktemp -d)}"
REFRESH=0
[ "${1:-}" = "--refresh" ] && { REFRESH=1; shift; R="${1:?repo required}"; WD="${2:-$WD}"; }

if [ ! -d "$WD/.git" ]; then
  git clone -q "https://github.com/$R.git" "$WD"
fi
cd "$WD"
DEFAULT=$(gh repo view "$R" --json defaultBranchRef --jq .defaultBranchRef.name)
git fetch -q origin "$DEFAULT"
ROOT=$(git rev-list --max-parents=0 "origin/$DEFAULT" | tail -1)
EMPTY_TREE=$(git hash-object -t tree /dev/null)
BASE_C=$(git commit-tree "$EMPTY_TREE" -p "$ROOT" -m "gauntlet: empty baseline (root-anchored) — full-tree review vehicle, never merges")
HEAD_C=$(git commit-tree "origin/$DEFAULT^{tree}" -p "origin/$DEFAULT" -p "$BASE_C" -m "gauntlet: review target marker (tree identical to $DEFAULT @ $(git rev-parse --short origin/$DEFAULT))")
git push -q -f origin "$BASE_C":refs/heads/gauntlet/full-review "$HEAD_C":refs/heads/gauntlet/target

BODY="CEO order 2026-09-01: every published repo passes the hardcore FL4WRITE review+fix loop, retroactively. Base = empty tree anchored to the repo root; head = marker carrying the default-branch tree; the diff is the ENTIRE published tree. Findings get fixed on $DEFAULT; the target branch is refreshed after each fix so the PR re-reviews; loop until a full cycle returns zero Critical and zero Major. This PR never merges — it is the standing review vehicle."

if [ "$REFRESH" = "1" ]; then
  echo "target refreshed to $(git rev-parse --short origin/$DEFAULT); fl4write re-reviews on next cycle"
  exit 0
fi
gh pr view 1 -R "$R" >/dev/null 2>&1 && { echo "gauntlet PR already open"; exit 0; }
gh pr create -R "$R" --base gauntlet/full-review --head gauntlet/target \
  --title "FL4WRITE retroactive gauntlet: full-tree review of published HEAD" --body "$BODY"
