"""Renderer: the BEHAVIOR.md comment contract + tone presets + design system v1.

Persistent-comment law: ONE comment per PR, created once, then EDITED IN PLACE
on every re-review (edit-in-place never re-notifies — Codecov's law). New
findings get the 🆕 delta marker; resolved findings get the ✅ marker.
Tone is a renderer-only preset: the analyzer is tone-blind; roast is
internal-only and HARD-overridden for fork PRs and first-time contributors;
security-urgency is always rendered regardless of tone.

Design system v1: severity emoji badges, severity-count table header,
collapsible fix proposals, visible branded footer, personality per tone.
"""

from __future__ import annotations

from .config import RepoConfig
from .models import Finding, PullRequest

MARKER = "codesitter:v1:{review_hash}"

_SEVERITY_EMOJI = {"Critical": "🔴", "Major": "🟠", "Minor": "🟡", "Nit": "🔵"}
_URGENCY = {"Critical": "🚨 **Do NOT merge** until this is addressed."}

_TONES = {
    "quiet": "",
    "balanced": "> _Thanks for this PR. Here's what I found:_\n",
    "assertive": "> _Straight to it:_\n",
    "roast": (
        "> 🔥 **Roast mode.** Findings ranked by how much they'll hurt at 3am. No feelings spared; none targeted.\n\n"
    ),
}


def _tone_for(pr: PullRequest, config: RepoConfig) -> str:
    if pr.is_fork:
        return config.tone_fork_override
    return config.tone


def render_finding(f: Finding, tone: str) -> str:
    """One finding as a section with emoji badge + collapsible fix proposal."""
    emoji = _SEVERITY_EMOJI.get(f.severity, "⚪")
    urgency = _URGENCY.get(f.severity, "")
    parts: list[str] = [f"### {emoji} {f.severity} — `{f.path}:{f.line}` — `{f.rule_id}`", ""]
    parts.append(f.message)
    if f.proposal:
        parts += [
            "",
            "<details>",
            "<summary>💡 How to fix</summary>",
            "",
            "```",
            f.proposal,
            "```",
            "",
            "</details>",
        ]
    if urgency:
        parts += ["", urgency]
    return "\n".join(parts)


def _severity_table(findings: list[Finding]) -> str:
    counts = _count_severities(findings)
    rows = [
        f"| 🔴 Critical | {counts.get('Critical', 0)} |",
        f"| 🟠 Major | {counts.get('Major', 0)} |",
        f"| 🟡 Minor | {counts.get('Minor', 0)} |",
        f"| 🔵 Nit | {counts.get('Nit', 0)} |",
    ]
    return "| Severity | Count |\n|---|---|\n" + "\n".join(rows)


def render_review(
    pr: PullRequest,
    findings: list[Finding],
    config: RepoConfig,
    review_hash: str,
    previous_findings: list[Finding] | None = None,
    gatekeeper_dropped: int = 0,
) -> str:
    """Full persistent-comment body with the design system applied."""
    tone = _tone_for(pr, config)
    previous_keys = {(f.path, f.line, f.rule_id) for f in (previous_findings or [])}

    head = "## 🔍 codesitter review\n\n"

    if findings:
        head += _severity_table(findings) + "\n\n"
        head += f"`{pr.repo}#{pr.number}` @ `{pr.head_sha[:8]}` · {len(findings)} findings"
        if gatekeeper_dropped:
            head += f" · 🧹 {gatekeeper_dropped} nits filtered"
        head += "\n\n"
        body = _TONES[tone] + "\n---\n\n".join(
            ("🆕 " if (f.path, f.line, f.rule_id) not in previous_keys else "") + render_finding(f, tone)
            for f in findings
        )
    else:
        body = _TONES[tone] + "## ✨ Clean review — nothing to fix.\n\nGo merge it. 🎉"

    footer = (
        f"\n\n---\n"
        f"*Reviewed by **codesitter** · tone: {tone} · "
        f"[org law](https://github.com/KyaniteLabs/codesitter/blob/main/codesitter/law.py)*\n"
        f"<!-- {MARKER.format(review_hash=review_hash)} -->\n"
    )
    out = head + body + footer

    from . import scrub

    scrub.assert_clean(out.replace(MARKER.format(review_hash=review_hash), ""))
    return out


def _count_severities(findings: list[Finding]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for f in findings:
        counts[f.severity] = counts.get(f.severity, 0) + 1
    return counts
