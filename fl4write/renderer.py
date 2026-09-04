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
import unicodedata

from . import scrub
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
FINDING_LINE_FMT = "### {emoji} {sev} — {span} — `{rule}`"
FINDING_LINE_RE = re.compile(
    # MECE round-7 (luna F7-001): path and rule must stay SINGLE-LINE — a
    # rule spanning newlines let a crafted previous comment inject markdown
    # headings through the resolved-findings interpolation
    # F11-A5: the path/line span may be fenced with a backtick RUN (paths
    # containing a literal backtick use a wider fence) — the group must not
    # stop at a single backtick inside a wider fence
    r"^(?:🆕 )?### \S+ (?P<sev>Critical|Major|Minor|Nit) — (?P<f>`+)(?P<path>.*?):(?P<line>\d+)(?P=f) — `(?P<rule>[^`\n]+)`",
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
    section and swallow the rest of the comment, and escape heading-shaped
    lines so model text cannot mint fake finding sections or review headers
    in the posted comment (UltraQA round 1, ADV-04: a scrubbed message still
    rendered "### 🔴 Critical — fake.py:99 — general" as real structure)."""
    out = re.sub(r"(`{3,})", "``", text)
    # F13-A9: tilde fences are CommonMark structure too — an unclosed
    # ~~~ swallowed the urgency line, footer, and marker into a code block
    out = re.sub(r"(?m)^ {0,3}(~{3,})", lambda m: "\\" + m.group(1), out)
    # F9-A11: CommonMark treats up to THREE leading spaces as an ATX heading,
    # and '>' blockquote lines can still carry structure
    out = re.sub(r"(?m)^( {0,3})(#{1,6})(?=\s)",
                 lambda m: m.group(1) + "\\" + m.group(2), out)
    return re.sub(r"(?m)^ {0,3}>", "\\>", out)


def parse_finding_lines(body: str) -> list[tuple[str, str, int, str]]:
    """Parse (severity, path, line, rule_id) tuples out of a rendered comment.
    The inverse of render_finding's heading — kept here so the pair cannot drift."""
    return [
        (m.group("sev"), m.group("path"), int(m.group("line")), m.group("rule"))
        for m in FINDING_LINE_RE.finditer(body)
    ]


_CONTROL_ESCAPES = {}


def _escape_path(path: str) -> str:
    """F13-A12 (reopened F9-A09/F12-A6): the display transform is an
    INJECTIVE encoding of the raw path — backslash, newline, CR and every
    control/format codepoint become visible escapes, so distinct raw paths
    (a b vs a\nb; ab vs a\u200db) can never collapse onto one lifecycle
    identity. Rendered paths show the escapes; parse/compare uses the same
    encoding on both sides, so equality is byte-faithful."""
    out = []
    for ch in str(path):
        cp = ord(ch)
        if cp in (0x5C,):  # backslash first: double it
            out.append("\\\\")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif cp in (0x09, 0x0A):
            out.append(ch)
        elif unicodedata.category(ch) in ("Cc", "Cf"):
            out.append(f"\\u{cp:04x}")
        else:
            out.append(ch)
    return "".join(out)


def path_display(path: str) -> str:
    """Display form of a repo-controlled path in rendered comments: control/
    bidi escaped via the injective _escape_path, credential-shaped runs
    redacted. F9-A09: characters are NEVER deleted or aliased — '_' kept,
    F11-A5 keeps a literal backtick (run-widened fences at the span sites).
    F13-A12: the encoding is injective so lifecycle identity never collapses
    distinct paths, while the output stays single-line and control-free."""
    out = _escape_path(path)
    return scrub.redact_credentials(out)


def path_key(path: str) -> str:
    """F14-A04/A05 (reopened F13-A12/F12-A6): the LIFECYCLE identity form
    stored in finding lines. It is the escape-encoded path — and when
    display redaction would alias two distinct paths ('a/AKIA...py' vs
    'a/[redacted].py' both render '[redacted]'), the whole path is
    hex-encoded instead, keeping the encoding injective. Body round-trips
    return this exact string; comparisons never re-encode it."""
    out = _escape_path(path)
    if scrub.redact_credentials(out) != out:
        return "".join(f"\\u{ord(c):04x}" for c in path)
    return out


def _code_span(text: str) -> str:
    """CommonMark-safe code span: delimiter run = 1 + the longest backtick
    run inside the content — a single-backtick span cannot carry a literal
    backtick, and run-widening keeps the identity byte-exact (F11-A5)."""
    runs = 0
    cur = 0
    for ch in text:
        if ch == "`":
            cur += 1
            runs = max(runs, cur)
        else:
            cur = 0
    delim = "`" * (runs + 1)
    return f"{delim}{text}{delim}"


def path_plain(path: str) -> str:
    """Backslash-escaped display form for PLAIN markdown prose (bullets,
    bodies): a raw backtick there would open a code span and swallow the
    line; identity is irrelevant outside the finding-line contract."""
    return path_display(path).replace("`", "\\`")


def render_finding(f: Finding, tone: str, post_merge: bool = False) -> str:
    """One finding as a section with emoji badge + collapsible fix proposal."""
    emoji = _SEVERITY_EMOJI.get(f.severity, "⚪")
    urgency = (_URGENCY_POST_MERGE if post_merge else _URGENCY).get(f.severity, "")
    # MECE rounds 1-2: paths are repo-controlled untrusted text — display form
    # strips structure chars and redacts credential-shaped runs
    safe_rule = str(f.rule_id).replace("`", "")
    # F11-A5: the path:line span uses a backtick-RUN fence when the path
    # itself carries a backtick, so identity survives byte-exact.
    # F14-A04/A05: the span stores the injective path_key form.
    span = _code_span(f"{path_key(f.path)}:{f.line}")
    parts: list[str] = [
        FINDING_LINE_FMT.format(emoji=emoji, sev=f.severity, span=span,
                                rule=safe_rule),
        "",
    ]
    parts.append(_md_escape_block(scrub.scrub(scrub.redact_credentials(f.message))))  # F9-A10: full scrub belt
    if f.proposal:
        parts += [
            "",
            "<details>",
            "<summary>💡 How to fix</summary>",
            "",
            "````",
            _md_escape_block(scrub.redact_credentials(f.proposal)),
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
    # MECE round-2 (luna F2-004): identity comparisons use the DISPLAY path on
    # both sides — previous findings parsed back from a comment already carry
    # display forms; raw current paths are normalized to match
    # F14-A04: previous findings already carry the identity form in their
    # parsed path — never re-encode them (double-escaping made unchanged
    # findings flip to 🆕 and prior ones resolve)
    previous_keys = {(f.path, f.line, f.rule_id) for f in (previous_findings or [])}
    current_keys = {(path_key(f.path), f.line, f.rule_id) for f in findings}
    resolved = [f for f in (previous_findings or [])
                if (f.path, f.line, f.rule_id) not in current_keys]

    head = "## 🔍 FL4WRITE review (post-merge)\n\n" if post_merge else "## 🔍 FL4WRITE review\n\n"

    # F13-A10: truncation is an independent state — a truncated review with
    # ZERO findings used to render the clean 'Go merge it' celebration
    if diff_truncated:
        head += "⚠️ **PARTIAL REVIEW — the diff was truncated; the file set "
        head += "below the limit is NOT a clean bill**\n\n"

    if findings or resolved:
        head += _severity_table(findings) + "\n\n"
        head += f"`{pr.repo}#{pr.number}` @ `{pr.head_sha[:8]}` · {len(findings)} findings"
        if gatekeeper_dropped:
            head += f" · 🧹 {gatekeeper_dropped} nits filtered"
        head += "\n\n"
        sections = []
        if findings:
            sections.append(
                _TONES[tone]
                + "\n---\n\n".join(
                    ("🆕 " if (path_key(f.path), f.line, f.rule_id) not in previous_keys else "")
                    + render_finding(f, tone, post_merge)
                    for f in findings
                )
            )
        if resolved:
            lines = "\n".join(
                f"- ✅ {_code_span('~' + path_key(f.path) + ':' + str(f.line))} "
                f"({f.rule_id})" for f in resolved)
            sections.append(f"### ✅ Resolved since last review\n\n{lines}")
        body = "\n\n---\n\n".join(sections)
    elif post_merge and not diff_truncated:
        body = _TONES[tone] + "## ✨ Clean review — nothing to fix.\n\nMerged in good shape. ✅"
    elif not diff_truncated:
        body = _TONES[tone] + "## ✨ Clean review — nothing to fix.\n\nGo merge it. 🎉"
    else:
        # F13-A10: zero-finding TRUNCATED review — no merge encouragement,
        # the banner above already carries the disclosure
        body = _TONES[tone] + "Review incomplete (diff truncated) — no merge signal.\n"

    footer = (
        f"\n\n---\n"
        f"*Reviewed by **FL4WRITE** · tone: {tone} · "
        f"[org law](https://github.com/KyaniteLabs/fl4write/blob/main/fl4write/law.py)*\n"
        f"<!-- {MARKER.format(review_hash=review_hash)} -->\n"
    )
    out = head + body + footer


    # F9-A10: validate the CORE body — the bot's own trailing HTML comment
    # marker is legitimate; everything else must be clean
    _core = re.sub(r"\n?<!--.*?-->\s*$", "", out)
    scrub.assert_clean(_core)
    return out


def _count_severities(findings: list[Finding]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for f in findings:
        counts[f.severity] = counts.get(f.severity, 0) + 1
    return counts