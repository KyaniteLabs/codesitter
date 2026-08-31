"""Normalized entities — the engine speaks only these; forges are adapters."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PullRequest(BaseModel):
    forge: str
    number: int
    repo: str  # owner/name as the forge sees it
    title: str = ""
    body: str = ""
    head_sha: str
    is_fork: bool = False
    author: str = ""
    is_bot_author: bool = False
    state: str = "open"


class Finding(BaseModel):
    """A review finding. Severity/tone are renderer concerns; this is data."""

    rule_id: str  # must exist in config.review (grounding) or "general"
    severity: str  # must exist in config.severity_vocab (grounding)
    path: str
    line: int
    category: str = "General"
    message: str
    proposal: str = ""  # suggested fix, tone-invariant


class ReviewDoc(BaseModel):
    pr: PullRequest
    findings: list[Finding] = Field(default_factory=list)
    digest: dict[str, int] = Field(default_factory=dict)  # severity -> count
    incremental_range: tuple[str, str] | None = None  # (old_sha, new_sha)


def fingerprint(f: Finding, pr: PullRequest) -> str:
    """Dedup identity (Lane A/B/E convergence): stable across pushes when the
    finding is unchanged; any of rule/path/lines/message changing mints a new
    one. Used for find->update-else-create on the persistent comment."""
    import hashlib

    basis = f"{pr.repo}#{pr.number}|{f.rule_id}|{f.path}|{f.line}|{f.message}"
    return hashlib.sha256(basis.encode()).hexdigest()[:16]
