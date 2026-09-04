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

from . import scrub
import re
import time
from collections import Counter
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
_TEST_FILE_RE = re.compile(
    r"(^|/)(test_[^/]+\.py|[^/]+_test\.(go|rs|ts|js)|[^/]+\.test\.(ts|js|tsx|jsx)|tests?\.py)$"
)
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
    gatekeeper_failed: int = 0
    fix_attempts: int = 0
    fix_failures: int = 0
    _fix_failure_notes: list = field(default_factory=list)
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
    deadline: float | None = None,
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
    findings: list = []

    # Deterministic spec check first: run the diff's own tests (sandboxed).
    # Rails (audit A2): NEVER on fork PRs (hostile by org law); GitHub-only
    # (the fetch is github.com — on Forgejo it silently died per-cycle).
    # Budget (audit A7): verify can cost ~500s worst case — reserve it or skip.
    test_like = sorted(p for p in diff_files if _TEST_FILE_RE.search(p))
    if (
        test_like and config.verify_tests and not config.shadow
        and not pr.is_fork and primary.name == "github"
        and (deadline is None or (deadline - time.monotonic()) > REVIEW_BUDGET_S + 500)
    ):
        from . import executor as _ex

        failing = _ex.verify_diff_tests(pr, config, test_like)
        if failing is not None:
            findings.append(failing)
            report.alerts.append(
                f"#{pr.number}: diff's own tests FAIL at head — deterministic Critical filed"
            )
        elif deadline is not None and (deadline - time.monotonic()) < REVIEW_BUDGET_S + 5:
            # MECE round-3 (glm F3-3): verify_tests can consume ~500s of a
            # ~90s review budget — defer the analyze rather than overrun the
            # whole cycle on one PR (the old comment claimed a later gate
            # that never existed)
            report.alerts.append(f"#{pr.number}: verify consumed the review budget — deferred")
            return "deferred"

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

    deterministic = [f for f in findings if f.category == "CI"]
    findings = [f for f in findings if f.category != "CI"] + doc.findings
    dropped_here = 0  # MECE round-4 (luna F4-006): per-PR count for the comment
    if findings and config.gatekeeper:
        findings, dropped, failed_open = gatekeeper.filter_findings(findings, config)
        report.gatekeeper_dropped += dropped
        dropped_here = dropped
        if failed_open:
            report.gatekeeper_failed += 1
    # the deterministic verify finding is NEVER gatekeeper-droppable (A4)
    findings = deterministic + findings

    rh = f"{pr.head_sha[:12]}{len(findings):04x}"
    previous: list[Finding] = []
    existing = primary.get_persistent_comment(config.repo, pr.number)
    if existing:
        previous = _prior_findings(existing[1])
    body = renderer.render_review(
        pr, findings, config, rh, previous,
        gatekeeper_dropped=dropped_here or 0,
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

    # finding-level severity into telemetry (the gap: the quality loop
    # couldn't measure "fixable findings per day" without this)
    from . import telemetry as _tel
    sev_counts = Counter(f.severity for f in findings)
    _tel.emit("review", repo=config.repo, pr=pr.number,
              findings_total=len(findings), severity=dict(sev_counts),
              lane="post-merge" if post_merge else "pr")

    if run_fixes and config.fix.enabled and not config.shadow:
        if any(f.category == "CI" for f in findings):
            # audit A5: a verify Critical anchors at the TEST file — the fix
            # lane patching it is structurally test-weakening. Human surface.
            findings_for_fix = [f for f in findings if f.category != "CI"]
            report.alerts.append(
                f"#{pr.number}: failing-diff Critical posted for HUMAN action — "
                "the fix lane will not patch test files"
            )
        else:
            findings_for_fix = findings
        if primary.name != "github":
            # Comorbidity pass catch: the executor's PR/merge path is
            # GitHub-hardcoded — attempting anyway burns a model call then
            # dies as a contained error every cycle (silent feature death).
            # Fail LOUD as an escalation instead.
            blocked = "fix lane is GitHub-only in v1 — Forgejo repos are review/comment-only"
            # MECE round-1 (M3 DOM-C #7): escalate ONCE with the full finding
            # list — one comment per finding was comment-spam on FJ PRs
            escalatable = [f for f in findings_for_fix if f.severity in ("Critical", "Major")]
            if escalatable:
                primary.create_comment(config.repo, pr.number,
                                       fixlane.escalate(pr, escalatable, blocked))
                report.fix_escalations += len(escalatable)
        else:
            _fix_lane(pr, findings_for_fix, config, primary, st, report)

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
        if not _fix_freshness_gate(primary, config, f):
            continue
        report.fix_attempts += 1
        result = executor.attempt_fix(pr, f, config)
        status = result.get("status")
        if status == "pr_opened":
            report.fix_prs_opened += 1
            pr_state["fix_depth"] = depth + 1
        elif status in ("error", "testfail", "nofix"):
            # enumerated failure classes (the Architect's V2): every outcome
            # is COUNTED; the summarizing alert fires once at cycle end
            report.fix_failures += 1
            report._fix_failure_notes.append(f"#{pr.number} {status}: {str(result.get('reason'))[:80]}")
        elif status == "blocked":
            report.fix_escalations += 1
        else:
            # Sol audit: unknown statuses had no denominator — count + surface
            report.fix_failures += 1
            report._fix_failure_notes.append(f"#{pr.number} unknown-status {status!r}")
    try:
        # bot_identity REQUIRED (post-merge build): the merge gate re-verifies
        # authorship against it — a missing identity fails every merge closed.
        merged = executor.check_and_merge_own_prs(config, primary.bot_login)
        report.fix_prs_merged += len(merged)  # Sol audit: was int += list
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
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        # UltraQA round 3: shape drift degrades the lane, never crashes
        report.alerts.append(f"post-merge listing degraded (skipped this cycle): {exc}")
        return set()
    merged_prs = [p for p in merged_prs if isinstance(p, PullRequest)]

    # The cap bounds MODEL WORK (reviews), not list position: PRs already
    # terminal at this SHA (reviewed while open, dependency-skipped) pass
    # through free — otherwise a free-to-skip PR could starve a same-second
    # sibling behind it (caught by the same-second cap-split regression).
    terminal = 0  # watermark position: PRs terminally processed, oldest first
    reviewed_budget = 0
    considered: set[int] = set()
    # MECE round-5 (sol F5-001): shadow runs keep their own dedupe belt and
    # never advance the live watermark — a shadow-reviewed merged PR must be
    # re-reviewed (posted) after the live cutover
    pm_shadow: dict[str, str] = {}
    if config.shadow:
        sb = st.get("pm_shadow_seen")
        if isinstance(sb, dict):
            pm_shadow = {str(k): v for k, v in sb.items() if isinstance(v, str)}
    for pr in merged_prs:
        considered.add(pr.number)
        if config.shadow and pm_shadow.get(str(pr.number)) == pr.head_sha:
            continue  # already shadow-reviewed at this SHA — belt, not terminal
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
                post_merge=True, deadline=deadline,
            )
        except ForgeError as exc:
            report.alerts.append(f"#{pr.number}: forge error contained: {exc}")
            break  # do not advance the watermark past unprocessed PRs
        state.save_state(state_path, st)  # checkpoint after each merged PR
        reviewed_budget += 1
        if outcome == "shadow":
            pm_shadow[str(pr.number)] = pr.head_sha
            report.postmerge_reviewed += 1
            continue  # NOT terminal — the live cutover re-reviews and posts
        if outcome in ("reviewed", "model-failed-cap"):
            if outcome == "reviewed":
                report.postmerge_reviewed += 1
            terminal += 1
        else:
            break  # deferred (diff/model): watermark stops before this PR

    if config.shadow and pm_shadow:
        st["pm_shadow_seen"] = pm_shadow
    elif not config.shadow and isinstance(st.get("pm_shadow_seen"), dict):
        st.pop("pm_shadow_seen", None)
    if terminal:
        terminal_prs = [p for p in merged_prs[:terminal]]
        state.advance_merged_watermark(st, terminal_prs[-1].merged_at)
    return considered


