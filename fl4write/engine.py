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
    retro_reviewed: int = 0
    retro_zombies: int = 0
    ci_red_heads: int = 0
    ci_fix_prs_opened: int = 0
    ci_escalations: int = 0
    omni_scanned: int = 0
    omni_findings: int = 0
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
        if primary.name != "github":
            # Comorbidity pass catch: the executor's PR/merge path is
            # GitHub-hardcoded — attempting anyway burns a model call then
            # dies as a contained error every cycle (silent feature death).
            # Fail LOUD as an escalation instead.
            blocked = "fix lane is GitHub-only in v1 — Forgejo repos are review/comment-only"
            for f in findings:
                if f.severity in ("Critical", "Major"):
                    primary.create_comment(config.repo, pr.number, fixlane.escalate(pr, [f], blocked))
                    report.fix_escalations += 1
        else:
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

    # The cap bounds MODEL WORK (reviews), not list position: PRs already
    # terminal at this SHA (reviewed while open, dependency-skipped) pass
    # through free — otherwise a free-to-skip PR could starve a same-second
    # sibling behind it (caught by the same-second cap-split regression).
    terminal = 0  # watermark position: PRs terminally processed, oldest first
    reviewed_budget = 0
    considered: set[int] = set()
    for pr in merged_prs:
        considered.add(pr.number)
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
        if reviewed_budget >= config.post_merge.max_per_cycle:
            report.alerts.append(
                f"post-merge backlog: merged PRs pending beyond this cycle's cap "
                f"({config.post_merge.max_per_cycle}) — resuming next cycle"
            )
            break  # watermark stops BEFORE this unprocessed PR
        try:
            outcome = _review_pr(
                pr, config, primary, get_diff, shadow_sink, st, report, run_fixes,
                post_merge=True,
            )
        except ForgeError as exc:
            report.alerts.append(f"#{pr.number}: forge error contained: {exc}")
            break  # do not advance the watermark past unprocessed PRs
        state.save_state(state_path, st)  # checkpoint after each merged PR
        reviewed_budget += 1
        if outcome in ("reviewed", "shadow", "model-failed-cap"):
            if outcome in ("reviewed", "shadow"):
                report.postmerge_reviewed += 1
            terminal += 1
        else:
            break  # deferred (diff/model): watermark stops before this PR

    if terminal:
        terminal_prs = [p for p in merged_prs[:terminal]]
        state.advance_merged_watermark(st, terminal_prs[-1].merged_at)
    return considered


# CI-watch conclusions that mean RED (everything not in the benign set).
_CI_BENIGN = {"success", "skipped", "neutral", "canceled"}

# Omnisweep bounds (consensus-gated): files above this are skipped (the
# contents API refuses >1MB; anything near it is generated/vendored).
_OMNI_MAX_FILE_BYTES = 200_000
_OMNI_FIX_ATTEMPTS_PER_CYCLE = 3


def _omni_report_body(config: RepoConfig, findings: list[dict], scanned: int, total: int, complete: bool) -> str:
    """The audit-issue body: severity table + top-N findings + progress.
    Capped — the rest live in state (GitHub issue bodies cap at 64KB)."""
    cap = config.omnisweep.max_findings_in_issue
    sev_order = {s: i for i, s in enumerate(config.severity_vocab)}
    ordered = sorted(findings, key=lambda f: sev_order.get(f["sev"], 99))
    counts: dict[str, int] = {}
    for f in findings:
        counts[f["sev"]] = counts.get(f["sev"], 0) + 1
    table = "| Severity | Count |\n|---|---|\n" + "\n".join(
        f"| {s} | {counts.get(s, 0)} |" for s in config.severity_vocab
    )
    lines = [
        "## 🔍 Fl4wRite omnisweep — full-tree audit" + (" (COMPLETE)" if complete else ""),
        "",
        table,
        "",
        f"Progress: **{scanned}/{total}** files scanned at HEAD." if total else "",
        "",
    ]
    for f in ordered[:cap]:
        lines.append(f"### {f['sev']} — `{f['path']}:{f['line']}` — `{f['rule']}`\n{f['msg']}\n")
    if len(ordered) > cap:
        lines.append(f"… and {len(ordered) - cap} more findings recorded in sweep state.\n")
    if complete:
        lines.append("_Sweep complete. Findings above are at current HEAD; the fix lane (if enabled for this repo) will open PRs for qualifying severities._")
    return "\n".join(lines)


