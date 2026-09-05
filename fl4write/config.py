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
import types as _types
import typing
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

log = logging.getLogger("fl4write.config")

_SEVERITY_ORDER = ["Critical", "Major", "Minor", "Nit"]
_TONE_PATTERN = "^(quiet|balanced|assertive|roast)$"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    @model_validator(mode="before")
    @classmethod
    def _strict_bools_and_numbers(cls, raw):
        """F14-D004 (reopened F7-D009/F13-D006): strictness lives IN the
        model, not only in load_config preprocessing — public
        RepoConfig.model_validate must refuse 'shadow: "false"' (used to
        coerce to live False), 'enabled: "yes"', and boolean numerics."""
        if not isinstance(raw, dict):
            return raw
        from typing import get_args, get_origin

        for _k, _v in raw.items():
            _f = cls.model_fields.get(_k)
            if _f is None:
                continue
            _ann = _f.annotation
            _has_bool = _ann is bool
            _has_num = False
            if get_origin(_ann) is not None:
                for _a in get_args(_ann):
                    if _a is bool:
                        _has_bool = True
                    if _a in (int, float):
                        _has_num = True
            elif _ann in (int, float):
                _has_num = True
            if _v is None:
                continue
            if _has_bool and not isinstance(_v, bool):
                raise ValueError(f"config field {_k!r} must be a boolean, got {_v!r}")
            if _has_num and isinstance(_v, bool):
                raise ValueError(f"config field {_k!r} must be a number, got boolean")
        return raw


def _int_field_names() -> set[str]:
    """Lazy: model classes below this point register at import time."""
    import fl4write.config as _self

    names: set[str] = set()
    for _v in vars(_self).values():
        if isinstance(_v, type) and issubclass(_v, BaseModel):
            for _n, _f in getattr(_v, "model_fields", {}).items():
                if _f.annotation in (int, float):
                    names.add(_n)
    return names


def _reject_bool_ints(raw):
    """F12-D006: pydantic coerces YAML booleans to integers ('true' -> 1) —
    a typo'd boolean must fail load-loud, never silently change a limit.
    Deep-walks the raw config and refuses bools for any field declared int."""
    if isinstance(raw, dict):
        for k, v in raw.items():
            if k in _int_field_names() and isinstance(v, bool):
                raise ValueError(f"config field {k!r} must be an integer, got boolean {v!r}")
            if isinstance(v, (dict, list)):
                _reject_bool_ints(v)
    elif isinstance(raw, list):
        for v in raw:
            _reject_bool_ints(v)
    return raw


class ForgeBinding(_StrictModel):
    """One forge's view of a repo. Exactly one forge must be `primary`;
    others are `mirror` (polled for completeness, deduped by head SHA —
    mirrored PRs are never reviewed twice)."""

    role: str = Field(pattern="^(primary|mirror)$")
    api_base: str = Field(pattern=r"^https?://")  # http allowed: self-hosted forges

    @field_validator("api_base")
    @classmethod
    def _api_base_queryable(cls, v: str) -> str:
        # F12-D008: 'https://' (no netloc) passed the prefix pattern and
        # leaked raw transport ValueError through the adapters at runtime
        parsed = __import__("urllib.parse").parse.urlsplit(v)
        if not parsed.hostname:
            raise ValueError(f"api_base must include a host, got {v!r}")
        # Accessing port validates both its numeric form and valid range.
        _ = parsed.port
        return v
    token_env: str = Field(min_length=1)
    # REQUIRED + NON-EMPTY: no default — a default or empty value silently
    # omits auth instead of failing (MECE round-1, sol F1-005); "" would make
    # unauthenticated calls look configured


