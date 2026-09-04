"""Acceptance metrics — track whether posted findings get addressed.

The Greptile lesson: 79% nits = 19% address rate. Without measuring address
rate, we're flying blind on quality.

Audit 2026-09-01: the previous implementation counted ✅/"Addressed"
substrings in our own comment body — strings the renderer never emitted, so
the metric was structurally 0% forever while README advertised it. Real
signals now, derived from the persistent comment itself:

- `findings` — findings in the CURRENT comment (parsed via the renderer's
  finding-line contract).
- `resolved` — prior findings that no longer appear (the renderer's ✅
  Resolved section; recomputed here from the same contract).
- `reactions` — 👍/🎉 on our persistent comment = acknowledged.

`acceptance_snapshot` aggregates across open PRs with one: {addressed,
total, rate}. PRs without our comment are excluded from the denominator.
"""

from __future__ import annotations

import logging
from typing import Any

from .config import RepoConfig
from .forges import ForgeAdapter, ForgeError
from .renderer import parse_finding_lines

log = logging.getLogger("fl4write.metrics")


def comment_signals(forge: ForgeAdapter, repo: str, pr_number: int) -> dict[str, int] | None:
    """Signals for one PR from our persistent comment, or None without one."""
    try:
        existing = forge.get_persistent_comment(repo, pr_number)
    except (ValueError, TypeError, KeyError, AttributeError, IndexError):
        return None  # UltraQA round 2: malformed comment tuples degrade, never raise
    if not existing or not isinstance(existing, (tuple, list)) or len(existing) < 2:
        return None
    body = existing[1]
    if not isinstance(body, str):
        return None
    current = parse_finding_lines(body)
    # MECE round-6 (luna-max F6-C014): count resolved markers ONLY at line
    # starts — a model-quoted message containing the marker substring used to
    # inflate resolved/acceptance counts
    import re as _re
    resolved = len(_re.findall(r"(?m)^- ✅ `~", body))
    reactions = 0
    summary = getattr(forge, "reaction_summary", None)
    if summary is not None:
        # MECE round-2 (terra F2-005/006): reactions are counted ONLY for the
        # acceptance contents (+1/hooray); an 👀 or 🚀 must not count as
        # "addressed". Values are {login: n} dicts — malformed rows degrade.
        try:
            groups = summary(repo, existing[0]) or {}
            for content, voters in groups.items():
                if content not in ("+1", "hooray"):
                    continue
                if isinstance(voters, dict):
                    reactions += sum(1 for v in voters.values() if v)
        except (ForgeError, ValueError, TypeError, KeyError, AttributeError):
            pass  # reactions are an enhancement, never a dependency
    return {
        "findings": len(current),
        "resolved": resolved,
        "reactions": reactions,
        "addressed": min(resolved + reactions, len(current) + resolved),
    }


def acceptance_snapshot(forge: ForgeAdapter, config: RepoConfig) -> dict[str, Any]:
    """Repo-level acceptance across open AND recently-merged PRs (L6: this
    org's PRs merge in ~60s — an open-only denominator was structurally n/a;
    the post-merge/retro findings live on MERGED PRs). Best-effort: never
    raises."""
    total = addressed = 0
    prs: list = []
    try:
        prs = list(forge.list_open_prs(config.repo))
    except (ForgeError, ValueError, TypeError, KeyError, AttributeError) as exc:
        # UltraQA round 2: shape errors are external-surface failures — this
        # function's contract is "never raises" (acceptance=n/a on the line)
        log.warning("acceptance open-list skipped (%s): %s", config.repo, exc)
    if hasattr(forge, "list_merged_prs"):
        try:
            from datetime import datetime, timedelta, timezone

            since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
            prs += [
                p for p in forge.list_merged_prs(config.repo, since)
                if all(not (p.number == q.number) for q in prs)
            ]
        except (ForgeError, NotImplementedError, ValueError, TypeError, KeyError,
                AttributeError):
            pass  # merged sampling is additive, never load-bearing
    # UltraQA round 2: row-shape guard — a half-parsed adapter returning
    # garbage rows must not crash the snapshot (contract: never raises)
    prs = [p for p in prs if getattr(p, "number", None) is not None]
    seen: set[int] = set()
    for pr in prs:
        if pr.number in seen:  # merged+open overlap or duplicate pages (Sol#7)
            continue
        seen.add(pr.number)
        try:
            sig = comment_signals(forge, config.repo, pr.number)
        except ForgeError:
            continue
        if sig is None:
            continue
        total += sig["findings"] + sig["resolved"]
        # sig['addressed'] is already min-capped — recomputing from raw parts
        # let reactions exceed 100% (Sol#7 repro: 1 finding + 2 reactions = 200%)
        addressed += sig["addressed"]
    rate = f"{100 * addressed / total:.0f}%" if total else "n/a"
    return {"total": total, "addressed": addressed, "rate": rate}