def _omni_fix_phase(
    config: RepoConfig, primary: ForgeAdapter, st: dict[str, Any], report: CycleReport
) -> None:
    """Post-completion fix drain. SEPARATELY gated (omnisweep.fix) — cold-code
    findings lack the reviewed-diff premise the fix lane was built on.
    Rails asserted HERE, not only in config: severity floor, GitHub-only,
    stable hash-salted branch numbers (blake2b(head:id) — no positional
    arithmetic, no wrap, ever)."""
    import hashlib

    from . import executor

    if config.omnisweep.fix_min_severity not in config.severity_vocab:  # rail, in code
        report.alerts.append("omnisweep.fix_min_severity invalid — fix phase skipped")
        return
    if primary.name != "github":
        report.alerts.append("omnisweep fix phase: GitHub-only in v1 — findings stay in the audit issue")
        return
    sev_floor = config.severity_vocab.index(config.omnisweep.fix_min_severity)
    head = st.get("omni_head", "")
    if not head:
        return
    attempts = 0
    for f in st.get("omni_findings", []):
        if attempts >= _OMNI_FIX_ATTEMPTS_PER_CYCLE:
            break
        if f.get("fix_attempted") or config.severity_vocab.index(f["sev"]) > sev_floor:
            continue
        f["fix_attempted"] = True
        attempts += 1
        synth = PullRequest(
            forge=primary.name,
            number=int(hashlib.blake2b(f"{head}:{f['id']}".encode(), digest_size=8).hexdigest()[:12], 16),
            repo=config.repo,
            title=f"omnisweep fix: {f['path']}:{f['line']}",
            head_sha=head,
        )
        from .models import Finding as _F

        finding = _F(
            rule_id=f["rule"], severity=f["sev"], path=f["path"], line=f["line"],
            category="omnisweep", message=f["msg"],
        )
        result = executor.attempt_fix(synth, finding, config)
        if result.get("status") == "pr_opened":
            report.fix_prs_opened += 1
        else:
            log.warning("omni fix failed for %s:%s: %s", f["path"], f["line"], result.get("reason"))


