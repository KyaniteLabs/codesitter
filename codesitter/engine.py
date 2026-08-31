"""Engine core: the cycle. Trigger seam + collect -> dedupe -> analyze -> post.

The trigger seam (ralplan): `run_cycle(config, trigger)` takes a NORMALIZED
trigger (repo, pr, reason) — cron is merely v1's trigger adapter; no `reason`
value bypasses the head-SHA predicate (state correctness is reason-blind).

Shadow mode: config.shadow=True logs the would-be post and touches nothing.
Mirror dedupe: PRs seen on a mirror forge with a head SHA already reviewed on
the primary are skipped without a second review.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from . import fixlane, renderer, state
from .analyzer import ModelUnavailable, analyze
from .config import RepoConfig
from .forges import ForgeAdapter, ForgeError, adapter_for
from .models import Finding, PullRequest
from .state import CycleLock, CycleLockHeld

log = logging.getLogger("codesitter")


class ShadowSink(Protocol):
    def __call__(self, repo: str, pr_number: int, body: str) -> None: ...


@dataclass
class CycleReport:
    repo: str
    scanned: int = 0
    reviewed: int = 0
    skipped_mirror: int = 0
    mirror_degraded: int = 0
    skipped_dependency: int = 0
    fix_escalations: int = 0
    model_unavailable: int = 0
    shadow_only: bool = False


def run_cycle(
    config: RepoConfig,
    state_path: Path,
    get_diff: Callable[[PullRequest], tuple[set[str], str]],
    trigger_reason: str = "cron",
    shadow_sink: ShadowSink | None = None,
) -> CycleReport:
    """One poll-invariant cycle. `reason` is annotation only — the predicate
    in state.needs_review decides; nothing bypasses it. `get_diff` is
    REQUIRED: grounding without a real diff file-set is vacuous (review
    finding 1) — a missing fetcher is a config error that aborts loudly."""
    report = CycleReport(repo=config.repo, shadow_only=config.shadow)
    primary_name = next(k for k, b in config.forges.items() if b.role == "primary")
    primary: ForgeAdapter = adapter_for(config.forges[primary_name])
    primary.bot_login = config.bot_login
    mirrors = [adapter_for(b) for b in config.forges.values() if b.role == "mirror"]
    for m in mirrors:
        m.bot_login = config.bot_login

    try:
        with CycleLock(state_path.with_suffix(".lock")):
            st = state.load_state(state_path)
            prs = primary.list_open_prs(config.repo, st.get("watermark"))
            seen_shas: dict[str, str] = {}
            for pr in prs:
                seen_shas.setdefault(pr.head_sha, f"{pr.forge}:{pr.number}")
            for m in mirrors:  # mirror dedupe (ralplan): same SHA = same PR.
                # Degradation law: a mirror is a dedupe optimization, NEVER a
                # correctness dependency — an unreachable/unauthorized mirror
                # logs and skips; the primary cycle proceeds regardless.
                try:
                    for mpr in m.list_open_prs(config.repo):
                        if mpr.head_sha in seen_shas:
                            report.skipped_mirror += 1
                except ForgeError as exc:
                    log.warning("mirror %s unavailable (degraded, continuing): %s", m.name, exc)
                    report.mirror_degraded += 1
            report.scanned = len(prs)
            for pr in prs:
                if not state.needs_review(st, pr.number, pr.head_sha):
                    continue
                dep = fixlane.dependency_depth(pr, pr.title, config)
                if dep == "skip":
                    report.skipped_dependency += 1
                    state.mark_reviewed(st, pr.number, pr.head_sha, "dependency-skip")
                    continue
                try:
                    diff_files, diff_text = get_diff(pr)
                    doc = analyze(pr, diff_files, diff_text, config)
                except ModelUnavailable as exc:
                    log.warning("model unavailable for %s#%s: %s", config.repo, pr.number, exc)
                    report.model_unavailable += 1
                    continue  # unreviewed stays unreviewed — never silent skip
                rh = f"{pr.head_sha[:12]}{len(doc.findings):04x}"
                previous: list[Finding] = []
                existing = primary.get_persistent_comment(config.repo, pr.number)
                if existing:
                    import re

                    prev_block = existing[1]
                    previous = [
                        Finding(
                            rule_id="general",
                            severity="Minor",
                            path=m.group(1),
                            line=int(m.group(2)),
                            category="prior",
                            message=m.group(3),
                        )
                        for m in re.finditer(r"\*\*?\[?\w+\]?\*?\*? (\S+):(\d+)\*\*.*?— (.+)", prev_block)
                    ]
                body = renderer.render_review(pr, doc.findings, config, rh, previous)
                if config.shadow:
                    if shadow_sink:
                        shadow_sink(config.repo, pr.number, body)
                    report.shadow_only = True
                elif existing:
                    primary.update_comment(config.repo, pr.number, existing[0], body)
                else:
                    primary.create_comment(config.repo, pr.number, body)
                outcome = f"shadow:{len(doc.findings)}" if config.shadow else f"reviewed:{len(doc.findings)}"
                state.mark_reviewed(st, pr.number, pr.head_sha, outcome)
                report.reviewed += 1
            state.save_state(state_path, st)
    except CycleLockHeld:
        log.info("cycle lock held — skipping this cycle (never double-post)")
        report.scanned = 0
    return report
