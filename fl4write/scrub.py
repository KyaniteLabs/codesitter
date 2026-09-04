"""Untrusted-text scrubbing — the lethal-trifecta first defense.

EVERYTHING crossing the trust boundary (PR bodies, commit messages, finding
text, review comments, file names) is scrubbed before it enters model prompts
or is echoed into output. Defense classes, from the Lane E research:

- control/invisible characters (RLM/LRM/ZWSP, bidi overrides, ANSI escapes)
- markdown/link exfiltration vectors (data: URLs, base64 img/src in any form)
- hidden HTML (details/summary collapses hiding instructions), HTML comments
- our own marker protocol (fl4write-sitter must never be spoofable)

This is deliberately allow-list-flavored: strip by category, then assert the
result contains none of the categories. Injection payloads become inert text
the model sees as data.
"""

from __future__ import annotations

import re
import unicodedata

_CONTROL_CATEGORIES = {"Cc", "Cf"}
# Keep \n and \t — they're structural, not hostile.
_WHITELIST_CODEPOINTS = {0x09, 0x0A}

_DATA_URL_RE = re.compile(r"data:[^\s\"')]+", re.IGNORECASE)
_BASE64_IMG_RE = re.compile(r"!\[[^\]]*\]\([^)]*base64[^)]*\)", re.IGNORECASE)
_REMOTE_SRC_RE = re.compile(r"<\s*(img|source|script|iframe)[^>]*src\s*=", re.IGNORECASE)
_REMOTE_IMG_RE = re.compile(r"!\[[^\]]*\]\(\s*https?://[^)]*\)", re.IGNORECASE)  # exfil beacon
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_HIDDEN_TAG_RE = re.compile(
    r"</?\s*(details|summary|script|style|iframe|h[1-6]|table|thead|tbody|tr|th|td|"
    r"div|section|article|blockquote|pre|hr)\b[^>]*>", re.IGNORECASE)
# Our persistent-comment marker must be minted only by the renderer.
_MARKER_RE = re.compile(r"(?:fl4write|codesitter):v\d+:[0-9a-fA-F]+")


def scrub(text: str) -> str:
    """Category-strip untrusted text. Idempotent. Never raises."""
    if not isinstance(text, str):
        return ""
    out = []
    for ch in text:
        cp = ord(ch)
        if cp in _WHITELIST_CODEPOINTS:
            out.append(ch)
            continue
        if unicodedata.category(ch) in _CONTROL_CATEGORIES:
            continue  # drop bidi overrides, zero-widths, ANSI, etc.
        out.append(ch)
    s = "".join(out)
    s = _DATA_URL_RE.sub("[scrubbed-data-url]", s)
    s = _BASE64_IMG_RE.sub("[scrubbed-image]", s)
    s = _REMOTE_IMG_RE.sub("[image removed]", s)
    s = _REMOTE_SRC_RE.sub("&lt;remote-src ", s)
    s = _HTML_COMMENT_RE.sub("", s)
    if "<!--" in s:
        # MECE round-1 (terra F1-07): an UNCLOSED comment opener can swallow
        # the remainder of the rendered comment — remove any leftover opener
        s = s.split("<!--", 1)[0] + s.split("<!--", 1)[1].replace("<!--", "")
    s = _HIDDEN_TAG_RE.sub("", s)
    s = _MARKER_RE.sub("[scrubbed-marker]", s)
    return s


# High-entropy or prefixed runs that look like credentials (MECE round-1,
# terra F1-013): redacted at RENDER/posting time so a model-quoted literal is
# never duplicated onto a more public surface. Kept out of analyzer grounding
# (L1-B3 needs the literal before posting decisions).
_SECRET_PREFIX = ("ghp_", "gho_", "github_pat_", "sk-", "sk_", "AKIA",
                  "xoxb-", "xoxp-", "glpat-", "AIza")
_REDACT_RUN_RE = re.compile(r"[A-Za-z0-9_\-]{16,}")
# Long camelCase identifiers that look high-entropy but are code, not secrets
_KNOWN_IDENTIFIERS = {"documentQuerySelector", "getElementById", "getElementByClassName"}


def _entropy(s: str) -> float:
    import math
    if not s:
        return 0.0
    freq = {c: s.count(c) for c in set(s)}
    return -sum((n / len(s)) * math.log2(n / len(s)) for n in freq.values())


def redact_credentials(text: str) -> str:
    """Replace credential-shaped strings with [redacted]. Prefix runs always;
    16+ char runs only when high-entropy (a real secret, not an identifier).
    Apply at posting surfaces, never on analyzer grounding paths."""
    if not isinstance(text, str) or not text:
        return text
    out = text
    for m in _REDACT_RUN_RE.finditer(text):
        tok = m.group(0)
        if tok not in _KNOWN_IDENTIFIERS and (any(
                tok.startswith(p) for p in _SECRET_PREFIX) or _entropy(tok) >= 3.5):
            out = out.replace(tok, "[redacted]", 1)
    # prefix-marked tokens not caught by the 16+ run rule (shorter prefixes)
    import re as _re
    for p in _SECRET_PREFIX:
        out = _re.sub(re.escape(p) + r"[A-Za-z0-9_\-]{8,}", "[redacted]", out)
    return out


def inline(text: str, limit: int | None = None) -> str:
    """Scrub + collapse to ONE line for list/title renderings (issue bodies,
    escalation bullets, PR titles): finding text with newlines must never
    break a bullet list or mint fake entries (UltraQA round 1, ADV-04/P3 —
    scrub keeps \n structural, which is right for prose but wrong here)."""
    s = redact_credentials(scrub(text))
    s = " ".join(s.split()) if s else ""
    return s[:limit] if limit else s


def assert_clean(text: str) -> None:
    """Fail loudly if scrub() output still contains a defense category."""
    for ch in text:
        cp = ord(ch)
        if cp in _WHITELIST_CODEPOINTS:
            continue
        if unicodedata.category(ch) in _CONTROL_CATEGORIES:
            raise ValueError(f"unscrubbed control char U+{cp:04X} in output")
    for pattern in (_DATA_URL_RE, _BASE64_IMG_RE, _REMOTE_IMG_RE, _REMOTE_SRC_RE, _MARKER_RE):
        if pattern.search(text):
            raise ValueError(f"unscrubbed pattern {pattern.pattern[:30]} in output")