def _omnisweep_step(
    config: RepoConfig,
    primary: ForgeAdapter,
    state_path: Path,
    shadow_sink: ShadowSink | None,
    st: dict[str, Any],
    report: CycleReport,
    deadline: float | None,
) -> None:
    """Omnisweep: full-tree scan at HEAD, one file per model call, findings
    compacted into state and surfaced as ONE audit issue edited in place.
    Cursor-resumable, capped per cycle, terminal on exhaustion; the total-
    files cap aborts the sweep loudly. Fix phase runs only after completion
    and only through the separately-gated _omni_fix_phase."""
    import fnmatch

    from . import gatekeeper
    from .analyzer import ModelUnavailable, analyze

    if st.get("omni_complete"):
        if config.omnisweep.fix and st.get("omni_findings"):
            _omni_fix_phase(config, primary, st, report)
        return

    tree = primary.list_tree_files(config.repo)
    if tree is None:
        report.alerts.append("omnisweep: tree listing unqueryable (skipped this cycle)")
        return
    files, truncated = tree
    if truncated:
        report.alerts.append("omnisweep: tree listing TRUNCATED by the forge — sweep may miss files")

    excludes = config.omnisweep.exclude + (config.path_filters or {}).get("ignore", [])
    scan = sorted(
        p for (p, size) in files
        if 0 < size <= _OMNI_MAX_FILE_BYTES
        and not any(fnmatch.fnmatch(p, pat) for pat in excludes)
    )
    total = len(scan)
    scanned_total = int(st.get("omni_scanned_total", 0))
    if scanned_total + total > config.omnisweep.max_total_files:
        report.alerts.append(
            f"omnisweep ABORTED: {scanned_total + total} files exceeds "
            f"max_total_files={config.omnisweep.max_total_files} — widen the cap or narrow excludes"
        )
        st["omni_complete"] = True
        return

    cursor = st.get("omni_cursor", "")
    pending = [p for p in scan if p > cursor][: config.omnisweep.max_files_per_cycle]
    if not pending:
        st["omni_complete"] = True
        findings = st.get("omni_findings", [])
        _omni_upsert_issue(config, primary, st, findings, len(scan), len(scan), complete=True, report=report)
        report.alerts.append(f"omnisweep complete: {len(findings)} findings across {total} files")
        if config.omnisweep.fix and findings:
            _omni_fix_phase(config, primary, st, report)
        return

    # anchor for the fix phase: HEAD moves mid-sweep → findings from an older
    # HEAD are re-anchored by the freshness of the file fetch at fix time.
    if not st.get("omni_head"):
        anchor = primary.head_check_runs(config.repo)
        if anchor:
            st["omni_head"] = anchor[0]

    scanned_this_cycle = 0
    for path in pending:
        if deadline is not None and (deadline - time.monotonic()) < REVIEW_BUDGET_S:
            report.alerts.append("omnisweep deferred — cycle deadline reached")
            break
        content = primary.get_file(config.repo, path, st.get("omni_head", "") or "HEAD")
        if content is None:
            st["omni_cursor"] = path  # unfetchable files are skipped, not retried forever
            continue
        synth = PullRequest(
            forge=primary.name, number=0, repo=config.repo,
            title=f"omnisweep: {path}", head_sha=st.get("omni_head", "") or "HEAD",
        )
        try:
            doc = analyze(synth, {path}, content, config, mode="file")
        except ModelUnavailable as exc:
            report.model_unavailable += 1
            log.warning("omnisweep model unavailable at %s: %s", path, exc)
            break  # deferred: cursor stays before this file
        findings = doc.findings
        if findings:
            findings, dropped = gatekeeper.filter_findings(findings, config)
            report.gatekeeper_dropped += dropped
        next_id = int(st.get("omni_next_id", 1))
        for f in findings:
            st.setdefault("omni_findings", []).append({
                "id": next_id, "path": f.path, "line": f.line, "rule": f.rule_id,
                "sev": f.severity, "msg": f.message[:200],  # compact: no proposals in state
            })
            next_id += 1
        st["omni_next_id"] = next_id
        st["omni_cursor"] = path
        scanned_this_cycle += 1
        state.save_state(state_path, st)  # checkpoint after each file
    st["omni_scanned_total"] = scanned_total + scanned_this_cycle
    report.omni_scanned = scanned_this_cycle
    report.omni_findings = len(st.get("omni_findings", []))
    done = st.get("omni_cursor", "") >= scan[-1] if scan else True
    if done and scanned_this_cycle:
        # finalized in the SAME cycle as the last file — no idle hourly hop
        st["omni_complete"] = True
        report.alerts.append(
            f"omnisweep complete: {report.omni_findings} findings across {total} files"
        )
        _omni_upsert_issue(
            config, primary, st, st.get("omni_findings", []),
            total, total, complete=True, report=report,
        )
        if config.omnisweep.fix and st.get("omni_findings"):
            _omni_fix_phase(config, primary, st, report)
    else:
        _omni_upsert_issue(
            config, primary, st, st.get("omni_findings", []),
            len([p for p in scan if p <= st.get("omni_cursor", "")]), total, complete=False, report=report,
        )


