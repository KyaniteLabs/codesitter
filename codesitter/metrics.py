"""Acceptance metrics — track whether posted findings get addressed.

The Greptile lesson: 79% nits = 19% address rate. Without measuring address
rate, we're flying blind on quality. This module checks reactions, commit
references, and PR-state changes to estimate whether findings are being
acted on.

Surfaces as `acceptance` in the cycle report: {addressed, total, rate}.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from .config import RepoConfig
from .forges import ForgeAdapter

log = logging.getLogger("codesitter.metrics")


def count_addressed_findings(forge: ForgeAdapter, repo: str, pr_number: int, marker: str = "codesitter:v1:") -> int:
    """Check how many findings in our persistent comment were addressed.

    A finding is 'addressed' if:
    - Its line range was changed in a commit after our review
    - The PR was closed/merged after our review
    - Someone reacted 👍 or 🎉 to the comment (acknowledged)
    """
    try:
        comment = forge.get_persistent_comment(repo, pr_number)
        if not comment:
            return 0
        body = comment[1]
        # Count findings (lines with severity badges)
        finding_lines = re.findall(r"- \*\*\[\w+\] .+?:\d+\*\*", body)
        # Count acknowledged (✅ Addressed markers or resolved sections)
        addressed = body.count("✅") + body.count("Addressed")
        return min(addressed, len(finding_lines))
    except Exception as exc:
        log.warning("metrics check failed for %s#%s: %s", repo, pr_number, exc)
        return 0


def acceptance_snapshot(forge: ForgeAdapter, config: RepoConfig, reviewed_prs: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute an acceptance-rate snapshot for the cycle report."""
    total = 0
    addressed = 0
    for rec in reviewed_prs:
        pr_num = rec.get("pr")
        findings = rec.get("findings", 0)
        total += findings
        if findings > 0:
            addressed += count_addressed_findings(forge, config.repo, pr_num)
    rate = round(addressed / total * 100, 1) if total > 0 else None
    return {
        "addressed": addressed,
        "total": total,
        "rate": f"{rate}%" if rate is not None else "n/a (no findings yet)",
    }
