"""Renderer: the BEHAVIOR.md comment contract + tone presets.

Persistent-comment law: ONE comment per PR, created once, then EDITED IN PLACE
on every re-review (edit-in-place never re-notifies — Codecov's law). New
findings get the NEW delta marker; resolved findings get the addressed marker.
Tone is a renderer-only preset (Lane D): the analyzer is tone-blind; roast is
internal-only and HARD-overridden for fork PRs and first-time contributors;
security-urgency is always rendered regardless of tone.
"""

from __future__ import annotations

from .config import RepoConfig
from .models import Finding, PullRequest

MARKER = "codesitter:v1:{review_hash}"

_TONES = {
    "quiet": "",
    "balanced": "",
    "assertive": "",
    "roast": (
        "> 🔥 Roast mode (internal repo, opted in). Findings below are ranked by "
        "how much they'll hurt at 3am. No feelings were spared; none were targeted.\n\n"
    ),
}

_URGENCY = {"Critical": "🚨 **Do NOT merge** until this is addressed."}


def _tone_for(pr: PullRequest, config: RepoConfig) -> str:
    if pr.is_fork:
        return config.tone_fork_override  # hard override, not configurable away
    return config.tone


def render_finding(f: Finding, tone: str) -> str:
    urgency = _URGENCY.get(f.severity, "")
    line = f"- **[{f.severity}] {f.path}:{f.line}** ({f.category}, rule `{f.rule_id}`) — {f.message}"
    if f.proposal:
        line += f"\n  - Proposal: `{f.proposal}`"
    if urgency:
        line += f"\n  - {urgency}"
    return line


def render_review(
    pr: PullRequest,
    findings: list[Finding],
    config: RepoConfig,
    review_hash: str,
    previous_findings: list[Finding] | None = None,
) -> str:
    """Full persistent-comment body. previous_findings drives the NEW deltas."""
    tone = _tone_for(pr, config)
    previous_keys = {(f.path, f.line, f.rule_id) for f in (previous_findings or [])}
    head = f"## codesitter review — {pr.repo}#{pr.number} @ `{pr.head_sha[:8]}`\n\n"
    if findings:
        digest = " · ".join(f"**{n}** {s}" for s, n in sorted(_count_severities(findings).items()))
        body = (
            f"Findings: {digest}\n\n"
            + _TONES[tone]
            + "\n".join(
                ("🆕 " if (f.path, f.line, f.rule_id) not in previous_keys else "") + render_finding(f, tone)
                for f in findings
            )
        )
    else:
        body = _TONES[tone] + "No actionable comments were generated in the recent review. 🎉"
    footer = f"\n\n---\n<!-- {MARKER.format(review_hash=review_hash)} -->\n"
    out = head + body + footer
    from . import scrub

    scrub.assert_clean(out.replace(MARKER.format(review_hash=review_hash), ""))
    return out


def _count_severities(findings: list[Finding]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for f in findings:
        counts[f.severity] = counts.get(f.severity, 0) + 1
    return counts