class ModelRoute(_StrictModel):
    endpoint: str = Field(pattern=r"^https?://")  # http allowed: BYO-LLM localhost routers

    @field_validator("endpoint")
    @classmethod
    def _endpoint_queryable(cls, v: str) -> str:
        parsed = __import__("urllib.parse").parse.urlsplit(v)
        if not parsed.hostname:
            raise ValueError(f"endpoint must include a host, got {v!r}")
        _ = parsed.port
        return v
    model: str
    key_env: str = ""  # empty = no auth header
    # MECE round-5 (luna F5-003): NaN/Infinity temperature serializes as
    # invalid JSON and <=0 max_tokens is an unusable request — bound both
    # (pydantic ge/le comparisons reject NaN by construction)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_tokens: int = Field(default=4000, ge=1, le=1_048_576)
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

    repo: str = Field(pattern=r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")  # F12-D007: forge-safe owner/name (no URL delimiters)
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
    test_cmd: str | None = None  # per-repo test command; the pytest default
    # misfires on non-Python repos (DialectOS 09-03: Critical "no tests ran"
    # against a pnpm/vitest monorepo whose CI was green on the same tree)
    test_timeout: int = Field(default=240, ge=30, le=1800)  # monorepo
    # install+test chains need more than the 240s single-suite default
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

    @model_validator(mode="before")
    @classmethod
    def _no_env_namespace_collisions(cls, raw) -> object:
        # F12-D005 (CRITICAL): a forge binding's token_env must never equal a
        # model route's key_env — the app-installation token was mirrored into
        # the binding's env name, and a collision sent the FORGE credential as
        # the model endpoint's Bearer token
        _reject_bool_ints(raw)
        if not isinstance(raw, dict):
            return raw
        _model = raw.get("model") or {}
        _fallback = raw.get("fallback_model") or {}
        _key_envs = {(_model.get("key_env") or ""), (_fallback.get("key_env") or "")}
        _key_envs.discard("")
        # F14-D001 (CRITICAL, reopened F12-D005/F13-D001): the GitHub App
        # auth implicitly exports the forge credential as GH_TOKEN and
        # CODESITTER_GITHUB_TOKEN — a model key_env using either name would
        # receive the App token as the model endpoint's Bearer
        for _reserved in ("GH_TOKEN", "CODESITTER_GITHUB_TOKEN"):
            if _reserved in _key_envs:
                raise ValueError(
                    f"model key_env {_reserved!r} is reserved for forge app auth")
        _forges = raw.get("forges")
        if isinstance(_forges, dict):
            _seen_envs: dict[str, str] = {}
            for _name, _b in _forges.items():
                if isinstance(_b, dict):
                    _te = _b.get("token_env")
                    if isinstance(_te, str) and _te in _key_envs:
                        raise ValueError(
                            f"forge {_name!r} token_env {_te!r} collides with a model "
                            "key_env — credentials would cross authentication "
                            "namespaces")
                    # F13-D001 (CRITICAL, reopened F12-D005): two forges on
                    # DIFFERENT hosts sharing one token_env made the CLI mirror
                    # the GitHub App token into the Forgejo binding's env name
                    # — the GH credential would ride as Forgejo's Authorization
                    if _te in _seen_envs:
                        raise ValueError(
                            f"forge {_name!r} token_env {_te!r} duplicates forge "
                            f"{_seen_envs[_te]!r} — one env name must not carry "
                            "credentials across differently routed hosts")
                    _seen_envs[_te] = _name
        return raw

    @field_validator("review")
    @classmethod
    def _rules_exist(cls, v: dict[str, str]) -> dict[str, str]:
        for rule_id in v:
            if not rule_id or rule_id.strip() != rule_id:
                raise ValueError(f"invalid rule id: {rule_id!r}")
            if any(ord(c) < 0x20 or c.isspace() for c in rule_id):
                # F14-A08: control-bearing rule ids crashed the render assert
                raise ValueError(f"rule id contains control/whitespace: {rule_id!r}")
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


def _iter_model_fields(obj):
    """Yield (attribute-name, value) for bool-annotated fields of a pydantic
    model, descending into nested models."""
    import types as _types

    for name, field in obj.model_fields.items():
        ann = field.annotation
        # unwrap Optional[bool]
        origin = typing.get_origin(ann)
        if origin is typing.Union or origin is _types.UnionType:
            args = [a for a in typing.get_args(ann) if a is not type(None)]
            ann = args[0] if len(args) == 1 and args[0] is bool else ann
        if ann is bool:
            yield name, getattr(obj, name)
    for name, field in obj.model_fields.items():
        val = getattr(obj, name)
        if hasattr(val, "model_fields"):  # nested model
            yield from _iter_model_fields(val)


def _assert_strict_bools(raw: dict, model_cls) -> None:
    """MECE round-7 (sol F7-D009): pydantic COERCES string booleans ('off' ->
    False) before validation ever sees them — 'strict' models only forbid
    extra keys. Pre-check the RAW mapping so a templating/quoting mistake
    refuses at load instead of silently enabling posting or fixes."""
    for name, field in model_cls.model_fields.items():
        ann = field.annotation
        origin = typing.get_origin(ann)
        if origin is typing.Union or origin is _types.UnionType:
            args = [a for a in typing.get_args(ann) if a is not type(None)]
            ann = args[0] if len(args) == 1 else ann
        if ann is bool and name in raw:
            v = raw[name]
            if v is not None and not isinstance(v, bool):
                raise ValueError(
                    f"boolean field {name!r} must be a real true/false, got "
                    f"{v!r} ({type(v).__name__}) — quote or type error")
        if hasattr(ann, "model_fields") and isinstance(raw.get(name), dict):
            # nested model configs (fix/omnisweep/...) carry bools too
            _assert_strict_bools(raw[name], ann)


def _warn_missing_forge_credentials(config) -> None:
    """MECE round-7 (sol F7-D010): every NON-GitHub forge binding needs its
    own credential env (the CLI mirrors the GH token only to GitHub hosts) —
    warn at load so an authless Forgejo binding never silently 401s forever."""
    import os

    from .forges import _is_github_base

    for bname, binding in config.forges.items():
        if not _is_github_base(binding.api_base) and binding.token_env \
                and not os.environ.get(binding.token_env):
            log.warning("forge binding %s (%s): token_env %s is not set in the "
                        "environment (expect 401s)", bname, binding.api_base,
                        binding.token_env)


def load_config(path: str | Path) -> RepoConfig:
    """Fail-loud loader: config errors abort the cycle, never silently skip."""
    raw = yaml.load(Path(path).read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
    _assert_strict_bools(raw, RepoConfig)  # F7-D009: pre-validation
    config = RepoConfig.model_validate(raw)
    for rid in config.review:
        # MECE round-7 (luna F7-001): rule ids ride into comment backticks
        # and parsed identities — newline/control riddled keys must refuse at
        # load, never inject at render
        if len(rid) > 80 or any(ch in rid for ch in ("\n", "\r", "`", "\x00")):
            raise ValueError(f"review rule id {rid!r} contains unsafe characters")
    _warn_missing_forge_credentials(config)  # F7-D010
    from .capabilities import default_review_rules
    merged = {**default_review_rules(), **config.review}
    config = config.model_copy(update={"review": merged})
    check_model_keys(config)
    return config
