"""L1-B4/L1-B5 severity-integrity gates (2026-09-03 adjudication sample).

Pins the two defect classes the council consult (CTO + CS, liminal post-merge
window) found in the analyzer: self-contradictory bodies posted at failure
severity, and testing-quality Criticals that claim no verifiable failing test.
Every escape from the sample window has a regression here.
"""

from __future__ import annotations

import json

from fl4write import config as cfg
from fl4write.analyzer import analyze
from fl4write.models import PullRequest

RAW = {
    "repo": "KyaniteLabs/fl4write",
    "forges": {
        "github": {
            "role": "primary", "api_base": "https://api.github.com", "token_env": "GHT",
        }
    },
    "model": {"endpoint": "http://model/v1", "model": "test", "key_env": "MK"},
    "review": {"secrets": "never commit secrets",
               "testing-quality": "core logic has tests",
               "security-threat": "mitigations verified"},
    "severity_vocab": ["Critical", "Major", "Minor", "Nit"],
    "shadow": False,
    "ci_watch": {"enabled": True},
    "fix": {"enabled": True, "merge_own_prs": False},
}


def make_config(**over):
    raw = dict(RAW)
    raw.update(over)
    return cfg.RepoConfig.model_validate(raw)


def _analyze(monkeypatch, item, config=None):
    monkeypatch.setattr(
        "fl4write.analyzer._call_model",
        lambda route, prompt, mode="pr", system=None, **kw: json.dumps({"findings": [item]}),
    )
    return analyze(
        PullRequest(forge="github", number=1, repo="o/r", head_sha="a" * 40),
        {item["path"]}, "diff content " + item["path"], config or make_config(),
    )


class TestSelfContradictionGate:
    """L1-B4: a body that concludes "passes / no issue / no failure" refutes its
    own finding — sample items 2, 3, 6, 9 (liminal #1114/#1115/#1116/#1117,
    posted Critical with "tests pass. No issue." bodies)."""

    def test_late_self_contradiction_dropped(self, monkeypatch):
        # sample item 3: the contradiction sits past char 120 (the old guard's
        # entire scan window) and the old phrase list never covered "passes".
        item = {
            "rule_id": "testing-quality", "severity": "Critical", "path": "t.test.ts",
            "line": 163, "category": "c",
            "message": ("The test attempts to mutate the length property and expects it to throw. "
                        "However, in strict mode it throws synchronously, so the test should pass. "
                        "But the rows are frozen via Object.freeze. So the test passes. No issue."),
        }
        doc = _analyze(monkeypatch, item)
        assert doc.findings == [] and doc.digest["_dropped_ungrounded"] >= 1

    def test_no_failing_test_found_dropped(self, monkeypatch):
        # sample item 2: "…which matches. So tests pass. No failing test found."
        item = {
            "rule_id": "testing-quality", "severity": "Critical", "path": "t.test.ts",
            "line": 42, "category": "c",
            "message": ("The regex matches the array entries which matches the expected array. "
                        "So tests pass. No failing test found. No change needed; tests pass."),
        }
        doc = _analyze(monkeypatch, item)
        assert doc.findings == []

    def test_assertion_is_correct_dropped(self, monkeypatch):
        # sample item 9: "…but those are separate instances. The assertion is
        # correct. No failure." — contradiction after the last contrast marker.
        item = {
            "rule_id": "testing-quality", "severity": "Critical", "path": "o.test.ts",
            "line": 53, "category": "c",
            "message": ("However, the test also creates other organs, but those are separate "
                        "instances and do not affect the first organ's stats. The assertion is "
                        "correct. No failure."),
        }
        doc = _analyze(monkeypatch, item)
        assert doc.findings == []

    def test_not_a_failure_after_but_dropped(self, monkeypatch):
        # sample item 6: "…the test would pass, but it is misleading… but not a
        # failure." posted Critical.
        item = {
            "rule_id": "testing-quality", "severity": "Critical", "path": "v.test.ts",
            "line": 162, "category": "c",
            "message": ("While this test expects no digests, it does not actually test the "
                        "scenario because the HTML is not a realistic page. However, the test "
                        "would pass, but it is misleading. This is a test quality issue but not "
                        "a failure."),
        }
        doc = _analyze(monkeypatch, item)
        assert doc.findings == []

    def test_legit_contrastive_claim_survives_contradiction_gate(self, monkeypatch):
        # sample item 14: "The PR claims 149 tests pass, but the diff does not
        # include any test changes." — the pass claim precedes the finding's
        # contrast clause: NOT self-contradicting; the ceiling gate then handles
        # its severity.
        item = {
            "rule_id": "testing-quality", "severity": "Critical", "path": "h.ts",
            "line": 604, "category": "c",
            "message": ("The PR claims 149 tests pass, but the diff does not include any test "
                        "changes. The new function is not covered by tests in this diff."),
        }
        doc = _analyze(monkeypatch, item)
        assert len(doc.findings) == 1
        assert doc.findings[0].severity == "Major"  # L1-B5 ceiling applies

    def test_major_self_contradiction_also_dropped(self, monkeypatch):
        item = {
            "rule_id": "security-threat", "severity": "Major", "path": "s.py",
            "line": 10, "category": "c",
            "message": "The endpoint is validated server-side. No issue here really.",
        }
        doc = _analyze(monkeypatch, item)
        assert doc.findings == []

    def test_old_head_guard_behavior_kept(self, monkeypatch):
        # the pre-existing head-120 3-phrase guard (no contrast markers needed)
        item = {
            "rule_id": "secrets", "severity": "Major", "path": "x.py", "line": 4,
            "category": "c",
            "message": "The totals MATCH and this IS CONSISTENT. No issue here really",
        }
        doc = _analyze(monkeypatch, item)
        assert doc.findings == []

    def test_clean_anchored_finding_survives(self, monkeypatch):
        item = {
            "rule_id": "secrets", "severity": "Critical", "path": "x.py", "line": 4,
            "category": "c",
            "message": "live problem found: token prefix ghp_abc leaks via logs",
        }
        doc = _analyze(monkeypatch, item)
        assert len(doc.findings) == 1


