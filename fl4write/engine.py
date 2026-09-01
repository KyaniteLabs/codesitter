"""Engine core: the cycle. Trigger seam + collect → dedupe → analyze →
gatekeep → post → fix-lane handoff → issues triage → metrics.

The trigger seam (ralplan): `run_cycle(config, trigger)` takes a NORMALIZED
trigger (repo, pr, reason) — cron is merely v1's trigger adapter; no `reason`
value bypasses the head-SHA predicate (state correctness is reason-blind).

Shadow mode: config.shadow=True logs the would-be post and touches nothing.
Mirror dedupe: PRs seen on a mirror forge with a head SHA already reviewed on
the primary are skipped without a second review.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

from . import fixlane, gatekeeper, renderer, state
from .analyzer import ModelUnavailable, analyze
from .config import RepoConfig
from .forges import ForgeAdapter, ForgeError, adapter_for
from .models import Finding, PullRequest
from .state import CycleLock, CycleLockHeld

log = logging.getLogger("fl4write")


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
    gatekeeper_dropped: int = 0
    fix_prs_opened: int = 0
    fix_prs_merged: int = 0
    issues_triaged: int = 0
    acceptance: dict[str, Any] = field(default_factory=dict)


def run_cycle(
    config: RepoConfig,
    state_path: Path,
    get_diff: Callable[[PullRequest], tuple[set[str], str]],
    trigger_reason: str = "cron",
    shadow_sink: ShadowSink | None = None,
    run_issues: bool = False,
    run_fixes: bool = False,
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
            for m in mirrors:
                try:
                    for mpr in m.list_open_prs(config.repo):
                        if mpr.head_sha in seen_shas:
                            report.skipped_mirror += 1
                except ForgeError as exc:
                    log.warning("mirror %s unavailable (degraded, continuing): %s", m.name, exc)
                    report.mirror_degraded += 1
            report.scanned = len(prs)

            reviewed_records: list[dict[str, Any]] = []

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
                    continue

                # Gatekeeper nit-filter (fail-open on model down)
                findings = doc.findings
                if findings:
                    findings, dropped = gatekeeper.filter_findings(findings, config)
                    report.gatekeeper_dropped += dropped

                rh = f"{pr.head_sha[:12]}{len(findings):04x}"
                previous: list[Finding] = []
                existing = primary.get_persistent_comment(config.repo, pr.number)
                if existing:
                    import re

                    prev_block = existing[1]
                    previous = [
                        Finding(
                            rule_id=m.group("rule") if "rule" in m.groupdict() else "general",
                            severity="Minor",
                            path=m.group("path"),
                            line=int(m.group("line")),
                            category="prior",
                            message=m.group("msg"),
                        )
                        for m in re.finditer(
                            r"\*\*\[(?P<sev>\w+)\] (?P<path>.+):(?P<line>\d+)\*\*"
                            r" \([^)]*rule `(?P<rule>[^`]+)`\) — (?P<msg>.+)",
                            prev_block,
                        )
                    ]
                body = renderer.render_review(pr, findings, config, rh, previous)
                if config.shadow:
                    if shadow_sink:
                        shadow_sink(config.repo, pr.number, body)
                    report.shadow_only = True
                elif existing:
                    primary.update_comment(config.repo, pr.number, existing[0], body)
                else:
                    primary.create_comment(config.repo, pr.number, body)
                outcome = f"shadow:{len(findings)}" if config.shadow else f"reviewed:{len(findings)}"
                state.mark_reviewed(st, pr.number, pr.head_sha, outcome)
                report.reviewed += 1
                reviewed_records.append({"pr": pr.number, "findings": len(findings)})

                # Fix-lane executor: attempt fixes for Critical/Major findings
                if run_fixes and config.fix.enabled and findings and not config.shadow:
                    from . import executor

                    for finding in findings:
                        if finding.severity in ("Critical", "Major"):
                            depth = st.get("prs", {}).get(str(pr.number), {}).get("fix_depth", 0)
                            result = executor.attempt_fix(pr, finding, config, depth)
                            if result["status"] == "pr_opened":
                                report.fix_prs_opened += 1
                            elif result["status"] == "blocked":
                                report.fix_escalations += 1
                            # Update depth
                            pr_state = st["prs"].setdefault(str(pr.number), {})
                            pr_state["fix_depth"] = depth + 1

                    # Check and merge our own PRs that have green CI
                    merged = executor.check_and_merge_own_prs(config, config.bot_login)
                    report.fix_prs_merged += len(merged)

            # Acceptance metrics snapshot
            if reviewed_records:
                from . import metrics

                report.acceptance = metrics.acceptance_snapshot(primary, config, reviewed_records)

            # Issues lane
            if run_issues:
                from . import issues as issues_lane

                issue_summary = issues_lane.run_issues_cycle(config, state_path, primary)
                report.issues_triaged = issue_summary.get("triaged", 0)

            state.save_state(state_path, st)
    except CycleLockHeld:
        log.info("cycle lock held — skipping this cycle (never double-post)")
        report.scanned = 0
    return report
