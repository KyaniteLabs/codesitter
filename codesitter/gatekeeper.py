"""Gatekeeper — the nit-killer second pass.

Runs between the analyzer and the poster. Takes the findings list, asks the
model (with a staff-engineer persona) which findings are WORTH POSTING vs
which are noise/nits that will be ignored. Drops the noise before it becomes
comment fatigue. Implements the Greptile lesson: 79% nits = 19% address rate;
filtered = 55%+.

The gatekeeper NEVER escalates severity or adds findings — it only filters.
Config: `gatekeeper: enabled` in the repo config.
"""

from __future__ import annotations

import json
import logging

from .analyzer import ModelUnavailable, _call_model
from .config import RepoConfig
from .models import Finding

log = logging.getLogger("codesitter.gatekeeper")

_GATEKEEPER_SYSTEM = (
    "You are a staff engineer reviewing a code reviewer's findings before they "
    "are posted to a PR. Your job is to KILL findings that will be ignored. "
    'Reply ONLY with JSON: {"keep": [{"path": str, "line": int, "reason": str}]} '
    "— only the findings worth a developer's attention. Kill nits, style "
    "comments, anything a senior dev would dismiss. Keep only findings that "
    "would block a merge or cause a production incident."
)


def filter_findings(findings: list[Finding], config: RepoConfig) -> tuple[list[Finding], int]:
    """Gatekeeper pass: returns (kept_findings, dropped_count).

    On model failure, returns all findings unfiltered (fail-open: never block
    posting because the filter is down — but log it).
    """
    if not findings:
        return findings, 0

    finding_list = "\n".join(f"- [{f.severity}] {f.path}:{f.line} ({f.rule_id}): {f.message[:120]}" for f in findings)
    prompt = f"REPO SEVERITY VOCAB: {config.severity_vocab}\nFINDINGS TO FILTER:\n{finding_list}\nJSON keep list:"

    try:
        response = _call_model(config.model, prompt)
        parsed = json.loads(response[response.index("{") : response.rindex("}") + 1])
        keep_set = {(k["path"], k["line"]) for k in parsed.get("keep", []) if isinstance(k, dict)}
        kept = [f for f in findings if (f.path, f.line) in keep_set]
        dropped = len(findings) - len(kept)
        if dropped:
            log.info("gatekeeper dropped %d/%d findings (nit filter)", dropped, len(findings))
        return kept, dropped
    except (ModelUnavailable, ValueError, json.JSONDecodeError, KeyError) as exc:
        log.warning("gatekeeper unavailable (fail-open, posting all): %s", exc)
        return findings, 0
