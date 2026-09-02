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
    "are posted to a PR. Your job is to KILL findings that will be ignored. "
    'Reply ONLY with JSON: {"keep": [{"path": str, "line": int, "reason": str}]} '
    "— only the findings worth a developer's attention. Kill nits, style "
    "comments, anything a senior dev would dismiss. Keep only findings that "
    "would block a merge or cause a production incident. The keep entries must "
    "copy path and line EXACTLY as given."
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
