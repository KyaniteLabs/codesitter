"""Gatekeeper — the nit-killer second pass.

Runs between the analyzer and the poster. Takes the findings list, asks the
model (with a staff-engineer persona) which findings are WORTH POSTING vs
which are noise/nits that will be ignored. Drops the noise before it becomes
comment fatigue. Implements the Greptile lesson: 79% nits = 19% address rate;
filtered = 55%+.

The gatekeeper NEVER escalates severity or adds findings — it only filters.
Config: `gatekeeper: false` in the repo config disables the pass entirely
(the engine reads the flag).

Audit 2026-09-01 hardening:
- FAIL-OPEN IS REAL NOW: any exception class (HTTPError, URLError, timeout,
  RuntimeError, TypeError...) returns all findings. The old tuple missed the
  most common failure classes and CRASHED the whole cycle, losing its state.
- The keep-list is validated: lines coerced to int, paths stripped. An empty
  or unparseable keep-set while findings exist = parse failure = fail-open —
  never "drop everything and post 🎉 over real findings".
- Dropped findings are logged WITH identity (path:line, rule, message head) —
  the 21-dropped-unknown incident made tuning blind.
- The org-law addendum rides the same system prompt as the analyzer.
"""

from __future__ import annotations

import logging

from .analyzer import _call_model
from .config import RepoConfig
from .models import Finding

log = logging.getLogger("fl4write.gatekeeper")

_GATEKEEPER_SYSTEM = (
    "You are a staff engineer reviewing a code reviewer's findings before they "
    "are posted to a PR. Your job is to KILL findings that will be ignored and "
    "DEMOTE findings that are real but over-ranked. "
    'Reply ONLY with JSON: {"keep": [{"path": str, "line": int, "reason": str}], '
    '"demote": [{"path": str, "line": int, "severity": str, "reason": str}]} '
    "— keep ONLY findings worth a developer's attention (kill nits, style "
    "comments, anything a senior dev would dismiss). demote entries may ONLY "
    "lower a severity (never raise); use the provided severity vocabulary. "
    "Both lists copy path and line EXACTLY as given."
)


def _keep_set(parsed: object) -> set[tuple[str, int]] | None:
    """Validated (path, line) set, or None when unparseable/unusable."""
    if not isinstance(parsed, dict):
        return None
    keep = parsed.get("keep")
    if not isinstance(keep, list):
        return None
    out: set[tuple[str, int]] = set()
    for k in keep:
        if not isinstance(k, dict):
            continue
        try:
            out.add((str(k.get("path", "")).strip(), int(k.get("line"))))
        except (TypeError, ValueError):
            continue
    return out


def _demotions(parsed: dict, severity_vocab: list[str]) -> dict[tuple[str, int, str], str]:
    """Valid {(path, line, rule_id): lower_severity} — demotion may only
    LOWER, target must be in the vocab, and the key includes rule_id so two
    findings sharing a line are not both demoted (Sol#3: (path,line) alone
    mutated the unrequested sibling)."""
    out: dict[tuple[str, int, str], str] = {}
    for d in parsed.get("demote") or []:
        if not isinstance(d, dict):
            continue
        try:
            key = (str(d.get("path", "")).strip(), int(d.get("line")), str(d.get("rule_id", "")))
        except (TypeError, ValueError):
            continue
        target = str(d.get("severity", ""))
        if target not in severity_vocab:
            continue
        out[key] = target
    return out


def filter_findings(findings: list[Finding], config: RepoConfig) -> tuple[list[Finding], int, bool]:
    """Gatekeeper pass: returns (kept_findings, dropped_count, failed_open).

    On ANY model/parse failure, returns all findings unfiltered with
    failed_open=True (never block posting because the filter is down — but
    the caller COUNTS it: an always-failing filter is a silent no-op, the
    850x/sweep lesson). An empty keep-set against a non-empty findings list
    is treated as a parse failure, not as "drop everything".
    """
    if not findings:
        return findings, 0, False

    finding_list = "\n".join(
        f"- [{f.severity}] {f.path}:{f.line} ({f.rule_id}): {f.message[:120]}" for f in findings
    )
    prompt = f"REPO SEVERITY VOCAB: {config.severity_vocab}\nFINDINGS TO FILTER:\n{finding_list}\nJSON keep list:"

    from .law import SYSTEM_PROMPT_ADDENDUM

    try:
        # The gatekeeper MUST send ITS OWN contract — routing through the
        # analyzer's default system prompt made the model reply {"findings":
        # [...]} to a keep-list ask, unusable, fail-open, 850x/sweep: the nit
        # filter had never filtered anything (live-caught 2026-09-01).
        response = _call_model(
            config.model, prompt,
            system=_GATEKEEPER_SYSTEM + "\n\n" + SYSTEM_PROMPT_ADDENDUM,
        )
        from .analyzer import extract_json

        parsed = extract_json(response, envelope_key="keep")
        keep_set = _keep_set(parsed)
        if keep_set is None:
            raise ValueError(f"keep-list unusable: {str(parsed)[:120]}")
        kept = [f for f in findings if (f.path, f.line) in keep_set]
        if not kept:
            # "Model says drop ALL" and "model returned garbage" are
            # indistinguishable — refuse the destructive read, fail open.
            raise ValueError("keep-list matched zero findings; refusing drop-all as parse failure")
        # L2: demotions apply ONLY to kept findings and only DOWNWARD
        demote = _demotions(parsed, config.severity_vocab)
        demoted_ids = []
        # MECE round-1 (terra F1-021): the applied set is keyed by
        # (path, line, rule_id) — two findings on one line under different
        # rules must each get their own requested demotion
        applied: set = set()
        for f in kept:
            key3 = (f.path, f.line, f.rule_id)
            target = demote.get(key3)
            if target is None:
                # (path,line) match WITHOUT rule match is ambiguous (Sol#3):
                # only apply when exactly one finding holds that line
                same_line = [g for g in kept if (g.path, g.line) == (f.path, f.line)]
                if len(same_line) == 1 and (f.path, f.line) not in {(p, l) for p, l, _ in applied}:
                    target = next((v for (p, ln, r), v in demote.items()
                                   if (p, ln) == (f.path, f.line)), None)
            if key3 in applied:
                continue
            if target and config.severity_vocab.index(target) > config.severity_vocab.index(f.severity):
                log.info("gatekeeper demoted %s:%s (%s) %s->%s", f.path, f.line, f.rule_id, f.severity, target)
                demoted_ids.append(f"{f.path}:{f.line} ({f.rule_id}) {f.severity}->{target}")
                f.severity = target
                applied.add(key3)
        from . import telemetry as _tel
        _tel.emit("gatekeeper", repo=config.repo, kept=len(kept),
                  dropped=len(findings) - len(kept), demoted=demoted_ids)
        for f in findings:
            if (f.path, f.line) not in keep_set:
                log.info("gatekeeper dropped: %s:%s (%s) %s", f.path, f.line, f.rule_id, f.message[:60])
        dropped = len(findings) - len(kept)
        if dropped:
            log.info("gatekeeper dropped %d/%d findings (nit filter)", dropped, len(findings))
        return kept, dropped, False
    except Exception as exc:  # fail-open is the contract, for ALL failure classes

        log.warning("gatekeeper unavailable (fail-open, posting all): %s", exc)
        return findings, 0, True
