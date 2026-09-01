"""Per-repo config schema (.fl4write.yaml) — repo law as data.

The AGENTS.md pattern made machine-readable: review constraints, severity
mapping, fix-lane autonomy, model routing, per-forge bindings. Adding a repo
means adding one file (in-repo) plus forge bindings here or in org defaults.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator


class ForgeBinding(BaseModel):
    """One forge's view of a repo. Exactly one forge must be `primary`;
    others are `mirror` (polled for completeness, deduped by head SHA —
    mirrored PRs are never reviewed twice)."""

    role: str = Field(pattern="^(primary|mirror)$")
    api_base: str
    token_env: str = "CODESITTER_GITHUB_TOKEN"


class ModelRoute(BaseModel):
    endpoint: str
    model: str
    key_env: str = ""  # empty = no auth header
    temperature: float = 0.2
    max_tokens: int = 4000


class FixLaneConfig(BaseModel):
    enabled: bool = False
    merge_own_prs: bool = True  # asserted in code at the merge call site too
    max_fix_depth: int = 2  # re-review x fix loop cap; escalate on exceed
    fork_policy: str = Field(default="comment-only", pattern="^comment-only$")
    dependency_policy: str = Field(
        default="skip-patch",
        pattern="^(skip-patch|skip-all|shallow-minor)$",
    )


class RepoConfig(BaseModel):
    """The full per-repo config. Validated fail-loud at startup (Lane A)."""

    repo: str  # owner/name on the primary forge
    forges: dict[str, ForgeBinding]
    model: ModelRoute
    fallback_model: ModelRoute | None = None
    review: dict[str, str] = Field(default_factory=dict)  # rule-id -> prose law
    severity_vocab: list[str] = Field(default_factory=lambda: ["Critical", "Major", "Minor", "Nit"])
    tone: str = Field(default="balanced", pattern="^(quiet|balanced|assertive|roast)$")
    tone_fork_override: str = Field(default="balanced")  # hard override, forks
    path_filters: dict[str, list[str]] = Field(default_factory=dict)  # minimatch-lite
    fix: FixLaneConfig = Field(default_factory=FixLaneConfig)
    known_env_failures: list[str] = Field(default_factory=list)  # test ids to ignore
    shadow: bool = False  # True = log findings, post nothing
    gatekeeper: bool = True  # nit-filter second pass (fail-open)
    issues_enabled: bool = False  # issues-lane triage (comment-only)
    bot_login: str = "fl4write[bot]"  # the account comments post AS; the
    # hijack-defense author check must match this or we reject our own
    # persistent comment and double-post (inaugural finding)

    @field_validator("forges")
    @classmethod
    def _exactly_one_primary(cls, v: dict[str, ForgeBinding]) -> dict[str, ForgeBinding]:
        primaries = [k for k, b in v.items() if b.role == "primary"]
        if len(primaries) != 1:
            raise ValueError(f"exactly one forge must be 'primary', got {primaries}")
        return v

    @field_validator("review")
    @classmethod
    def _rules_exist(cls, v: dict[str, str]) -> dict[str, str]:
        for rule_id in v:
            if not rule_id or rule_id.strip() != rule_id:
                raise ValueError(f"invalid rule id: {rule_id!r}")
        return v


def load_config(path: str | Path) -> RepoConfig:
    """Fail-loud loader: config errors abort the cycle, never silently skip."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return RepoConfig.model_validate(raw)
