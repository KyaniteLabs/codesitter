"""CheckYourself integration — the 19-capability production-hardening scaffold.

Sourced from KyaniteLabs/checkyourself (the org's own production-readiness
system): each capability is a structured review rule with the grounding
contract FL4WRITE already enforces (rule_id must exist in config.review).
This replaces the 3-4 generic rules most configs shipped with — coverage
becomes a PARTITION (every capability either fires or is N/A), not vibes.

The P0-P3 risk taxonomy maps onto FL4WRITE's severity vocab:
  P0 (don't ship) -> Critical
  P1 (serious before launch) -> Major
  P2 (important hardening) -> Minor
  P3 (improvement) -> Nit

Scoring: the readiness score is the weighted category sum with CheckYourself's
cap system — any P0 caps at 49, any P1 caps at 74, missing evidence in a
critical category caps at 84.
"""

from __future__ import annotations

# The 19 capabilities (CheckYourself 90_ADVANCED/capabilities), each as
# (rule_id, category, weight, prose_law) — the analyzer grounds findings
# against rule_ids; the scorer aggregates by category
CAPABILITIES = [
    # rule_id, category, weight, prose_law
    ("spec-delivery", "Frontend & Delivery", 8,
     "Requirements are traceable to implementation; acceptance criteria exist for core flows."),
    ("frontend-ux", "Frontend & Delivery", 8,
     "Client-side validation mirrors server-side; loading/error states handled; no client-only security."),
    ("api-services", "API & Services", 10,
     "Routes validate inputs server-side; uploads bounded; webhooks verified; business rules enforced."),
    ("data-storage", "Data & Storage", 18,
     "Schema has constraints; migrations are reversible; backup evidence exists; seed data is safe."),
    ("auth-permissions", "Auth & Access", 14,
     "Authentication is server-side; authorization checks on every protected path; sessions managed."),
    ("tenant-isolation", "Data & Storage", 18,
     "User/tenant data is isolated at the query layer; cache keys are tenant-scoped; exports respect boundaries."),
    ("security-threat", "Security & Privacy", 18,
     "Injection, XSS, CSRF, SSRF, path traversal are mitigated; dependencies scanned; no unsafe deserialization."),
    ("secrets-config", "Secrets & Config", 10,
     "Secrets never in code or client bundles; env examples exist; config drift between environments is managed."),
    ("testing-quality", "Testing & Quality", 10,
     "Core logic has tests; dangerous paths (auth, payments, writes, isolation) are tested; CI runs them."),
    ("ci-cd-supply", "CI & Deployment", 8,
     "Dependencies pinned; lockfile present; CI checks on PR; deploy process documented."),
    ("hosting-release", "CI & Deployment", 8,
     "Rollback plan exists; environments separated; prod secrets not in dev."),
    ("infra-iac", "CI & Deployment", 8,
     "Infrastructure is code-reviewed; no public-by-default resources; IAM is scoped."),
    ("perf-caching", "Performance & Scale", 8,
     "Rate limits on abuse-prone endpoints; queries indexed; cache is correct and bounded."),
    ("scaling-resilience", "Performance & Scale", 8,
     "No single point of failure; retries have backoff; graceful degradation under load."),
    ("observability", "Operations", 8,
     "Structured logs exist; errors are tracked; someone is alerted; a runbook exists."),
    ("availability-recovery", "Operations", 8,
     "Backups are tested; recovery time is understood; data loss window is known."),
    ("ai-governance", "AI & Governance", 6,
     "AI/agent behavior is bounded; prompts don't leak secrets; outputs are validated before use."),
    ("privacy-compliance", "Security & Privacy", 18,
     "PII collection is minimized and documented; deletion paths exist; consent tracked."),
    ("production-readiness", "Overall", 10,
     "The app can handle real users without data loss, security breach, or unrecoverable outage."),
]

CATEGORY_WEIGHTS: dict[str, int] = {}
for _, cat, w, _ in CAPABILITIES:
    CATEGORY_WEIGHTS[cat] = CATEGORY_WEIGHTS.get(cat, 0) + w

# P0-P3 risk taxonomy mapped to FL4WRITE severities
RISK_SEVERITY_MAP = {
    "P0": "Critical",  # don't ship
    "P1": "Major",     # serious before launch
    "P2": "Minor",     # important hardening gap
    "P3": "Nit",       # improvement
}

# Category weights for the readiness score (CheckYourself scoring-method.md)
SCORING_CATEGORIES = {
    "Data & Storage": 18,
    "Auth & Access": 14,
    "Secrets & Config": 10,
    "API & Services": 10,
    "Testing & Quality": 10,
    "CI & Deployment": 8,
    "Operations": 8,
    "Performance & Scale": 8,
    "Frontend & Delivery": 8,
    "Security & Privacy": 18,
    "AI & Governance": 6,
    "Overall": 10,
}

# Caps (CheckYourself scoring-method.md)
CAP_P0 = 49
CAP_P1 = 74
CAP_MISSING_CRITICAL = 84


def default_review_rules() -> dict[str, str]:
    """The 19 capabilities as FL4WRITE review rules (rule_id -> prose law)."""
    return {rid: law for rid, _, _, law in CAPABILITIES}


def readiness_score(findings_by_severity: dict[str, int],
                    categories_checked: set[str] | None = None) -> int:
    """0-100 production-readiness score. Starts at 100; deducts per finding;
    applies CheckYourself caps.

    findings_by_severity: {"Critical": n, "Major": n, "Minor": n, "Nit": n}
    categories_checked: which capability categories had evidence (for the
    missing-evidence cap).
    """
    score = 100
    crit = findings_by_severity.get("Critical", 0)
    major = findings_by_severity.get("Major", 0)
    minor = findings_by_severity.get("Minor", 0)
    nit = findings_by_severity.get("Nit", 0)

    # deduct per finding (diminishing — the first few findings matter most)
    score -= min(crit * 15, 40)
    score -= min(major * 8, 25)
    score -= min(minor * 2, 15)
    score -= min(nit, 5)

    # CheckYourself caps
    if crit > 0:
        score = min(score, CAP_P0)
    if major > 0:
        score = min(score, CAP_P1)

    # missing evidence in critical categories
    critical_cats = {"Data & Storage", "Auth & Access", "Secrets & Config", "Testing & Quality"}
    if categories_checked is not None and not (critical_cats & categories_checked):
        score = min(score, CAP_MISSING_CRITICAL)

    return max(0, min(100, score))


def score_label(score: int) -> str:
    if score >= 90:
        return "HIGH — credible evidence across critical surfaces"
    if score >= 75:
        return "MEDIUM — some gaps, but core is covered"
    if score >= 50:
        return "LOW — significant hardening needed"
    return "CRITICAL — do not ship"
