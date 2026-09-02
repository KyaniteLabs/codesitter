"""Tier scheduler — the soft-launch scale answer, Phase 1 (consensus-gated,
fl4write #6: Architect APPROVE + Critic APPROVE-with-4-amendments).

DESIGN LAWS (from the gate):
- DERIVED-ONLY: reads state files + two forge probes; NEVER writes anything
  (LEARNINGS #17 — no second load/save pair). The engine stays untouched.
- FAIL-SAFE classification: missing/corrupt state → UNKNOWN → WARM + alert
  (corruption masquerades as inactivity — the classifier must fail toward
  MORE frequency, never less). New repo (no state) → HOT bootstrap.
- The per-owner reality: KyaniteLabs is an org (/orgs/ probe);
  simongonzalezdc is a USER (/users/ probe — /orgs/ 404s). Forgejo-primary
  repos have NO GitHub pushed signal → default WARM (LEARNINGS #24: this
  org merges in ~60s — a busy Forgejo repo silently parked cold is a
  regression).
- Duplicate configs (same repo: value) ALERT, never silent-dedupe
  (resonant-gifts + resonant-tastecheck both name resonant-tastecheck
  today — the fleet has been double-cycling it hourly).
- Cadence is a latency knob, not a correctness knob (the head-SHA
  predicate self-heals); the watermark catch-up is unbounded once it
  exists, so cold repos lose nothing but time.

Output: one config filename per line whose repo is DUE this cycle, plus
ALERT lines (surfaced by the runner's unconditional ALERT grep). The
scheduler ALSO prints the aggregate plan line for runner.log.
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from pathlib import Path

TIER_CADENCE_S = {"hot": 3600, "warm": 4 * 3600, "cold": 24 * 3600}
STATE_DIR = Path.home() / ".fl4write"


def _state_path(repo: str) -> Path:
    return STATE_DIR / f"{repo.replace('/', '__')}.state.json"


def _read_state(repo: str) -> dict | None:
    """None = missing or corrupt (UNKNOWN class — never 'inactive')."""
    p = _state_path(repo)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _probe_pushed(owner_type: str, owner: str, token_env: str = "CODESITTER_GITHUB_TOKEN") -> dict[str, float]:
    """One probe per owner: {repo_name: pushed_at_epoch}. User accounts need
    /users/ (the /orgs/ endpoint 404s on them — the Critic's amendment 4)."""
    endpoint = (
        f"https://api.github.com/orgs/{owner}/repos?sort=pushed&per_page=100"
        if owner_type == "org"
        else f"https://api.github.com/users/{owner}/repos?sort=pushed&per_page=100"
    )
    token = os.environ.get(token_env, "")
    req = urllib.request.Request(  # noqa: S310
        endpoint,
        headers={"Accept": "application/vnd.github+json",
                 **({"Authorization": f"token {token}"} if token else {})},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            rows = json.loads(resp.read().decode())
        import calendar

        out = {}
        for r in rows if isinstance(rows, list) else []:
            pushed = r.get("pushed_at") or ""
            try:
                out[r.get("name", "")] = calendar.timegm(time.strptime(pushed, "%Y-%m-%dT%H:%M:%SZ"))
            except ValueError:
                continue
        return out
    except Exception:  # noqa: BLE001 — probe failure never blocks scheduling
        return {}


def classify(repo: str, forge_github: bool, pushed_epoch: float | None,
             now: float) -> tuple[str, str]:
    """-> (tier, reason). Hot = pushed in the last 25h OR bootstrap OR
    watermark/open-PR activity. Warm = pushed in 7d or unknown. Cold = quiet
    beyond 7d with healthy state."""
    st = _read_state(repo)
    if st is None:
        if not _state_path(repo).exists():
            return "hot", "bootstrap (no state file — first cycle)"
        return "warm", "UNKNOWN: state unreadable/corrupt — failing toward frequency"
    if not forge_github:
        # Forgejo repos have no GitHub pushed signal; the org merges fast
        # (LEARNINGS #24) — WARM floor, refined by local activity below.
        base = "warm"
    elif pushed_epoch and (now - pushed_epoch) < 25 * 3600:
        base = "hot"
    elif pushed_epoch and (now - pushed_epoch) < 7 * 86400:
        base = "warm"
    elif pushed_epoch:
        base = "cold"
    else:
        base = "warm"  # probe failed for this repo — never fail toward cold
    # local activity refines upward: watermark advanced or open PRs present
    has_open = bool(st.get("prs"))
    wm = st.get("merged_since")
    if base == "cold" and (has_open or wm):
        base = "warm"
    return base, f"pushed={'recent' if base == 'hot' else base}; open_prs={has_open}; wm={bool(wm)}"


def due(configs: list[tuple[str, str, bool]], now: float | None = None,
        pushed_map: dict[str, float] | None = None) -> list[str]:
    """configs = [(filename, repo, is_github_primary)]. Returns due filenames
    (staggered colds across their cadence) + prints the plan line."""
    now = now or time.time()
    by_repo: dict[str, str] = {}
    for fname, repo, _ in configs:
        if repo in by_repo:
            print(f"ALERT: duplicate config for {repo}: {by_repo[repo]} and {fname} — "
                  f"cycling {by_repo[repo]} only (dedupe ALERTS, never silent)")
            continue
        by_repo[repo] = fname
    out = []
    counts = {"hot": 0, "warm": 0, "cold": 0}
    for repo, fname in by_repo.items():
        forge_github = next(g for f, r, g in configs if r == repo)
        pushed = (pushed_map or {}).get(repo.split("/", 1)[1]) if forge_github else None
        tier, reason = classify(repo, forge_github, pushed, now)
        counts[tier] = counts.get(tier, 0) + 1
        # stagger: cold repos due at (hash % 24)h marks; warm at (hash % 4)h
        slug = sum(ord(c) for c in repo)
        cadence = TIER_CADENCE_S[tier]
        phase = (slug % cadence) if tier != "hot" else 0
        n = int(now)
        due_now = (n % cadence) >= phase and ((n - phase) % cadence) < 3600
        if tier == "hot" or due_now:
            out.append(fname)
        if "UNKNOWN" in reason:
            print(f"ALERT: {repo} scheduled {tier}: {reason}")
    print(f"tiers: {counts['hot']}h/{counts['warm']}w/{counts['cold']}c — {len(out)} due")
    return out


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("configs", nargs="+", help="config filenames")
    ap.add_argument("--json", action="store_true", help="emit due list as JSON")
    args = ap.parse_args()
    from fl4write.config import load_config

    parsed = []
    for f in args.configs:
        try:
            c = load_config(f)
            github = "api.github.com" in next(
                b.api_base for b in c.forges.values() if b.role == "primary"
            )
            parsed.append((f, c.repo, github))
        except Exception as exc:  # noqa: BLE001 — a bad config cycles anyway
            print(f"ALERT: config {f} unparseable ({exc}) — scheduled hot as fallback")
            parsed.append((f, f"__unparsed__{f}", True))
    org_map = _probe_pushed("org", "KyaniteLabs")
    user_map = _probe_pushed("user", "simongonzalezdc")
    pushed = {**org_map, **user_map}
    due_files = due(parsed, pushed_map=pushed)
    if args.json:
        print(json.dumps(due_files))
    else:
        for f in due_files:
            print(f)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
