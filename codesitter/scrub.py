"""Untrusted-text scrubbing — the lethal-trifecta first defense.

EVERYTHING crossing the trust boundary (PR bodies, commit messages, finding
text, review comments, file names) is scrubbed before it enters model prompts
or is echoed into output. Defense classes, from the Lane E research:

- control/invisible characters (RLM/LRM/ZWSP, bidi overrides, ANSI escapes)
- markdown/link exfiltration vectors (data: URLs, base64 img/src in any form)
- hidden HTML (details/summary collapses hiding instructions), HTML comments
- our own marker protocol (codesitter-sitter must never be spoofable)

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
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_HIDDEN_TAG_RE = re.compile(r"</?\s*(details|summary|script|style|iframe)\b[^>]*>", re.IGNORECASE)
# Our persistent-comment marker must be minted only by the renderer.
_MARKER_RE = re.compile(r"codesitter:v\d+:[0-9a-fA-F]+")


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
    s = _REMOTE_SRC_RE.sub("&lt;remote-src ", s)
    s = _HTML_COMMENT_RE.sub("", s)
    s = _HIDDEN_TAG_RE.sub("", s)
    s = _MARKER_RE.sub("[scrubbed-marker]", s)
    return s


def assert_clean(text: str) -> None:
    """Fail loudly if scrub() output still contains a defense category."""
    for ch in text:
        cp = ord(ch)
        if cp in _WHITELIST_CODEPOINTS:
            continue
        if unicodedata.category(ch) in _CONTROL_CATEGORIES:
            raise ValueError(f"unscrubbed control char U+{cp:04X} in output")
    for pattern in (_DATA_URL_RE, _BASE64_IMG_RE, _REMOTE_SRC_RE, _MARKER_RE):
        if pattern.search(text):
            raise ValueError(f"unscrubbed pattern {pattern.pattern[:30]} in output")
