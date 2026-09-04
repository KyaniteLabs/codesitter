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
try:
    from .state import STATE_VERSION  # one source of truth (state.py)
except ImportError:  # pragma: no cover - standalone invocation
    STATE_VERSION = 1


def _known_repo(repo: str) -> bool:
    """Has this repo EVER cycled? The telemetry stream is the durable record
    (a result-file or telemetry line naming the repo = established)."""
    tel = STATE_DIR / "telemetry.jsonl"
    try:
        with tel.open(encoding="utf-8", errors="ignore") as fh:
            return any(f'"repo": "{repo}"' in line for line in fh)
    except OSError:
        return False


def _state_path(repo: str) -> Path:
    return STATE_DIR / f"{repo.replace('/', '__')}.state.json"


def _read_state(repo: str) -> dict | None:
    """None = missing or unusable (UNKNOWN class — never 'inactive'). Valid
    JSON with the wrong SHAPE (a list, a string) is also unusable (Sol#9).
    MECE round-5 (sol F5-005): an unknown STATE VERSION is unusable too —
    the canonical loader reconciles unknown versions; a scheduler that called
    them healthy would park a future-format state as cold."""
    p = _state_path(repo)
    try:
        st = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(st, dict) or not isinstance(st.get("prs", {}), dict):
        return None  # shape-corrupt = UNKNOWN, never a crash (Sol#9)
    if not isinstance(st.get("version"), int) \
            or isinstance(st.get("version"), bool) \
            or st.get("version") != STATE_VERSION:
        # MECE round-6 (luna-max F6-C019): True == 1 — boolean versions must
        # not pass the int check; unknown/future = UNKNOWN, never cold
        return None
    return st


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
        if not _state_path(repo).exists() and not _known_repo(repo):
            return "hot", "bootstrap (no state file AND never cycled — new repo)"
        # deleted/missing state on an ESTABLISHED repo is UNKNOWN, never
        # bootstrap-hot and never cold (Sol#9: absence is unproven, not new)
        return "warm", "UNKNOWN: state missing/corrupt on an established repo — failing toward frequency"
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
    # local activity refines upward: open PRs, or a RECENT post-merge
    # watermark. MECE round-5 (sol F5-006): the watermark alone is durable
    # historical state, not current activity — an ancient watermark used to
    # upgrade every post-merge-enabled repo out of cold forever.
    has_open = bool(st.get("prs"))
    wm_recent = False
    wm = st.get("merged_since")
    if isinstance(wm, str) and wm:
        import calendar
        from datetime import datetime as _dt

        try:
            wm_epoch = calendar.timegm(time.strptime(wm, "%Y-%m-%dT%H:%M:%SZ"))
        except ValueError:
            try:
                wm_epoch = _dt.fromisoformat(wm.replace("Z", "+00:00")).timestamp()
            except ValueError:
                wm_epoch = None
        if wm_epoch is not None:
            wm_recent = (now - wm_epoch) < 7 * 86400
    if base == "cold" and (has_open or wm_recent):
        base = "warm"
    return base, f"pushed={'recent' if base == 'hot' else base}; open_prs={has_open}; wm_recent={wm_recent}"


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
        pushed = (pushed_map or {}).get(repo) if forge_github else None
        tier, reason = classify(repo, forge_github, pushed, now)
        counts[tier] = counts.get(tier, 0) + 1
        # stagger by a STABLE FULL-RANGE hash (Sol#5: additive ASCII sums
        # cluster real repo names into the same hourly slot)
        import hashlib

        cadence = TIER_CADENCE_S[tier]
        phase = int(hashlib.sha256(repo.encode()).hexdigest()[:8], 16) % cadence if tier != "hot" else 0
        n = int(now)
        due_now = ((n - phase) % cadence) < 3600
        if tier == "hot" or due_now:
            out.append(fname)
        if "UNKNOWN" in reason:
            print(f"ALERT: {repo} scheduled {tier}: {reason}")
    print(f"tiers: {counts['hot']}h/{counts['warm']}w/{counts['cold']}c — {len(out)} due")
    return out


def main() -> int:
    import argparse
    import contextlib
    import io

    ap = argparse.ArgumentParser()
    ap.add_argument("configs", nargs="+", help="config filenames")
    ap.add_argument("--json", action="store_true", help="emit due list as JSON (legacy)")
    ap.add_argument("--plan", action="store_true",
                    help="ONE envelope {due, alerts, summary} — the runner parses this "
                         "ONCE (3 invocations = 3x the probe cost)")
    args = ap.parse_args()
    from fl4write.config import load_config

    parsed = []
    alerts: list[str] = []
    for f in args.configs:
        try:
            c = load_config(f)
            github = "api.github.com" in next(
                b.api_base for b in c.forges.values() if b.role == "primary"
            )
            parsed.append((f, c.repo, github))
        except Exception as exc:  # noqa: BLE001 — a bad config cycles anyway
            alerts.append(f"config {f} unparseable ({str(exc)[:60]}) — scheduled hot as fallback")
            parsed.append((f, f"__unparsed__{f}", True))
    org_map = _probe_pushed("org", "KyaniteLabs")
    user_map = _probe_pushed("user", "simongonzalezdc")
    # keyed by FULL owner/name — a user fork sharing an org repo's bare name
    # must not overwrite the org timestamp (Sol#10)
    pushed = {}
    for mapping, owner in ((org_map, "KyaniteLabs"), (user_map, "simongonzalezdc")):
        for name, ts in mapping.items():
            pushed[f"{owner}/{name}"] = ts
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        due_files = due(parsed, pushed_map=pushed)
    for line in buf.getvalue().splitlines():  # scheduler ALERTs join the envelope
        if line.startswith("ALERT: "):
            alerts.append(line[len("ALERT: "):])
    summary = next((ln for ln in buf.getvalue().splitlines() if ln.startswith("tiers: ")), "")
    if args.plan:
        print(json.dumps({"due": due_files, "alerts": alerts, "summary": summary}))
    elif args.json:
        print(json.dumps(due_files))
    else:
        for a in alerts:
            print(f"ALERT: {a}")
        if summary:
            print(summary)
        for f in due_files:
            print(f)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
