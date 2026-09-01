"""Issues lane — triage for GitHub + Forgejo issues (not PRs).

Collects new issues, runs LLM triage (duplicate detection, label routing,
answer drafting from repo law), posts a single triage comment. Comment-only:
never closes, never reassigns, never edits labels via API (the comment
SUGGESTS labels; a human applies them).

Config surface: `issues_enabled: true` in the repo config AND the runner passes
`--issues`; either missing disables the lane.
State: tracks `last_triaged_number` per repo (issues are numbered; we
triage everything with a number > last_triaged).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from . import scrub
from .analyzer import ModelUnavailable, _call_model
from .config import RepoConfig
from .forges import ForgeAdapter, ForgeError, is_own_identity


log = logging.getLogger("fl4write.issues")

_TRIAGE_SYSTEM = (
    "You are an issue triager. You receive an issue (title + body) and the "
    'repo\'s context. Reply ONLY with JSON: {"labels": [str], "is_duplicate": bool, '
    '"duplicate_hint": str|null, "draft_reply": str, "urgency": "low|medium|high|critical", '
    '"is_regression": bool, "regression_version": str|null}. '
    "The draft_reply should be helpful, grounded in the repo's law/docs, and "
    "under 100 words. Never claim a fix exists unless the law mentions it."
)

_URGENCY_MARKER = {"critical": "🚨", "high": "⚠️", "medium": "", "low": ""}


def collect_new_issues(forge: ForgeAdapter, repo: str, last_number: int) -> list[dict[str, Any]]:
    """Fetch open issues with number > last_number, PAGINATED and ascending.

    Single-page-30 was a silent permanent-skip: GitHub sorts newest-first,
    so with >30 untriaged issues the watermark jumped past unseen older ones.
    We page through everything, then process in ascending order so the
    watermark only ever advances over issues actually handled."""
    all_issues: list[dict[str, Any]] = []
    try:
        all_issues = list(forge._paginated(f"/repos/{repo}/issues?state=open", page_size=50))
    except ForgeError:
        all_issues = forge._call("GET", f"/repos/{repo}/issues?state=open&per_page=100")
        all_issues = all_issues if isinstance(all_issues, list) else []
    fresh = [i for i in all_issues if i.get("number", 0) > last_number and "pull_request" not in i]
    return sorted(fresh, key=lambda i: i.get("number", 0))


def triage_issue(issue: dict[str, Any], config: RepoConfig) -> dict[str, Any] | None:
    """Run LLM triage on one issue. Returns the triage result or None on failure."""
    title = scrub.scrub(issue.get("title", ""))
    body = scrub.scrub((issue.get("body") or "")[:4000])

    prompt = (
        f"REPO LAW:\n{json.dumps(config.review, indent=1)}\nISSUE TITLE: {title}\nISSUE BODY:\n{body}\nJSON triage:"
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
    labels = ", ".join(f"`{lbl}`" for lbl in triage.get("labels", [])) or "none suggested"

    parts = [
        f"## FL4WRITE triage — issue #{issue_num}",
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

    parts.append("\n---\n<!-- fl4write-triage:v1 -->")
    result = "\n".join(parts)
    scrub.assert_clean(result.replace("<!-- fl4write-triage:v1 -->", ""))
    return result


def find_existing_triage(forge: ForgeAdapter, repo: str, number: int, bot_login: str) -> tuple[int, str] | None:
    """Find our existing triage comment on this issue."""
    for c in forge._paginated(f"/repos/{repo}/issues/{number}/comments", page_size=50):
        body = c.get("body") or ""
        author = ((c.get("user") or {}).get("login") or "").lower()
        if (
            "fl4write-triage:v1" in body or "codesitter-triage:v1" in body
        ) and is_own_identity(author, bot_login):
            return c["id"], body
    return None


def _foreign_triage_exists(forge: ForgeAdapter, repo: str, number: int) -> bool:
    """True if ANY comment carries the triage marker, whatever the author.

    Defense-in-depth against duplicate posts across identity/host confusion:
    a marker-bearing comment we cannot claim still means this issue was
    triaged — skip rather than spam a second copy.
    """
    for c in forge._paginated(f"/repos/{repo}/issues/{number}/comments", page_size=50):
        body = c.get("body") or ""
        if "fl4write-triage:v1" in body or "codesitter-triage:v1" in body:
            return True
    return False


def run_issues_cycle(config: RepoConfig, st: dict[str, Any], forge: ForgeAdapter) -> dict[str, int]:
    """One issues-triage cycle for one repo. Returns a summary dict.

    Mutates the ENGINE-OWNED state dict (single owner per cycle: the engine
    loads once and saves once — a lane doing its own load+save here caused a
    lost update that wiped last_triaged_number every cycle, re-triaging all
    open issues and email-storming maintainers).
    """
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
            # SHADOW NEVER ADVANCES THE WATERMARK (LEARNINGS #2 class): a
            # shadow-triaged issue must still get its live triage later.
            continue
        else:
            body = render_triage_comment(num, triage, config)
            existing = find_existing_triage(forge, config.repo, num, config.bot_login)
            if existing:
                forge.update_comment(config.repo, num, existing[0], body)
            elif _foreign_triage_exists(forge, config.repo, num):
                # Marker present but not ours (identity change, cross-host run):
                # NEVER post a second copy — that is the email-storm failure.
                log.warning(
                    "issue #%s: marker comment exists under another identity; skipping (no duplicate)",
                    num,
                )
                summary["skipped"] += 1
                st["last_triaged_number"] = max(st.get("last_triaged_number", 0), num)
                continue
            else:
                forge.create_comment(config.repo, num, body)
            summary["triaged"] += 1

        st["last_triaged_number"] = max(st.get("last_triaged_number", 0), num)

    return summary