class TestTestingQualityCeiling:
    """L1-B5: a testing-quality Critical requires a failure claim AND a runnable
    per-repo test_cmd — otherwise it is a coverage note at Major (rubric:
    Critical = verifiable failing diff test). Sample items 14, 20."""

    def test_coverage_gap_demoted_without_test_cmd(self, monkeypatch):
        item = {
            "rule_id": "testing-quality", "severity": "Critical", "path": "h.ts",
            "line": 358, "category": "c",
            "message": ("The diff adds a new code path (the shim) but includes no tests. "
                        "Without a test the shim could regress silently and the claim of "
                        "correctness is unsubstantiated."),
        }
        doc = _analyze(monkeypatch, item, config=make_config())
        assert len(doc.findings) == 1
        assert doc.findings[0].severity == "Major"

    def test_failure_claim_without_test_cmd_demoted(self, monkeypatch):
        # even an explicit "would fail" claim is unverifiable when the bot cannot
        # run the repo's tests (no test_cmd) — stays Major until the engine
        # proves it (post-merge CI green contradicts "test fails" claims anyway).
        item = {
            "rule_id": "testing-quality", "severity": "Critical", "path": "v.test.ts",
            "line": 134, "category": "c",
            "message": ("The test feeds escaped markup so no inlining happens and the digests "
                        "would be empty, causing the test to fail; it expects 2 digests."),
        }
        doc = _analyze(monkeypatch, item, config=make_config())
        assert len(doc.findings) == 1
        assert doc.findings[0].severity == "Major"

    def test_failure_claim_with_test_cmd_kept_critical(self, monkeypatch):
        item = {
            "rule_id": "testing-quality", "severity": "Critical", "path": "t.py",
            "line": 12, "category": "c",
            "message": ("The diff's own test test_x.py fails against the changed code: the "
                        "assertion at line 12 breaks."),
        }
        doc = _analyze(monkeypatch, item,
                       config=make_config(test_cmd="python3 -m pytest tests/"))
        assert len(doc.findings) == 1
        assert doc.findings[0].severity == "Critical"

    def test_non_testing_rules_unaffected(self, monkeypatch):
        item = {
            "rule_id": "security-threat", "severity": "Critical", "path": "s.py",
            "line": 10, "category": "c",
            "message": "verifiable exploit: unsanitized input reaches exec()",
        }
        doc = _analyze(monkeypatch, item, config=make_config())
        assert len(doc.findings) == 1
        assert doc.findings[0].severity == "Critical"


