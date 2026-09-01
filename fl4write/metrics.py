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
    existing = forge.get_persistent_comment(repo, pr_number)
    if not existing:
        return None
    body = existing[1]
    current = parse_finding_lines(body)
    resolved = body.count("- ✅ `~")
    reactions = 0
    summary = getattr(forge, "reaction_summary", None)
    if summary is not None:
        try:
            for group in (summary(repo, existing[0]) or {}).values():
                reactions += sum(1 for v in (group or {}).values() if v)
        except ForgeError:
            pass  # reactions are an enhancement, never a dependency
    return {
        "findings": len(current),
        "resolved": resolved,
        "reactions": reactions,
        "addressed": min(resolved + reactions, len(current) + resolved),
    }


def acceptance_snapshot(forge: ForgeAdapter, config: RepoConfig) -> dict[str, Any]:
    """Repo-level acceptance across open PRs. Best-effort: never raises."""
    total = addressed = 0
    try:
        prs = forge.list_open_prs(config.repo)
    except ForgeError as exc:
        log.warning("acceptance snapshot skipped (%s): %s", config.repo, exc)
        return {"total": 0, "addressed": 0, "rate": "n/a"}
    for pr in prs:
        try:
            sig = comment_signals(forge, config.repo, pr.number)
        except ForgeError:
            continue
        if sig is None:
            continue
        total += sig["findings"] + sig["resolved"]
        addressed += sig["resolved"] + sig["reactions"]
    rate = f"{100 * addressed / total:.0f}%" if total else "n/a"
    return {"total": total, "addressed": addressed, "rate": rate}
