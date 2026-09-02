"""Per-repo config schema (.fl4write.yaml) — repo law as data.

The AGENTS.md pattern made machine-readable: review constraints, severity
mapping, fix-lane autonomy, model routing, per-forge bindings. Adding a repo
means adding one file (in-repo) plus forge bindings here or in org defaults.

Fail-loud doctrine (audit 2026-09-01): every model forbids unknown keys —
a typo like `shdow: true` must ABORT, not silently drop the safety flag.
YAML duplicate keys abort too (merge-conflict/regenerator corruption class).
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

log = logging.getLogger("fl4write.config")

_SEVERITY_ORDER = ["Critical", "Major", "Minor", "Nit"]
_TONE_PATTERN = "^(quiet|balanced|assertive|roast)$"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ForgeBinding(_StrictModel):
    """One forge's view of a repo. Exactly one forge must be `primary`;
    others are `mirror` (polled for completeness, deduped by head SHA —
    mirrored PRs are never reviewed twice)."""

    role: str = Field(pattern="^(primary|mirror)$")
    api_base: str = Field(pattern=r"^https?://")  # http allowed: self-hosted forges
    token_env: str  # REQUIRED: no default — a binding must name its env var
    # (a default silently sent the GitHub token to the Forgejo host)


class ModelRoute(_StrictModel):
    endpoint: str = Field(pattern=r"^https?://")  # http allowed: BYO-LLM localhost routers
    model: str
    key_env: str = ""  # empty = no auth header
    temperature: float = 0.2
    max_tokens: int = 4000
    seed: int | None = None  # reproducibility for regression triage


class FixLaneConfig(_StrictModel):
    enabled: bool = False
    merge_own_prs: bool = True  # asserted in code at the merge call site too
    max_fix_depth: int = 2  # re-review x fix loop cap; escalate on exceed
    fork_policy: str = Field(default="comment-only", pattern="^comment-only$")
    dependency_policy: str = Field(
        default="skip-patch",
        pattern="^(skip-patch|skip-all|shallow-minor)$",
    )


class PostMergeConfig(_StrictModel):
    """Post-merge review mode (LEARNINGS #24): this org's PRs open and merge
    in ~60s, so an open-PR poller structurally never sees them. When enabled,
    each cycle additionally reviews PRs merged since the per-repo watermark;
    findings land as post-merge comments, fixes ride follow-up PRs."""

    enabled: bool = False  # opt-in per repo (central config only; in-repo
    # configs are adoption artifacts, the runner reads central configs)
    initial_lookback_h: int = Field(default=24, ge=1, le=168)  # bounded first-cycle catch-up
    max_per_cycle: int = Field(default=10, ge=1, le=50)  # model-spend + cycle-time bound


class CIWatchConfig(_StrictModel):
    """CI-failure trigger (CEO directive 2026-09-01): a CI failure on an OWN
    repo summons review + fix. Red default-branch HEAD (SHA-keyed — no
    timestamp watermark) yields findings from the failing checks' annotations
    (deterministic signal, no model in the finding itself); the fix lane
    attempts the patch; no-fix escalates to an issue. Forks/upstream
    submissions are structurally out: the fleet is originally-ours-only and
    the fix lane's fork rail stays hard."""

    enabled: bool = False
    escalate_issues: bool = True  # open an issue when no fix lands for a red head
    max_checks: int = Field(default=5, ge=1, le=20)  # failing checks considered per head
    max_annotations: int = Field(default=10, ge=1, le=50)  # findings per check


class RetroAuditConfig(_StrictModel):
    """Retro audit (CEO ask 2026-09-01: "catch any OLD mistakes"): walk merged
    PRs OLDER than the forward post-merge watermark, newest-first, capped and
    cursor-resumable across cycles. Freshness gate drops findings whose path
    no longer exists on HEAD (zombie findings on fixed/moved code post
    nothing). Direct-push commits with no PR are v2 — not covered here."""

    enabled: bool = False
    lookback_days: int = Field(default=90, ge=1, le=730)
    max_per_cycle: int = Field(default=5, ge=1, le=25)  # model-spend bound; drains over days
    freshness_gate: bool = True  # skip findings whose path is gone from HEAD


class OmniSweepConfig(_StrictModel):
    """Omnisweep (CEO charter 2026-09-01: "go to town — find and fix
    everything / scan the whole thing prelaunch"): full-tree scan at HEAD,
    findings land in ONE audit issue per repo (edited in place), an optional
    conservative fix phase drives the existing fix lane via stable-id
    synthetic PRs. Fix phase is SEPARATELY gated: cold-code findings lack the
    reviewed-diff premise the fix lane was built on, and merge_own_prs
    defaults True — so omni fixes are opt-in and Critical-only by default."""

    enabled: bool = False
    fix: bool = False  # separate gate; scan-only is the safe default
    fix_min_severity: str = Field(default="Critical", pattern="^(Critical|Major)$")
    max_files_per_cycle: int = Field(default=10, ge=1, le=50)
    max_total_files: int = Field(default=2000, ge=10, le=20000)  # sweep-wide abort bound
    max_findings_in_issue: int = Field(default=20, ge=5, le=100)  # body cap; rest in state
    exclude: list[str] = Field(default_factory=lambda: [
        "node_modules/*", "vendor/*", "dist/*", "build/*", ".git/*",
        "*.lock", "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
        "*.png", "*.jpg", "*.jpeg", "*.gif", "*.ico", "*.webp", "*.svg",
        "*.woff", "*.woff2", "*.ttf", "*.eot", "*.pdf", "*.zip", "*.gz",
        "*.mp4", "*.mp3", "*.wav", "*.wasm", "*.bin",
    ])


class RepoConfig(_StrictModel):
    """The full per-repo config. Validated fail-loud at startup."""

    repo: str = Field(pattern=r"^[^/\s]+/[^/\s]+$")  # owner/name
    forges: dict[str, ForgeBinding]
    model: ModelRoute
    fallback_model: ModelRoute | None = None
    review: dict[str, str] = Field(default_factory=dict)  # rule-id -> prose law
    # Renderer/engine are vocab-hardcoded until they are vocab-driven; a
    # custom vocab that renders wrong is worse than refusing it.
    severity_vocab: list[str] = Field(default_factory=lambda: list(_SEVERITY_ORDER))
    tone: str = Field(default="balanced", pattern=_TONE_PATTERN)
    tone_fork_override: str = Field(default="balanced", pattern=_TONE_PATTERN)
    path_filters: dict[str, list[str]] = Field(default_factory=dict)  # minimatch-lite
    fix: FixLaneConfig = Field(default_factory=FixLaneConfig)
    post_merge: PostMergeConfig = Field(default_factory=PostMergeConfig)
    ci_watch: CIWatchConfig = Field(default_factory=CIWatchConfig)
    retro_audit: RetroAuditConfig = Field(default_factory=RetroAuditConfig)
    omnisweep: OmniSweepConfig = Field(default_factory=OmniSweepConfig)
    known_env_failures: list[str] = Field(default_factory=list)  # test ids to ignore
    verify_tests: bool = True  # run the diff's own tests sandboxed; a failing
    # diff is a deterministic Critical (prompt-only tracing missed planted bugs)
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

    @field_validator("severity_vocab")
    @classmethod
    def _vocab_supported(cls, v: list[str]) -> list[str]:
        if v != _SEVERITY_ORDER:
            raise ValueError(f"severity_vocab must be {_SEVERITY_ORDER} (renderer is vocab-hardcoded)")
        return v

    @field_validator("fallback_model")
    @classmethod
    def _fallback_differs(cls, v: ModelRoute | None, info) -> ModelRoute | None:
        primary = info.data.get("model")
        if v is not None and primary is not None and (v.endpoint, v.model) == (primary.endpoint, primary.model):
            log.warning(
                "fallback_model is identical to model (%s @ %s) — the fallback "
                "lane provides no resilience against that provider's outage",
                v.model, v.endpoint,
            )
        return v


class _UniqueKeyLoader(yaml.SafeLoader):
    """PyYAML silently keeps the LAST duplicate mapping key; a merge-conflicted
    or regenerated config must abort instead (corruption class, LEARNINGS #16)."""


def _no_dupes(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ValueError(f"duplicate YAML key: {key!r}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_dupes
)


def check_model_keys(config: RepoConfig) -> None:
    """Warn (not abort) when a route's key_env is unset in this environment —
    the failure would otherwise surface as an opaque per-cycle 401."""
    import os

    for name, route in (("model", config.model), ("fallback_model", config.fallback_model)):
        if route is not None and route.key_env and not os.environ.get(route.key_env):
            log.warning("%s.key_env %s is not set in the environment (expect 401s)", name, route.key_env)


def load_config(path: str | Path) -> RepoConfig:
    """Fail-loud loader: config errors abort the cycle, never silently skip."""
    raw = yaml.load(Path(path).read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
    config = RepoConfig.model_validate(raw)
    check_model_keys(config)
    return config