def _omni_upsert_issue(
    config: RepoConfig, primary: ForgeAdapter, st: dict[str, Any],
    findings: list[dict], scanned: int, total: int, complete: bool, report: CycleReport,
) -> None:
    """Create-or-edit the ONE audit issue per repo, through the adapter.
    Shadow mode touches nothing. Findings live in state — an issue failure
    degrades to next-cycle retry, never data loss."""
    if config.shadow or not findings:
        return
    body = _omni_report_body(config, findings, scanned, total, complete)
    number = st.get("omni_issue")
    if number:
        if not primary.update_issue(config.repo, number, body):
            report.alerts.append(f"omnisweep: issue #{number} update failed — retrying next cycle")
        return
    created = primary.open_issue(
        config.repo, f"omnisweep: full-tree audit of {config.repo}", body,
    )
    if created is None:
        report.alerts.append("omnisweep: audit-issue creation failed — retrying next cycle")
        return
    st["omni_issue"] = created


def _retro_sweep(
    config: RepoConfig,
    primary: ForgeAdapter,
    state_path: Path,
    get_diff: Callable[[PullRequest], tuple[set[str], str] | None],
    shadow_sink: ShadowSink | None,
    st: dict[str, Any],
    report: CycleReport,
    deadline: float | None,
) -> set[int]:
    """Retro audit (CEO ask: catch any OLD mistakes): walk merged PRs OLDER
    than the forward post-merge watermark — newest-first, capped per cycle,
    cursor-resumable (`retro_cursor` = oldest merged_at processed; everything
    above it is pending until done). Freshness gate drops findings whose path
    no longer exists on HEAD (zombies on fixed code); an all-zombie PR posts
    NOTHING. Guards: cursor (primary), retro_seen set (same-second belt),
    head-SHA records (suspenders). Returns considered numbers for prune."""
    from datetime import datetime, timedelta, timezone

    if st.get("retro_complete"):
        return set()
    boundary = (
        datetime.now(timezone.utc) - timedelta(days=config.retro_audit.lookback_days)
    ).isoformat()
    upper = state.merged_watermark(st) or datetime.now(timezone.utc).isoformat()
    cursor = st.get("retro_cursor") or upper

    try:
        listed = primary.list_merged_prs(config.repo, boundary)
    except ForgeError as exc:
        report.alerts.append(f"retro listing failed (skipped this cycle): {exc}")
        return set()

    seen: set[int] = set(st.get("retro_seen", {}))
    pending = sorted(
        (p for p in listed
         if p.merged_at < cursor and p.number not in seen),
        key=lambda p: p.merged_at,
        reverse=True,  # newest unprocessed first: recent mistakes matter most
    )[: config.retro_audit.max_per_cycle]

    considered: set[int] = set()
    oldest_processed: str | None = None
    for pr in pending:
        considered.add(pr.number)
        if deadline is not None and (deadline - time.monotonic()) < REVIEW_BUDGET_S:
            report.alerts.append("retro sweep deferred — cycle deadline reached")
            break
        seen.add(pr.number)
        st["retro_seen"] = {n: True for n in seen}
        if not state.needs_review(st, pr.number, pr.head_sha):
            oldest_processed = pr.merged_at
            continue  # already reviewed at this SHA while it was open — nothing to catch
        outcome = _retro_review_pr(
            pr, config, primary, get_diff, shadow_sink, st, report,
        )
        state.save_state(state_path, st)
        if outcome == "deferred":
            seen.discard(pr.number)  # retry next cycle
            st["retro_seen"] = {n: True for n in seen}
            break
        oldest_processed = pr.merged_at

    if oldest_processed:
        st["retro_cursor"] = oldest_processed
    if oldest_processed is None and not pending:
        # window exhausted between boundary and cursor — nothing left to audit
        # (also fires for repos with no merges in the window: stop re-listing)
        st["retro_complete"] = True
        report.alerts.append(
            f"retro audit complete: {len(seen)} merged PRs within "
            f"{config.retro_audit.lookback_days}d swept"
        )
    return considered