# CI-watch conclusions that mean RED (everything not in the benign set).
_CI_BENIGN = {"success", "skipped", "neutral", "canceled"}


def _fix_freshness_gate(primary: ForgeAdapter, config: RepoConfig, finding) -> bool:
    """True = fresh enough to attempt a fix. The #503 class: a finding on a
    file deleted/moved after review made every attempt fail at fetch,
    invisibly. False = skip the fix (finding stays posted); None-probe =
    fail-open (proceed)."""
    exists = primary.path_exists(config.repo, finding.path)
    if exists is False:
        log.info("fix freshness gate: %s gone from HEAD — skipping fix", finding.path)
        return False
    return True

# Omnisweep bounds (consensus-gated): files above this are skipped (the
# contents API refuses >1MB; anything near it is generated/vendored).
_OMNI_MAX_FILE_BYTES = 200_000
_OMNI_FIX_ATTEMPTS_PER_CYCLE = 3


def _omni_readiness(findings: list[dict]) -> tuple[int, str]:
    """CheckYourself-style readiness score from the sweep's findings.
    MECE round-1 (terra F1-11): the missing-evidence cap was INERT — no caller
    ever passed categories_checked. Now derived from each finding's rule
    category, so a sweep that never checked e.g. Auth & Access is capped."""
    from .capabilities import CAPABILITIES, readiness_score, score_label
    from collections import Counter

    sev = Counter(f.get("sev", f.get("severity", "Nit")) for f in findings)
    rule_to_cat = {rid: cat for rid, cat, _, _ in CAPABILITIES}
    # persisted omni findings carry the field "rule" (round-1 wiring bug:
    # helper read rule_id and no caller existed — terra F2-007)
    cats = {rule_to_cat.get(f.get("rule_id") or f.get("rule", ""), "")
            for f in findings if rule_to_cat.get(f.get("rule_id") or f.get("rule", ""))}
    score = readiness_score(dict(sev), categories_checked=cats)
    return score, score_label(score)


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
        "## 🔍 FL4WRITE omnisweep — full-tree audit" + (" (COMPLETE)" if complete else ""),
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
        sev = f.get("sev")
        if sev not in config.severity_vocab:
            continue  # MECE round-3 (glm F3-2): vocab-drifted persisted rows
        if f.get("fix_attempted") or f.get("fix_stale") or config.severity_vocab.index(sev) > sev_floor:
            continue
        from .models import Finding as _Finding

        if not _fix_freshness_gate(primary, config, _Finding(
                rule_id=f["rule"], severity=f["sev"], path=f["path"], line=f["line"],
                category="omnisweep", message=f["msg"])):
            f["fix_stale"] = True  # short-circuits eligibility forever (V3)
            continue
        f["fix_attempted"] = True
        attempts += 1
        report.fix_attempts += 1
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
        status = result.get("status")
        if status == "error":
            # MECE round-6 (M3 stream candidate, desk-verified): a transient
            # error (network/model) marked the finding attempted BEFORE the
            # call, so it was never retried on a later cycle — un-mark it:
            # terminal outcomes (pr_opened/testfail/nofix) stay attempted,
            # transient errors retry (per-cycle cap still bounds the burn)
            f["fix_attempted"] = False
        if status == "pr_opened":
            report.fix_prs_opened += 1
        elif status in ("error", "testfail", "nofix"):
            report.fix_failures += 1
            report._fix_failure_notes.append(f"omni {f['path']}:{f['line']} {status}: {str(result.get('reason'))[:60]}")
        else:
            report.fix_failures += 1
            report._fix_failure_notes.append(f"omni {f['path']}:{f['line']} unknown-status {status!r}")


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
        report.omni_findings = len(st.get("omni_findings", []))  # F5-011
        if not st.get("omni_published"):  # MECE round-5 (sol F5-002): a
            # completed sweep whose issue create/update FAILED must retry the
            # publication — the old fast path returned before the upsert and
            # "retrying next cycle" was a lie
            findings = st.get("omni_findings", [])
            total = int(st.get("omni_total", 0) or 0)
            if findings:
                _omni_upsert_issue(config, primary, st, findings, total, total,
                                   complete=True, report=report)
                if not st.get("omni_published"):
                    return  # publication still failing — retry next cycle
            else:
                st["omni_published"] = True  # clean sweep: nothing to publish
        if config.omnisweep.fix and st.get("omni_findings"):
            _omni_fix_phase(config, primary, st, report)
        return

    tree = primary.list_tree_files(config.repo)
    if tree is None:
        report.alerts.append("omnisweep: tree listing unqueryable (skipped this cycle)")
        return
    if not (isinstance(tree, (tuple, list)) and len(tree) == 2):
        # UltraQA round 3: wrong-shape tree response degrades, never crashes
        report.alerts.append(f"omnisweep: tree listing wrong shape ({type(tree).__name__}, skipped)")
        return
    files, truncated = tree
    if not isinstance(files, list):
        report.alerts.append("omnisweep: tree files not a list (skipped this cycle)")
        return
    if truncated:
        # MECE round-5 (sol F5-007): a known-truncated listing must NEVER
        # render COMPLETE — completion is a correctness claim about the whole
        # tree, and the alert alone used to be followed by omni_complete=True
        report.alerts.append(
            "omnisweep: tree listing TRUNCATED by the forge — completion BLOCKED; "
            "files past the truncation are unaudited (widen caps/excludes or split the repo)")
    # row-shape guard: (path, size) pairs only; one garbage row must not abort
    files = [row for row in files
             if isinstance(row, (tuple, list)) and len(row) == 2
             and isinstance(row[0], str) and isinstance(row[1], int)
             and row[1] >= 0]

    excludes = config.omnisweep.exclude + (config.path_filters or {}).get("ignore", [])
    scan = sorted(
        p for (p, size) in files
        if 0 < size <= _OMNI_MAX_FILE_BYTES
        and not any(fnmatch.fnmatch(p, pat) for pat in excludes)
    )
    total = len(scan)
    scanned_total = int(st.get("omni_scanned_total", 0))
    if total > config.omnisweep.max_total_files:
        # MECE round-2 (terra F2-001): the cap bounds the TREE (one-shot);
        # the old scanned_total+total check double-counted the tree every
        # cycle and aborted large-but-legal sweeps mid-flight
        report.alerts.append(
            f"omnisweep ABORTED: tree has {total} files exceeds "
            f"max_total_files={config.omnisweep.max_total_files} — widen the cap or narrow excludes"
        )
        # MECE round-5 (sol F5-007): an abort is NOT a completion — no
        # omni_complete, nothing publishable; the sweep re-lists and re-alerts
        # each cycle until the cap/excludes are fixed
        st["omni_total"] = total
        report.omni_findings = len(st.get("omni_findings", []))
        return

    cursor = st.get("omni_cursor", "")
    pending = [p for p in scan if p > cursor][: config.omnisweep.max_files_per_cycle]
    if not pending:
        # MECE round-5 (sol F5-001/007): shadow runs and truncated listings
        # must NOT set live completion — completion is a live-publishable,
        # whole-tree claim
        if config.shadow or truncated:
            return
        st["omni_complete"] = True
        st["omni_total"] = total
        findings = st.get("omni_findings", [])
        report.omni_scanned = len(scan)
        report.omni_findings = len(findings)
        _omni_upsert_issue(config, primary, st, findings, len(scan), len(scan), complete=True, report=report)
        if not st.get("omni_published"):
            report.alerts.append("omnisweep: final audit-issue publication failed — retrying next cycle")
            return  # retry via the complete fast path before anything else
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
        try:
            content = primary.get_file(config.repo, path, st.get("omni_head", "") or "HEAD")
        except (ForgeError, ValueError, TypeError, KeyError, AttributeError) as exc:
            # UltraQA round 3: per-file fetch failure skips the file, never
            # aborts the sweep
            report.alerts.append(f"omnisweep: file fetch failed for {path}: {exc}")
            st["omni_cursor"] = path
            continue
        if content is None:
            st["omni_cursor"] = path  # unfetchable files are skipped, not retried forever
            continue
        synth = PullRequest(
            forge=primary.name, number=0, repo=config.repo,
            title=f"omnisweep: {path}", head_sha=st.get("omni_head", "") or "HEAD",
        )
        try:
            doc = analyze(synth, {path}, content, config, mode="file")
            st.setdefault("omni_file_fails", {}).pop(path, None)
        except ModelUnavailable as exc:
            report.model_unavailable += 1
            fails = int(st.setdefault("omni_file_fails", {}).get(path, 0)) + 1
            st["omni_file_fails"][path] = fails
            # A linear tree walk must never LIVeLOCK on one file (live-caught:
            # a file whose review exceeds max_tokens deferred forever, stalling
            # everything behind it). One retry, then skip-and-record.
            if fails >= 2:
                st.setdefault("omni_unscannable", []).append(path)
                st["omni_cursor"] = path
                log.warning("omnisweep: %s unscannable after %d attempts — skipped, recorded", path, fails)
                continue
            log.warning("omnisweep model unavailable at %s (attempt %d): %s", path, fails, exc)
            break  # one retry next cycle, cursor holds
        findings = doc.findings
        if findings:
            findings, dropped, failed_open = gatekeeper.filter_findings(findings, config)
            report.gatekeeper_dropped += dropped
            if failed_open:
                report.gatekeeper_failed += 1
        next_id = int(st.get("omni_next_id", 1))
        for f in findings:
            st.setdefault("omni_findings", []).append({
                "id": next_id, "path": f.path, "line": f.line, "rule": f.rule_id,
                "sev": f.severity, "msg": f.message[:200],  # compact: no proposals in state
                "via": config.model.model,  # route attribution: per-model quality becomes measurable
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
    if done and scanned_this_cycle and not truncated and not config.shadow:
        # finalized in the SAME cycle as the last file — no idle hourly hop.
        # MECE round-5 (sol F5-007/F5-001): a truncated tree or a shadow run
        # never finalizes — completion is a whole-tree, publishable claim
        st["omni_complete"] = True
        st["omni_total"] = total
        unscannable = len(st.get("omni_unscannable", []))
        report.alerts.append(
            f"omnisweep complete: {report.omni_findings} findings across {total} files"
            + (f" ({unscannable} unscannable — model failed twice, skipped + recorded)" if unscannable else "")
        )
        _omni_upsert_issue(
            config, primary, st, st.get("omni_findings", []),
            total, total, complete=True, report=report,
        )
        if not st.get("omni_published"):
            # MECE round-5 (sol F5-002): the completion is recorded but the
            # final publication failed — the next cycle's complete fast path
            # retries the upsert before doing anything else
            report.alerts.append("omnisweep: final audit-issue publication failed — retrying next cycle")
            return
        if config.omnisweep.fix and st.get("omni_findings"):
            _omni_fix_phase(config, primary, st, report)
    else:
        if config.shadow:
            return  # shadow sweeps never touch live progress belts
        if truncated and done and not scanned_this_cycle:
            return  # truncated completion-blocked: retry next cycle, no update
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
    degrades to next-cycle retry, never data loss. On a COMPLETE publish the
    state records omni_published — the retry contract the complete fast path
    honors (MECE round-5, sol F5-002)."""
    if config.shadow or not findings:
        return
    if complete:
        _score, _label = _omni_readiness(findings)
        report.alerts.append(f"omnisweep readiness: {_score}/100 ({_label})")
    body = _omni_report_body(config, findings, scanned, total, complete)
    number = st.get("omni_issue")
    if number:
        if not primary.update_issue(config.repo, number, body):
            report.alerts.append(f"omnisweep: issue #{number} update failed — retrying next cycle")
            return
        if complete:
            st["omni_published"] = True
        return
    created = primary.open_issue(
        config.repo, f"omnisweep: full-tree audit of {config.repo}", body,
    )
    if created is None:
        report.alerts.append("omnisweep: audit-issue creation failed — retrying next cycle")
        return
    st["omni_issue"] = created
    if complete:
        st["omni_published"] = True


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
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        # UltraQA round 2: API shape drift degrades the lane, never crashes
        report.alerts.append(f"retro listing degraded (skipped this cycle): {exc}")
        return set()

    # row-shape guard (UltraQA round 2): one malformed merged row must not
    # abort the sweep
    listed = [p for p in listed if isinstance(p, PullRequest)]

    # MECE round-2 (terra F2-002): JSON persistence turns int keys into
    # strings — the seen-set belt was comparing int numbers against str keys
    # and NEVER excluded (masked by the strict '<' cursor). Normalize here.
    _rs = st.get("retro_seen")
    if not isinstance(_rs, dict):
        _rs = {}  # MECE round-4 (luna F4-003): null/wrong-shape state degrades
    seen: set[int] = {int(k) for k in _rs if str(k).isdigit()}
    # MECE round-5 (sol F5-001): shadow runs keep their own dedupe belt and
    # never touch live cursors/belts — the live cutover must re-audit what
    # shadow only looked at
    shadow_belt: dict[str, str] = {}
    if config.shadow:
        sb = st.get("retro_shadow_seen")
        if isinstance(sb, dict):
            shadow_belt = {str(k): v for k, v in sb.items() if isinstance(v, str)}
    parked = st.get("retro_parked", {})
    if not isinstance(parked, dict):
        parked = {}
    now_i = int(time.time())
    # MECE round-5 (sol F5-009): parked PRs re-arm AUTOMATICALLY after their
    # window — no false "re-arms on the next repo commit" promise, no manual
    # reset needed
    active_park = {int(k) for k, v in parked.items()
                   if str(k).isdigit() and str(v).isdigit() and int(v) > now_i}
    pending = sorted(
        (p for p in listed
         if p.merged_at <= cursor and p.number not in seen
         and p.number not in active_park
         and (not config.shadow or shadow_belt.get(str(p.number)) != p.head_sha)),
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
        st["retro_seen"] = {int(n): True for n in seen}
        if not state.needs_review(st, pr.number, pr.head_sha):
            if not config.shadow:
                oldest_processed = pr.merged_at
            continue  # already reviewed at this SHA while it was open — nothing to catch
        try:
            outcome = _retro_review_pr(
                pr, config, primary, get_diff, shadow_sink, st, report,
            )
        except ForgeError as exc:
            # MECE round-3 (glm F3-1): per-PR containment like post-merge —
            # a forge hiccup defers THIS PR, never crashes the cycle
            report.alerts.append(f"retro #{pr.number}: forge error contained: {exc}")
            seen.discard(pr.number)
            st["retro_seen"] = {int(n): True for n in seen}
            state.save_state(state_path, st)
            break
        if outcome == "shadow":
            shadow_belt[str(pr.number)] = pr.head_sha
            if not config.shadow:
                oldest_processed = pr.merged_at
            continue
        if outcome == "deferred":
            seen.discard(pr.number)  # retry next cycle
            st["retro_seen"] = {n: True for n in seen}
            # MECE round-4 (luna F4-004): consecutive deferrals on one PR burn
            # the lane every cycle while the model/env is down — park after a
            # bounded retry count, surfaced by the alert
            key = f"retro_defer:{pr.number}:{pr.head_sha[:10]}"
            tries = int(st.get(key, 0)) + 1
            st[key] = tries
            if tries >= 3:
                # MECE round-5 (sol F5-009): parked entries carry an expiry —
                # the PR is retried automatically after the window, re-parked
                # only while the deferral cause persists
                st.pop(key, None)
                st["retro_parked"] = {**{str(k): v for k, v in parked.items()},
                                      str(pr.number): int(time.time()) + 86400}
                parked = st["retro_parked"]
                report.alerts.append(
                    f"retro #{pr.number}: deferred {tries}x (model/env) — parked 24h; "
                    "retried automatically after the window")
            state.save_state(state_path, st)  # MECE round-5 (sol F5-003): the
            # corrected seen-set/park state is saved HERE — the old
            # save-before-classification checkpointed the pre-discard seen-set
            # (a kill between the two left the PR permanently skipped)
            break
        oldest_processed = pr.merged_at

    if config.shadow and shadow_belt:
        st["retro_shadow_seen"] = shadow_belt
        while len(st["retro_shadow_seen"]) > 2000:  # bounded belt
            st["retro_shadow_seen"].pop(next(iter(st["retro_shadow_seen"])))
    elif not config.shadow and isinstance(st.get("retro_shadow_seen"), dict):
        st.pop("retro_shadow_seen", None)  # live runs stop honoring the belt
    if oldest_processed:
        st["retro_cursor"] = oldest_processed
    if oldest_processed is None and not pending and not active_park:
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
    dropped_here = 0  # MECE round-4 (luna F4-006): per-PR count for the comment
    if findings and config.gatekeeper:
        findings, dropped, _fo = gatekeeper.filter_findings(findings, config)
        report.gatekeeper_dropped += dropped
        dropped_here = dropped

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
        gatekeeper_dropped=dropped_here or 0,
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
    if not isinstance(queried, (tuple, list)) or len(queried) != 2:
        report.alerts.append("ci_watch: head_check_runs wrong shape (degraded this cycle)")
        return
    head, runs = queried
    if not isinstance(head, str) or not head:
        report.alerts.append("ci_watch: head value unusable (degraded this cycle)")
        return
    if not isinstance(runs, list):
        report.alerts.append("ci_watch: check-runs wrong shape (degraded this cycle)")
        return
    # UltraQA round 3 (P2): check-run fields are forge-external — coerce types
    # so a numeric name or dict conclusion degrades instead of crashing
    # (a dict is unhashable against the benign set).
    failing = []
    for r in runs:
        if not isinstance(r, dict):
            continue
        if r.get("status") != "completed":
            continue
        conclusion = r.get("conclusion")
        if not isinstance(conclusion, str):
            conclusion = "?"
        name = r.get("name")
        if not isinstance(name, str):
            name = "unnamed check"
        run_id = r.get("id")
        if not isinstance(run_id, (str, int)):
            continue  # unusable run identity: skip, never crash (UltraQA P2)
        if conclusion not in _CI_BENIGN:
            failing.append(dict(r, conclusion=conclusion, name=name, id=run_id))
    failing = failing[: config.ci_watch.max_checks]
    if not failing:
        st.pop("ci_red_sha", None)
        return
    report.ci_red_heads += 1
    if st.get(f"ci_acted:{head}"):
        return  # already acted at this SHA — a new commit re-arms the watch
    # MECE round-2 (terra F2-004): acted is set only after a SUCCESSFUL
    # action below; an escalation failure stays un-acted and retries.

    findings: list[Finding] = []
    summaries: list[str] = []
    for run in failing:
        name = run.get("name")
        if not isinstance(name, str):
            name = "unnamed check"
        conclusion = run.get("conclusion") or "?"
        if not isinstance(conclusion, str):
            conclusion = "?"
        out = run.get("output")
        summary = out.get("summary") if isinstance(out, dict) else None
        summary = summary.strip() if isinstance(summary, str) else ""
        # CI check text is forge-external: single-line it before it lands in an
        # escalation body (UltraQA round 2, P2 — annotations/summaries bypass
        # the analyzer, so the scrub that protects posted findings doesn't run)
        summaries.append(f"- **{scrub.inline(name, 60)}** — {scrub.inline(conclusion, 20)}"
                         + (f": {scrub.inline(summary, 300)}" if summary else ""))
        anns = primary.check_annotations(config.repo, run.get("id")) or []
        for a in anns[: config.ci_watch.max_annotations]:
            if not isinstance(a, dict):  # MECE round-4 (luna F4-005): null rows
                continue
            if not a.get("path") or not a.get("message"):
                continue
            try:
                # annotation line is forge-external: non-numeric values must not
                # crash the watch (UltraQA round 2)
                ann_line = int(a.get("start_line") or a.get("line") or 0) or 1
            except (TypeError, ValueError):
                ann_line = 1
            # MECE round-5 (sol F5-008): every annotation field is forge-
            # external — a numeric/object message crashed the slice below
            msg = a.get("message")
            if not isinstance(msg, str):
                msg = str(msg) if msg is not None else ""
            findings.append(
                Finding(
                    rule_id="ci",
                    severity="Major",
                    path=scrub.inline(str(a["path"]), 200),
                    line=ann_line,
                    category="CI",
                    message=scrub.scrub(f"[{scrub.inline(name, 60)}] {msg[:400]}"),
                )
            )

    if findings:
        # GH Actions emits RUN-LEVEL auto-annotations anchored at the workflow
        # dir (path ".github", workflow line numbers — deprecation warnings,
        # step failures). Those are not code findings: the fix lane fetches
        # the anchored path and a directory is unfetchable (live 2026-09-03:
        # every red head burned a fix attempt on ".github"). Mint findings
        # only for paths that are FILES at the red head; None (unqueryable)
        # keeps the finding — fail-open.
        kept: list[Finding] = []
        for f in findings:
            is_file = primary.path_is_file(config.repo, f.path, ref=head)
            if is_file is False:
                log.info("ci_watch: dropped annotation at non-file path %s (run-level meta?)", f.path)
            else:
                kept.append(f)
        findings = kept

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
            if not _fix_freshness_gate(primary, config, f):
                continue
            report.fix_attempts += 1
            result = executor.attempt_fix(synth, f, config)
            status = result.get("status")
            if status == "pr_opened":
                report.ci_fix_prs_opened += 1
            elif status in ("error", "testfail", "nofix"):
                report.fix_failures += 1
                report._fix_failure_notes.append(f"ci@{head[:8]} {status}: {str(result.get('reason'))[:80]}")
                if status == "error":
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
                    "## FL4WRITE CI watch — human action required\n\n"
                    f"Default-branch HEAD `{head}` is red; no automated fix landed.\n\n"
                    f"Failing checks:\n" + "\n".join(summaries) +
                    "\n\n_Findings from annotations:_\n"
                    + ("\n".join(f"- `{renderer.path_display(f.path)}:{f.line}` — {scrub.inline(f.message, 120)}" for f in findings) or "(no file-level annotation findings — run-level/meta annotations only, or none)")
                ),
            )
            report.ci_escalations += 1
            st[f"ci_acted:{head}"] = True
        except Exception as exc:  # noqa: BLE001 — escalation must not kill the cycle
            report.alerts.append(f"ci_watch escalation failed for {config.repo}: {exc}")
    elif opened:
        st[f"ci_acted:{head}"] = True
    else:
        # no fix opened and no escalation channel (or shadow): acting again
        # next cycle changes nothing — mark acted to keep the red-head count
        # honest (one summon per SHA)
        st[f"ci_acted:{head}"] = True


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

            listing_failed = False
            try:
                prs = primary.list_open_prs(config.repo)
            except ForgeError as exc:
                listing_failed = True
                report.alerts.append(f"primary unreachable: {exc}")
                log.warning("primary unreachable for %s: %s", config.repo, exc)
                prs = []
            except (ValueError, TypeError, KeyError, AttributeError) as exc:
                # UltraQA round 2: a forge API SHAPE change (rows missing
                # fields, unexpected types) is an external-surface failure,
                # not a bug in the cycle — degrade this lane, never crash it.
                listing_failed = True
                report.alerts.append(f"primary list_open_prs degraded: {exc}")
                log.warning("list_open_prs shape failure for %s (degraded): %s", config.repo, exc)
                prs = []

            # Adapter contract guard: garbage rows (None, dicts, strings from a
            # half-parsed API) are dropped with an alert — one bad row must not
            # crash the cycle (UltraQA round 2, ENG-garbage-rows).
            if not all(isinstance(p, PullRequest) for p in prs):
                dropped_rows = sum(1 for p in prs if not isinstance(p, PullRequest))
                report.alerts.append(f"primary returned {dropped_rows} malformed PR rows (dropped)")
                log.warning("dropped %d malformed PR rows for %s", dropped_rows, config.repo)
                prs = [p for p in prs if isinstance(p, PullRequest)]

            open_numbers = set()
            truncated_by_deadline = False
            for pr in prs:
                open_numbers.add(pr.number)
                report.scanned += 1
                if deadline is not None and (deadline - time.monotonic()) < REVIEW_BUDGET_S:
                    truncated_by_deadline = True
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
                    _review_pr(pr, config, primary, get_diff, shadow_sink, st, report, run_fixes,
                               deadline=deadline)
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

            # MECE round-4 (luna F4-002): never prune on a listing FAILURE or
            # deadline truncation — empty open_numbers would delete every
            # per-PR record as if the PRs had closed (re-review storms + lost
            # fix-depth/model-failure state on the next healthy cycle)
            if not listing_failed and not truncated_by_deadline:
                state.prune_closed(st, open_numbers | merged_keep)

            if run_issues and config.issues_enabled:
                from . import issues as issues_lane

                issue_summary = issues_lane.run_issues_cycle(config, st, primary)
                report.issues_triaged = issue_summary.get("triaged", 0)

            if not config.shadow:
                from . import metrics

                report.acceptance = metrics.acceptance_snapshot(primary, config)

            if report.fix_failures:
                # ONE summarizing alert per cycle (V2) — alert fatigue is a
                # named org incident class; never one line per finding
                report.alerts.append(
                    f"fix failures: {report.fix_failures} — " + "; ".join(getattr(report, "_fix_failure_notes", [])[:5])
                )
            state.save_state(state_path, st)
    except CycleLockHeld as exc:
        log.warning("cycle lock held — skipping this cycle (never double-post): %s", exc)
        report.alerts.append(f"LOCK HELD: {exc}")
        report.scanned = 0
    except state.StateIOError as exc:
        report.alerts.append(str(exc))
    return report
