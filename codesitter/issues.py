"""Issues lane — triage for GitHub + Forgejo issues (not PRs).

Collects new issues, runs LLM triage (duplicate detection, label routing,
answer drafting from repo law), posts a single triage comment. Comment-only:
never closes, never reassigns, never edits labels via API (the comment
SUGGESTS labels; a human applies them).

Config surface: `issues: enabled` in the repo config. When absent, disabled.
State: tracks `last_triaged_number` per repo (issues are numbered; we
triage everything with a number > last_triaged).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from . import scrub
from .analyzer import ModelUnavailable, _call_model
from .config import RepoConfig
from .forges import ForgeAdapter, ForgeError
from .state import load_state, save_state

log = logging.getLogger("codesitter.issues")

_TRIAGE_SYSTEM = (
    "You are an issue triager. You receive an issue (title + body) and the "
    "repo's context. Reply ONLY with JSON: {\"labels\": [str], \"is_duplicate\": bool, "
    "\"duplicate_hint\": str|null, \"draft_reply\": str, \"urgency\": \"low|medium|high|critical\", "
    "\"is_regression\": bool, \"regression_version\": str|null}. "
    "The draft_reply should be helpful, grounded in the repo's law/docs, and "
    "under 100 words. Never claim a fix exists unless the law mentions it."
)

_URGENCY_MARKER = {"critical": "🚨", "high": "⚠️", "medium": "", "low": ""}


def collect_new_issues(forge: ForgeAdapter, repo: str, last_number: int) -> list[dict[str, Any]]:
    """Fetch open issues with number > last_number."""
    issues = forge._call("GET", f"/repos/{repo}/issues?state=open&type=issue&per_page=30")
    if not isinstance(issues, list):
        return []
    return [i for i in issues if i.get("number", 0) > last_number and "pull_request" not in i]


def triage_issue(issue: dict[str, Any], config: RepoConfig) -> dict[str, Any] | None:
    """Run LLM triage on one issue. Returns the triage result or None on failure."""
    title = scrub.scrub(issue.get("title", ""))
    body = scrub.scrub((issue.get("body") or "")[:4000])

    prompt = (
        f"REPO LAW:\n{json.dumps(config.review, indent=1)}\n"
        f"ISSUE TITLE: {title}\nISSUE BODY:\n{body}\nJSON triage:"
    )
    try:
        response = _call_model(config.model, prompt)
        parsed = json.loads(response[response.index("{") : response.rindex("}") + 1])
        return parsed
    except (ModelUnavailable, ValueError, json.JSONDecodeError) as exc:
        log.warning("issue triage failed for #%s: %s", issue.get("number"), exc)
        return None


def render_triage_comment(issue_num: int, triage: dict[str, Any], config: RepoConfig) -> str:
    """Render the triage comment body."""
    urgency = triage.get("urgency", "low")
    marker = _URGENCY_MARKER.get(urgency, "")
    labels = ", ".join(f"`{l}`" for l in triage.get("labels", [])) or "none suggested"

    parts = [
        f"## codesitter triage — issue #{issue_num}",
        "",
        f"**Urgency:** {marker} {urgency}" if marker else f"**Urgency:** {urgency}",
        f"**Suggested labels:** {labels}",
    ]

    if triage.get("is_duplicate"):
        parts.append(f"**Possible duplicate:** {triage.get('duplicate_hint', 'check similar issues')}")
    if triage.get("is_regression"):
        parts.append(f"**⚠️ Regression suspected** in: {triage.get('regression_version', 'unknown version')}")

    draft = scrub.scrub(triage.get("draft_reply", ""))
    if draft:
        parts.append(f"\n> {draft}")

    parts.append("\n---
<!-- codesitter-triage:v1 -->")
    result = "\n".join(parts)
    scrub.assert_clean(result.replace("<!-- codesitter-triage:v1 -->", ""))
    return result


def find_existing_triage(forge: ForgeAdapter, repo: str, number: int, bot_login: str) -> tuple[int, str] | None:
    """Find our existing triage comment on this issue."""
    for c in forge._paginated(f"/repos/{repo}/issues/{number}/comments", page_size=50):
        body = c.get("body") or ""
        author = ((c.get("user") or {}).get("login") or "").lower()
        if "codesitter-triage:v1" in body and author == bot_login:
            return c["id"], body
    return None


def run_issues_cycle(config: RepoConfig, state_path, forge: ForgeAdapter) -> dict[str, int]:
    """One issues-triage cycle for one repo. Returns a summary dict."""
    st = load_state(state_path)
    last_num = st.get("last_triaged_number", 0)
    summary = {"triaged": 0, "skipped": 0, "errors": 0}

    try:
        new_issues = collect_new_issues(forge, config.repo, last_num)
    except ForgeError as exc:
        log.warning("issues collect failed for %s: %s", config.repo, exc)
        return summary

    for issue in new_issues:
        num = issue.get("number", 0)
        triage = triage_issue(issue, config)
        if triage is None:
            summary["errors"] += 1
            continue

        if config.shadow:
            summary["triaged"] += 1
        else:
            body = render_triage_comment(num, triage, config)
            existing = find_existing_triage(forge, config.repo, num, config.bot_login)
            if existing:
                forge.update_comment(config.repo, num, existing[0], body)
            else:
                forge.create_comment(config.repo, num, body)
            summary["triaged"] += 1

        st["last_triaged_number"] = max(st.get("last_triaged_number", 0), num)

    save_state(state_path, st)
    return summary