def _retro_review_pr(
    pr: PullRequest,
    config: RepoConfig,
    primary: ForgeAdapter,
    get_diff: Callable[[PullRequest], tuple[set[str], str] | None],
    shadow_sink: ShadowSink | None,
    st: dict[str, Any],
    report: CycleReport,
) -> str:
    """One retro review: same pipeline as post-merge, plus the freshness gate.
    Returns 'reviewed' | 'shadow' | 'deferred' (deferred = retried later)."""
    from .analyzer import ModelUnavailable, analyze
    from . import gatekeeper

    diff = get_diff(pr)
    if diff is None:
        report.skipped_diff_unavailable += 1
        return "deferred"
    diff_files, diff_text = diff

    try:
        doc = analyze(pr, diff_files, diff_text, config)
    except ModelUnavailable:
        report.model_unavailable += 1
        return "deferred"  # retro never caps: the cursor already passed it; retry is free

    findings = doc.findings
    if findings and config.gatekeeper:
        findings, dropped = gatekeeper.filter_findings(findings, config)
        report.gatekeeper_dropped += dropped

    if findings and config.retro_audit.freshness_gate:
        fresh: list = []
        for f in findings:
            exists = primary.path_exists(config.repo, f.path)
            if exists is False:
                report.retro_zombies += 1  # path gone from HEAD: fixed/moved code
                continue
            fresh.append(f)  # True or None (unqueryable → fail open, keep)
        findings = fresh

    if not findings and not _has_prior_findings(primary, config, pr.number):
        # all-zombie or clean: post NOTHING on the old PR (zero-noise law);
        # the state record is the audit trail.
        state.mark_reviewed(st, pr.number, pr.head_sha, "retro:0")
        return "reviewed"

    rh = f"{pr.head_sha[:12]}{len(findings):04x}"
    previous: list[Finding] = []
    existing = primary.get_persistent_comment(config.repo, pr.number)
    if existing:
        previous = _prior_findings(existing[1])
    body = renderer.render_review(
        pr, findings, config, rh, previous, post_merge=True,
        gatekeeper_dropped=report.gatekeeper_dropped or 0,
        diff_truncated=bool(doc.digest.get("_diff_truncated")),
    )
    if config.shadow:
        if shadow_sink:
            shadow_sink(config.repo, pr.number, body)
        report.shadow_only = True
        state.mark_reviewed(st, pr.number, pr.head_sha, f"shadow:{len(findings)}")
        report.retro_reviewed += 1
        return "shadow"
    if existing:
        primary.update_comment(config.repo, pr.number, existing[0], body)
    else:
        primary.create_comment(config.repo, pr.number, body)
    state.mark_reviewed(st, pr.number, pr.head_sha, f"retro:{len(findings)}")
    report.retro_reviewed += 1
    return "reviewed"


def _has_prior_findings(primary: ForgeAdapter, config: RepoConfig, number: int) -> bool:
    """Does our own persistent comment on this PR already carry findings?
    (Edit-in-place continues the thread; clean/zombie results stay silent.)"""
    existing = primary.get_persistent_comment(config.repo, number)
    return bool(existing and renderer.parse_finding_lines(existing[1]))


