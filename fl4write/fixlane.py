"""Fix lane: verdict -> worktree -> PR -> CI-gated merge of OWN PRs only.

Rails (ralplan-approved + Lane B/C/E adopts), all asserted IN CODE at the
call sites, not only in config:

- Fork PRs: comment-only. Forever. A config edit cannot enable otherwise.
- Own-PR merge: the merge path re-verifies authorship + CI green at the
  call site (`merge_own_pr` raises otherwise).
- Fix-depth cap: at most config.fix.max_fix_depth rounds per finding per PR;
  on exceed, escalate to a human-action comment and stop.
- Dependency PRs (bot-authored): treated as read-only artifacts — skipped per
  config.fix.dependency_policy; never mutated.
- Loop prevention: a finding already attempted at this depth is not re-fixed.
"""

from __future__ import annotations

from . import scrub
from .config import RepoConfig
from .forges import is_own_identity
from .models import Finding, PullRequest


class FixLaneBlocked(RuntimeError):
    """Rail fired. The cycle records this and posts the escalation instead."""


def fix_allowed(pr: PullRequest, config: RepoConfig, depth_used: int) -> str | None:
    """Return None if a fix may proceed, else the blocking reason (posted as
    an escalation comment — never silently skipped)."""
    if pr.is_fork:
        # fork_policy knob is comment-only by schema AND by code rail — the
        # knob exists so the policy is VISIBLE in config; the rail is here.
        assert config.fix.fork_policy == "comment-only"
        return "fork PR — comment-only by code rail"
    if pr.is_bot_author:
        return "bot-authored (dependency) PR — read-only artifact by policy"
    if not config.fix.enabled:
        return "fix lane disabled for this repo"
    if depth_used >= config.fix.max_fix_depth:
        return f"fix depth cap reached ({config.fix.max_fix_depth}) — human action required; fl4write will not loop"
    return None


def dependency_depth(pr: PullRequest, title: str, config: RepoConfig) -> str:
    """Lane C policy: how deeply to review dependency PRs."""
    if not pr.is_bot_author:
        return "full"
    title_l = title.lower()
    if config.fix.dependency_policy == "skip-all":
        return "skip"
    if any(k in title_l for k in ("lockfile", "pin", "digest")):
        return "skip"
    if config.fix.dependency_policy == "skip-patch" and "patch" in title_l:
        return "skip"
    return "shallow"


def merge_own_pr(
    author: str,
    bot_identity: str,
    ci_green: bool,
    config: RepoConfig,
) -> None:
    """THE merge gate. Config cannot open this: authorship is re-verified here."""
    if not config.fix.merge_own_prs:
        raise FixLaneBlocked("merge_own_prs disabled")
    if not is_own_identity(author, bot_identity):  # current + legacy bot slugs
        raise FixLaneBlocked(f"refusing to merge PR authored by {author!r}, not {bot_identity!r}")
    if not ci_green:
        raise FixLaneBlocked("CI not green — merge refused")


def escalate(pr: PullRequest, findings: list[Finding], reason: str) -> str:
    """The human-escalation comment body for a blocked fix lane."""
    listing = "\n".join(f"- [{f.severity}] {f.path}:{f.line} — {scrub.inline(f.message, 100)}" for f in findings)
    return (
        f"## FL4WRITE fix lane — human action required\n\n"
        f"Blocked: {reason}\n\nOutstanding findings:\n{listing or '(none recorded)'}\n\n"
        "_This is an escalation, not a retry; the lane stops here by design._"
    )
