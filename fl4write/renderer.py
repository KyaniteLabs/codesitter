"""Renderer: the BEHAVIOR.md comment contract + tone presets + design system v1.

Persistent-comment law: ONE comment per PR, created once, then EDITED IN PLACE
on every re-review (edit-in-place never re-notifies — Codecov's law). New
findings get the 🆕 delta marker; findings present last cycle and gone now are
listed under ✅ Resolved. Tone is a renderer-only preset: the analyzer is
tone-blind; roast is internal-only and HARD-overridden for fork PRs and
first-time contributors; security-urgency is always rendered regardless of tone.

Design system v1: severity emoji badges, severity-count table header,
collapsible fix proposals, visible branded footer, personality per tone.

Audit 2026-09-01: the finding-line format has ONE source of truth here —
render_finding emits it, FINDING_LINE_RE parses it back, and a round-trip test
pins them together. The engine previously parsed a legacy format nothing
emitted, so `previous_findings` was always empty and every finding was 🆕
forever. Resolved findings now actually render (✅ section) instead of
vanishing silently.
"""

from __future__ import annotations

import re

from .config import RepoConfig
from .models import Finding, PullRequest

MARKER = "fl4write:v1:{review_hash}"
# Lookup must ALSO recognize pre-rename comments (posted as codesitter:v1)
# or every open PR would get a duplicate review at the rename boundary.
LEGACY_MARKER_PREFIXES = ("fl4write:v1:", "codesitter:v1:")

_SEVERITY_EMOJI = {"Critical": "🔴", "Major": "🟠", "Minor": "🟡", "Nit": "🔵"}
_URGENCY = {"Critical": "🚨 **Do NOT merge** until this is addressed."}
_URGENCY_POST_MERGE = {"Critical": "🚨 **Landed on main** — fix-forward strongly recommended."}

# The finding-line contract: rendered heading and parsed-back identity are the
# SAME format, defined once. Groups: sev, path, line, rule.
FINDING_LINE_FMT = "### {emoji} {sev} — `{path}:{line}` — `{rule}`"
FINDING_LINE_RE = re.compile(
    r"^(?:🆕 )?### \S+ (?P<sev>Critical|Major|Minor|Nit) — `(?P<path>[^:`]+):(?P<line>\d+)` — `(?P<rule>[^`]+)`",
    re.MULTILINE,
)

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


def _md_escape_block(text: str) -> str:
    """Finding text is MODEL output in a markdown context: collapse fence
    runs so a fenced snippet in a proposal cannot break out of the collapsible
    section and swallow the rest of the comment."""
    return re.sub(r"(`{3,})", "``", text)


def parse_finding_lines(body: str) -> list[tuple[str, str, int, str]]:
    """Parse (severity, path, line, rule_id) tuples out of a rendered comment.
    The inverse of render_finding's heading — kept here so the pair cannot drift."""
    return [
        (m.group("sev"), m.group("path"), int(m.group("line")), m.group("rule"))
        for m in FINDING_LINE_RE.finditer(body)
    ]


def render_finding(f: Finding, tone: str, post_merge: bool = False) -> str:
    """One finding as a section with emoji badge + collapsible fix proposal."""
    emoji = _SEVERITY_EMOJI.get(f.severity, "⚪")
    urgency = (_URGENCY_POST_MERGE if post_merge else _URGENCY).get(f.severity, "")
    parts: list[str] = [
        FINDING_LINE_FMT.format(emoji=emoji, sev=f.severity, path=f.path, line=f.line, rule=f.rule_id),
        "",
    ]
    parts.append(_md_escape_block(f.message))
    if f.proposal:
        parts += [
            "",
            "<details>",
            "<summary>💡 How to fix</summary>",
            "",
            "````",
            _md_escape_block(f.proposal),
            "````",
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
    diff_truncated: bool = False,
    post_merge: bool = False,
) -> str:
    """Full persistent-comment body with the design system applied."""
    tone = _tone_for(pr, config)
    previous_keys = {(f.path, f.line, f.rule_id) for f in (previous_findings or [])}
    current_keys = {(f.path, f.line, f.rule_id) for f in findings}
    resolved = [f for f in (previous_findings or []) if (f.path, f.line, f.rule_id) not in current_keys]

    head = "## 🔍 FL4WRITE review (post-merge)\n\n" if post_merge else "## 🔍 FL4WRITE review\n\n"

    if findings or resolved:
        head += _severity_table(findings) + "\n\n"
        head += f"`{pr.repo}#{pr.number}` @ `{pr.head_sha[:8]}` · {len(findings)} findings"
        if gatekeeper_dropped:
            head += f" · 🧹 {gatekeeper_dropped} nits filtered"
        if diff_truncated:
            head += " · ⚠️ **partial review — diff was truncated**"
        head += "\n\n"
        sections = []
        if findings:
            sections.append(
                _TONES[tone]
                + "\n---\n\n".join(
                    ("🆕 " if (f.path, f.line, f.rule_id) not in previous_keys else "") + render_finding(f, tone, post_merge)
                    for f in findings
                )
            )
        if resolved:
            lines = "\n".join(f"- ✅ `~{f.path}:{f.line}` ({f.rule_id})" for f in resolved)
            sections.append(f"### ✅ Resolved since last review\n\n{lines}")
        body = "\n\n---\n\n".join(sections)
    elif post_merge:
        body = _TONES[tone] + "## ✨ Clean review — nothing to fix.\n\nMerged in good shape. ✅"
    else:
        body = _TONES[tone] + "## ✨ Clean review — nothing to fix.\n\nGo merge it. 🎉"

    footer = (
        f"\n\n---\n"
        f"*Reviewed by **FL4WRITE** · tone: {tone} · "
        f"[org law](https://github.com/KyaniteLabs/fl4write/blob/main/fl4write/law.py)*\n"
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