def _ci_watch_step(
    config: RepoConfig,
    primary: ForgeAdapter,
    st: dict[str, Any],
    report: CycleReport,
    run_fixes: bool,
) -> None:
    """CEO directive 2026-09-01: a red default-branch HEAD on an OWN repo
    summons review + fix. SHA-keyed (state['ci_acted:{sha}']) — no timestamp
    watermark, self-healing on the next commit, same law as the head-SHA
    predicate. Findings come from the failing checks' annotations (a
    deterministic signal — the model is never asked to invent them); the fix
    lane attempts one patch per finding; no fix landing escalates to an issue.
    Contained: any failure logs and returns."""
    from . import executor
    from .models import Finding

    queried = primary.head_check_runs(config.repo)
    if queried is None:
        log.info("ci_watch: head check-runs unqueryable for %s (degraded this cycle)", config.repo)
        return
    head, runs = queried
    failing = [
        r for r in runs
        if r.get("status") == "completed" and r.get("conclusion") not in _CI_BENIGN
    ][: config.ci_watch.max_checks]
    if not failing:
        st.pop("ci_red_sha", None)
        return
    report.ci_red_heads += 1
    if st.get(f"ci_acted:{head}"):
        return  # already acted at this SHA — a new commit re-arms the watch
    st[f"ci_acted:{head}"] = True

    findings: list[Finding] = []
    summaries: list[str] = []
    for run in failing:
        name = run.get("name") or "unnamed check"
        conclusion = run.get("conclusion") or "?"
        summary = ((run.get("output") or {}).get("summary") or "").strip()
        summaries.append(f"- **{name}** — {conclusion}" + (f": {summary[:300]}" if summary else ""))
        anns = primary.check_annotations(config.repo, run.get("id")) or []
        for a in anns[: config.ci_watch.max_annotations]:
            if not a.get("path") or not a.get("message"):
                continue
            findings.append(
                Finding(
                    rule_id="ci",
                    severity="Major",
                    path=a["path"],
                    line=int(a.get("start_line") or 0) or 1,
                    category="CI",
                    message=f"[{name}] {a['message'][:400]}",
                )
            )

    if findings and run_fixes and config.fix.enabled and not config.shadow:
        # Synthetic PR anchored at the red head: the fix lane fetches the file
        # at this SHA, patches, tests sandboxed, opens a follow-up PR. A
        # sha-derived number keeps branch names unique per red head.
        synth = PullRequest(
            forge=primary.name,
            number=int(head[:6], 16),
            repo=config.repo,
            title=f"CI fix @ {head[:8]}",
            head_sha=head,
        )
        for f in findings[: config.ci_watch.max_annotations]:
            result = executor.attempt_fix(synth, f, config)
            if result.get("status") == "pr_opened":
                report.ci_fix_prs_opened += 1
            elif result.get("status") == "error":
                log.warning("ci fix failed for %s@%s: %s", config.repo, head[:8], result.get("reason"))
                break  # environmental failure: stop burning attempts this cycle
        opened = report.ci_fix_prs_opened
    else:
        opened = 0

    if not opened and config.ci_watch.escalate_issues and not config.shadow:
        try:
            executor.open_issue(
                config.repo,
                title=f"CI red on main @ {head[:8]} — {', '.join(r.get('name') or '?' for r in failing)}",
                body=(
                    "## Fl4wRite CI watch — human action required\n\n"
                    f"Default-branch HEAD `{head}` is red; no automated fix landed.\n\n"
                    f"Failing checks:\n" + "\n".join(summaries) +
                    "\n\n_Findings from annotations:_\n"
                    + ("\n".join(f"- `{f.path}:{f.line}` — {f.message[:120]}" for f in findings) or "(none — failing checks produced no annotations)")
                ),
            )
            report.ci_escalations += 1
        except Exception as exc:  # noqa: BLE001 — escalation must not kill the cycle
            report.alerts.append(f"ci_watch escalation failed for {config.repo}: {exc}")


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

            if config.ci_watch.enabled:
                _ci_watch_step(config, primary, st, report, run_fixes)

            if config.retro_audit.enabled:
                merged_keep |= _retro_sweep(
                    config, primary, state_path, get_diff, shadow_sink, st,
                    report, deadline,
                )

            if config.omnisweep.enabled:
                _omnisweep_step(
                    config, primary, state_path, shadow_sink, st, report, deadline,
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
