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
    '"demote": [{"path": str, "line": int, "rule_id": str, "severity": str, "reason": str}]} '
    "— keep ONLY findings worth a developer's attention (kill nits, style "
    "comments, anything a senior dev would dismiss). demote entries may ONLY "
    "lower a severity (never raise); use the provided severity vocabulary, "
    "and copy path, line AND rule_id EXACTLY as given (rule_id disambiguates "
    "findings that share a line)."
)


def _keep_sets(parsed: object) -> tuple[set[tuple[str, int]], dict[tuple[str, int], set[str]]] | None:
    """((line-only keep keys), {(path,line): {rule_id}}) or None when
    unparseable/unusable. MECE round-5 (glm F5-A02): rows that copy rule_id
    disambiguate same-line findings — keeping one sibling must NOT auto-keep
    the other (mirror of the Sol#3 demote-side fix); rows without rule_id
    keep the whole line (legacy-model behavior)."""
    if not isinstance(parsed, dict):
        return None
    keep = parsed.get("keep")
    if not isinstance(keep, list):
        return None
    line_only: set[tuple[str, int]] = set()
    by_rule: dict[tuple[str, int], set[str]] = {}
    for k in keep:
        if not isinstance(k, dict):
            continue
        try:
            pl = (str(k.get("path", "")).strip(), int(k.get("line")))
        except (TypeError, ValueError):
            continue
        rule = str(k.get("rule_id", "")).strip()
        if rule:
            by_rule.setdefault(pl, set()).add(rule)
        else:
            line_only.add(pl)
    return line_only, by_rule


def _keep_set(parsed: object) -> set[tuple[str, int]] | None:
    """Legacy (path, line) view used by callers that only need membership
    presence (drop logging); the authoritative matcher is filter_findings."""
    both = _keep_sets(parsed)
    if both is None:
        return None
    line_only, by_rule = both
    return line_only | set(by_rule)


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
        keep_sets = _keep_sets(parsed)
        if keep_sets is None:
            raise ValueError(f"keep-list unusable: {str(parsed)[:120]}")
        line_only, by_rule = keep_sets
        # MECE round-5 (glm F5-A02): rule-keyed rows disambiguate same-line
        # findings; a (path,line) row keeps the whole line; when every row at
        # a line carries a rule that matches NO finding, the single finding on
        # that line is kept (mirror of the demote-side ambiguity fallback)
        at_line: dict[tuple[str, int], list[Finding]] = {}
        for f in findings:
            at_line.setdefault((f.path, f.line), []).append(f)

        def _kept(f: Finding) -> bool:
            pl = (f.path, f.line)
            if pl in line_only:
                return True
            rules = by_rule.get(pl)
            if rules is None:
                return False
            if f.rule_id in rules:
                return True
            same_line = at_line.get(pl, [])
            # single finding at the line but the model's rule copy doesn't
            # match it: ambiguous, treat as a keep (no sibling to protect)
            return len(same_line) == 1

        kept = [f for f in findings if _kept(f)]
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
                if len(same_line) == 1 and (f.path, f.line) not in {(p, ln0) for p, ln0, _ in applied}:
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
        kept_ids = {id(f) for f in kept}
        for f in findings:
            if id(f) not in kept_ids:
                log.info("gatekeeper dropped: %s:%s (%s) %s", f.path, f.line, f.rule_id, f.message[:60])
        dropped = len(findings) - len(kept)
        if dropped:
            log.info("gatekeeper dropped %d/%d findings (nit filter)", dropped, len(findings))
        return kept, dropped, False
    except Exception as exc:  # fail-open is the contract, for ALL failure classes

        log.warning("gatekeeper unavailable (fail-open, posting all): %s", exc)
        return findings, 0, True
