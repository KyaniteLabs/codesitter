"""Engine: one poll-invariant cycle per repo — collect, dedupe, review, fix, triage.

Design laws (ralplan-approved):
- The head-SHA predicate decides re-review; trigger reason is annotation only.
- get_diff is REQUIRED: grounding without a real diff file-set is vacuous.
- ONE state owner per cycle: this module loads once and saves once; lanes
  mutate the dict (a lane doing its own load+save caused the email-storm
  lost update — LEARNINGS #17). Checkpoint saves after each PR keep a
  mid-cycle kill from losing the whole cycle's memory.
- Per-PR containment: one PR's forge/model failure never aborts the others
  and never loses the cycle's state (the mirror degrade law, extended to
  primaries).

Audit 2026-09-01:
- previous_findings now parses the RENDERER's actual format via
  renderer.parse_finding_lines (the old regex matched a format nothing
  emitted — every finding was 🆕 forever and ✅ resolution never existed).
- config.gatekeeper and config.issues_enabled are honored (dead knobs).
- A model-failure retry cap per (PR, SHA) stops the infinite retry loop on
  permanently unparseable generations.
- Deadline awareness: start no new PR when the remaining budget can't fit a
  review, so a runner kill can't livelock the repo (LEARNINGS #24 class).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import fixlane, gatekeeper, renderer, state
from .config import RepoConfig
from .forges import ForgeAdapter, ForgeError, adapter_for
from .models import Finding, PullRequest
from .state import CycleLock, CycleLockHeld

log = logging.getLogger("fl4write.engine")

ShadowSink = Callable[[str, int, str], None]

REVIEW_BUDGET_S = 90  # worst-case model time for one review (2 routes x ~45s + slack)
MODEL_FAILURE_CAP = 3  # per (PR, head SHA); exceed = alert-and-stop retrying


@dataclass
class CycleReport:
    repo: str
    scanned: int = 0
    reviewed: int = 0
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
    skipped_diff_unavailable: int = 0
    postmerge_reviewed: int = 0
    alerts: list[str] = field(default_factory=list)


def _mirror_shas(mirrors: list[ForgeAdapter], repo: str, report: CycleReport) -> set[str]:
    """Mirror completeness set — degradation law: unreachable mirror logs+skips."""
    shas: set[str] = set()
    for m in mirrors:
        try:
            shas |= {pr.head_sha for pr in m.list_open_prs(repo)}
        except Exception as exc:  # mirror degrade law

            report.mirror_degraded += 1
            log.warning("mirror %s degraded (log+skip, never abort): %s", m.name, exc)
    return shas


def _prior_findings(prev_body: str) -> list[Finding]:
    """Reconstruct prior findings from our own comment via the renderer's
    parse contract (single source of truth with the emitter)."""
    return [
        Finding(rule_id=rule, severity=sev, path=path, line=line, category="prior", message="")
        for sev, path, line, rule in renderer.parse_finding_lines(prev_body)
    ]


def _review_pr(
    pr: PullRequest,
    config: RepoConfig,
    primary: ForgeAdapter,
    get_diff: Callable[[PullRequest], tuple[set[str], str] | None],
    shadow_sink: ShadowSink | None,
    st: dict[str, Any],
    report: CycleReport,
    run_fixes: bool,
    post_merge: bool = False,
) -> str:
    """Review one PR. Contained: any failure logs and returns — the cycle and
    its state survive. Returns the outcome: terminal outcomes ("reviewed",
    "shadow", "dependency-skip", "model-failed-cap") advance the post-merge
    watermark; deferred ones ("diff-unavailable", "model-unavailable") do
    not — the PR must be retried by a later sweep."""
    from .analyzer import ModelUnavailable, analyze

    diff = get_diff(pr)
    if diff is None:
        # Diff fetch failed: DO NOT review (vacuous grounding posts 🎉 over
        # real findings — LEARNINGS #3) and DO NOT mark reviewed.
        report.skipped_diff_unavailable += 1
        report.alerts.append(f"diff unavailable for #{pr.number} — not reviewed, will retry")
        return "diff-unavailable"
    diff_files, diff_text = diff

    try:
        doc = analyze(pr, diff_files, diff_text, config)
    except ModelUnavailable as exc:
        report.model_unavailable += 1
        key = f"{pr.number}:{pr.head_sha[:10]}"
        fails = int(st.get("model_failures", {}).get(key, 0)) + 1
        st.setdefault("model_failures", {})[key] = fails
        if fails >= MODEL_FAILURE_CAP:
            # Terminal: stop retrying this SHA (the alert asks for a human);
            # mark it so a re-listed PR is not re-modeled every sweep.
            state.mark_reviewed(st, pr.number, pr.head_sha, "model-failed-cap")
            report.alerts.append(f"#{pr.number}: model failed {fails}x at this SHA — needs human look")
            return "model-failed-cap"
        log.warning("model unavailable for %s#%s: %s", config.repo, pr.number, exc)
        return "model-unavailable"
    st.get("model_failures", {}).pop(f"{pr.number}:{pr.head_sha[:10]}", None)

    findings = doc.findings
    if findings and config.gatekeeper:
        findings, dropped = gatekeeper.filter_findings(findings, config)
        report.gatekeeper_dropped += dropped

    rh = f"{pr.head_sha[:12]}{len(findings):04x}"
    previous: list[Finding] = []
    existing = primary.get_persistent_comment(config.repo, pr.number)
    if existing:
        previous = _prior_findings(existing[1])
    body = renderer.render_review(
        pr, findings, config, rh, previous,
        gatekeeper_dropped=report.gatekeeper_dropped or 0,
        diff_truncated=bool(doc.digest.get("_diff_truncated")),
        post_merge=post_merge,
    )
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

    if run_fixes and config.fix.enabled and not config.shadow:
        _fix_lane(pr, findings, config, primary, st, report)

    return "shadow" if config.shadow else "reviewed"


def _fix_lane(
    pr: PullRequest,
    findings: list[Finding],
    config: RepoConfig,
    primary: ForgeAdapter,
    st: dict[str, Any],
    report: CycleReport,
) -> None:
    """Attempt fixes for Critical/Major findings; capped by fix_depth in state
    (which now PERSISTS across pushes — mark_reviewed merges, not replaces)."""
    from . import executor

    for f in findings:
        if f.severity not in ("Critical", "Major"):
            continue
        pr_state = st["prs"].setdefault(str(pr.number), {})
        depth = int(pr_state.get("fix_depth", 0))
        blocked = fixlane.fix_allowed(pr, config, depth)
        if blocked is not None:
            body = fixlane.escalate(pr, [f], blocked)
            primary.create_comment(config.repo, pr.number, body)
            report.fix_escalations += 1
            continue
        result = executor.attempt_fix(pr, f, config)
        if result.get("status") == "pr_opened":
            report.fix_prs_opened += 1
            pr_state["fix_depth"] = depth + 1
        elif result.get("status") == "error":
            log.warning("fix attempt failed for %s#%s: %s", config.repo, pr.number, result.get("reason"))
    try:
        # bot_identity REQUIRED (post-merge build): the merge gate re-verifies
        # authorship against it — a missing identity fails every merge closed.
        merged = executor.check_and_merge_own_prs(config, primary.bot_login)
        report.fix_prs_merged += merged
    except Exception as exc:  # merge scan must not kill the cycle

        log.warning("merge scan failed for %s: %s", config.repo, exc)


def _post_merge_sweep(
    config: RepoConfig,
    primary: ForgeAdapter,
    state_path: Path,
    get_diff: Callable[[PullRequest], tuple[set[str], str] | None],
    shadow_sink: ShadowSink | None,
    st: dict[str, Any],
    report: CycleReport,
    run_fixes: bool,
    deadline: float | None,
) -> set[int]:
    """Post-merge review mode (LEARNINGS #24): review PRs merged since the
    watermark — this org's PRs open and merge in ~60s, invisible to the
    open-PR poller. Findings land as post-merge comments; fixes ride follow-up
    PRs off the PR head (an ancestor of main once merged).

    Watermark law: it only advances past TERMINALLY-processed PRs (oldest
    first), so deferred ones (diff/model unavailable) are retried next cycle.
    At-most-once never depends on it: the head-SHA predicate + persistent-
    comment marker hold even on a full rewind. Returns the PR numbers this
    sweep considered — prune keeps their records one cycle so a rewind
    re-list hits the head-SHA guard, not a fresh model call."""
    from datetime import datetime, timedelta, timezone

    since = state.merged_watermark(st)
    if not since:
        since = (
            datetime.now(timezone.utc) - timedelta(hours=config.post_merge.initial_lookback_h)
        ).isoformat()
    try:
        merged_prs = primary.list_merged_prs(config.repo, since)
    except ForgeError as exc:
        report.alerts.append(f"post-merge listing failed (skipped this cycle): {exc}")
        log.warning("merged-PR listing failed for %s: %s", config.repo, exc)
        return set()

    capped = merged_prs[: config.post_merge.max_per_cycle]
    if len(merged_prs) > config.post_merge.max_per_cycle:
        report.alerts.append(
            f"post-merge backlog: {len(merged_prs)} merged PRs pending, "
            f"processing {len(capped)} this cycle"
        )

    terminal = 0
    for pr in capped:
        if deadline is not None and (deadline - time.monotonic()) < REVIEW_BUDGET_S:
            report.alerts.append("post-merge sweep deferred — cycle deadline reached")
            break
        bot_authored = bool(pr.is_bot_author)
        if bot_authored and fixlane.dependency_depth(pr, pr.title, config) in ("skip",):
            state.mark_reviewed(st, pr.number, pr.head_sha, "dependency-skip")
            report.skipped_dependency += 1
            terminal += 1
            continue
        if not state.needs_review(st, pr.number, pr.head_sha):
            terminal += 1  # already reviewed at this SHA (e.g. while open)
            continue
        try:
            outcome = _review_pr(
                pr, config, primary, get_diff, shadow_sink, st, report, run_fixes,
                post_merge=True,
            )
        except ForgeError as exc:
            report.alerts.append(f"#{pr.number}: forge error contained: {exc}")
            break  # do not advance the watermark past unprocessed PRs
        state.save_state(state_path, st)  # checkpoint after each merged PR
        if outcome in ("reviewed", "shadow", "model-failed-cap"):
            if outcome in ("reviewed", "shadow"):
                report.postmerge_reviewed += 1
            terminal += 1
        else:
            break  # deferred (diff/model): watermark stops before this PR

    if terminal:
        state.advance_merged_watermark(st, capped[terminal - 1].merged_at)
    return {pr.number for pr in capped}


def run_cycle(
    config: RepoConfig,
    state_path: Path,
    get_diff: Callable[[PullRequest], tuple[set[str], str] | None],
    trigger_reason: str = "cron",
    shadow_sink: ShadowSink | None = None,
    run_issues: bool = False,
    run_fixes: bool = False,
    deadline: float | None = None,
) -> CycleReport:
    """One poll-invariant cycle. `reason` is annotation only — the predicate
    in state.needs_review decides; nothing bypasses it. `get_diff` is
    REQUIRED and may return None on fetch failure (skip, don't fake)."""
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
            mirror_shas = _mirror_shas(mirrors, config.repo, report)

            try:
                prs = primary.list_open_prs(config.repo)
            except ForgeError as exc:
                report.alerts.append(f"primary unreachable: {exc}")
                log.warning("primary unreachable for %s: %s", config.repo, exc)
                prs = []

            open_numbers = set()
            for pr in prs:
                open_numbers.add(pr.number)
                report.scanned += 1
                if deadline is not None and (deadline - time.monotonic()) < REVIEW_BUDGET_S:
                    report.alerts.append("cycle deadline reached — remaining PRs deferred to next cycle")
                    break
                mirror_seen = pr.head_sha in mirror_shas
                if mirror_seen and trigger_reason == "mirror":
                    continue  # mirrored PRs are never reviewed twice
                bot_authored = bool(pr.is_bot_author)
                if bot_authored and fixlane.dependency_depth(pr, pr.title, config) in ("skip",):
                    state.mark_reviewed(st, pr.number, pr.head_sha, "dependency-skip")
                    report.skipped_dependency += 1
                    continue
                if not state.needs_review(st, pr.number, pr.head_sha):
                    continue
                try:
                    _review_pr(pr, config, primary, get_diff, shadow_sink, st, report, run_fixes)
                except ForgeError as exc:
                    # Per-PR containment (audit C7): a throttled/broken call
                    # must not abort the cycle or lose already-reviewed state.
                    report.alerts.append(f"#{pr.number}: forge error contained: {exc}")
                    log.warning("forge error on %s#%s (contained): %s", config.repo, pr.number, exc)
                state.save_state(state_path, st)  # checkpoint after each PR

            merged_keep: set[int] = set()
            if config.post_merge.enabled:
                # BEFORE prune_closed: the sweep's head-SHA guard must see this
                # cycle's merged records before prune could drop them.
                merged_keep = _post_merge_sweep(
                    config, primary, state_path, get_diff, shadow_sink, st,
                    report, run_fixes, deadline,
                )

            state.prune_closed(st, open_numbers | merged_keep)

            if run_issues and config.issues_enabled:
                from . import issues as issues_lane

                issue_summary = issues_lane.run_issues_cycle(config, st, primary)
                report.issues_triaged = issue_summary.get("triaged", 0)

            if not config.shadow:
                from . import metrics

                report.acceptance = metrics.acceptance_snapshot(primary, config)

            state.save_state(state_path, st)
    except CycleLockHeld as exc:
        log.warning("cycle lock held — skipping this cycle (never double-post): %s", exc)
        report.alerts.append(f"LOCK HELD: {exc}")
        report.scanned = 0
    except state.StateIOError as exc:
        report.alerts.append(str(exc))
    return report