class TestSolAuditPins:
    """Regressions from the Sol delegate audit (2026-09-03, GO-WITH-CHANGES):
    no false drops on contextual pass-phrases; anchored failure wording."""

    def test_contextual_pass_phrase_is_not_contradiction(self, monkeypatch):
        # "the test passes a mutable config to the helper" — pass as verb with
        # an object, not a terminal conclusion. Audit example (c).
        item = {
            "rule_id": "security-threat", "severity": "Critical", "path": "h.py",
            "line": 9, "category": "c",
            "message": "The test passes a mutable config to the helper, mutating "
                       "shared state across runs and leaking the token.",
        }
        doc = _analyze(monkeypatch, item)
        assert len(doc.findings) == 1

    def test_would_pass_locally_with_real_defect_survives(self, monkeypatch):
        # audit example (a): CI-skipped test context is not self-refutation.
        item = {
            "rule_id": "testing-quality", "severity": "Critical", "path": "t.py",
            "line": 5, "category": "c",
            "message": ("The new test is skipped in CI, so the suite reports green "
                        "while the path stays dead. The test would pass locally, but "
                        "CI never runs it: skip marker hides the failure."),
        }
        doc = _analyze(monkeypatch, item,
                       config=make_config(test_cmd="python3 -m pytest tests/"))
        # survives the contradiction gate; ceiling keeps Critical (explicit
        # failure claim + runnable test_cmd)
        assert len(doc.findings) == 1
        assert doc.findings[0].severity == "Critical"

    def test_fixture_should_pass_only_because_survives(self, monkeypatch):
        # audit example (b): "should pass only because…" states the defect.
        item = {
            "rule_id": "testing-quality", "severity": "Major", "path": "f.py",
            "line": 8, "category": "c",
            "message": ("The fixture test should pass only because the filesystem is "
                        "case-insensitive; the same assertion breaks on Linux CI."),
        }
        doc = _analyze(monkeypatch, item)
        assert len(doc.findings) == 1

    def test_expects_receives_without_marker_demoted(self, monkeypatch):
        # audit example: "expects 2, receives 0" carries no failure word — the
        # ceiling cannot treat it as a verified failure claim without test_cmd.
        item = {
            "rule_id": "testing-quality", "severity": "Critical", "path": "v.test.ts",
            "line": 134, "category": "c",
            "message": "The test expects 2 digests but the implementation reports 0 "
                       "for escaped markup, so the assertion cannot hold.",
        }
        doc = _analyze(monkeypatch, item, config=make_config())
        assert len(doc.findings) == 1
        assert doc.findings[0].severity == "Major"

    def test_coverage_only_critical_with_test_cmd_still_demoted(self, monkeypatch):
        # even with a runnable test_cmd, a coverage-only claim ("could regress
        # silently", no failure wording) is not a Critical. Sample item 20.
        item = {
            "rule_id": "testing-quality", "severity": "Critical", "path": "h.ts",
            "line": 358, "category": "c",
            "message": ("The diff adds a new code path but includes no tests; without "
                        "a test the shim could regress silently and the claim of "
                        "correctness is unsubstantiated."),
        }
        doc = _analyze(monkeypatch, item, config=make_config(test_cmd="pnpm vitest run"))
        assert len(doc.findings) == 1
        assert doc.findings[0].severity == "Major"

    def test_unicode_and_empty_messages_safe(self, monkeypatch):
        item = {
            "rule_id": "general", "severity": "Minor", "path": "café/☃/x.py", "line": 1,
            "category": "c",
            "message": "Le champ café ☃ souffre d'un problème réel d'encodage émoji.",
        }
        doc = _analyze(monkeypatch, item)
        assert len(doc.findings) == 1
        item2 = dict(item, message="")
        doc2 = _analyze(monkeypatch, item2)
        assert len(doc2.findings) == 1  # empty message is not self-contradicting
