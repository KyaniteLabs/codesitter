"""Restart and remote-identity regressions reproduced by the fresh audit."""

import json
from types import SimpleNamespace

import pytest

from fl4write import engine, executor, issues, state
from fl4write.config import RepoConfig


def config():
    return RepoConfig.model_validate({
        "repo": "owner/project",
        "forges": {"github": {"role": "primary", "api_base": "https://api.github.com",
                               "token_env": "TEST_FORGE_KEY"}},
        "model": {"endpoint": "http://model.invalid/v1", "model": "test",
                  "key_env": "TEST_MODEL_KEY"},
        "omnisweep": {"enabled": True, "fix": True, "fix_min_severity": "Major"},
        "issues_enabled": True,
    })


def restart(tmp_path, **fields):
    row = {"id": 1, "path": "a.py", "line": 1, "rule": "tests",
           "sev": "Major", "msg": "A concrete defect.", **fields}
    p = tmp_path / "state.json"
    p.write_text(json.dumps({"version": 1, "prs": {}, "omni_head": "a" * 40,
                             "omni_complete": True, "omni_findings": [row]}))
    return state.load_state(p)


@pytest.mark.parametrize("flag", ["fix_attempted", "fix_stale"])
@pytest.mark.parametrize("value", ["false", 0])
def test_restart_does_not_suppress_fix_with_malformed_flag(tmp_path, monkeypatch, flag, value):
    st = restart(tmp_path, **{flag: value})
    monkeypatch.setattr(engine, "_fix_freshness_gate", lambda *a: True)
    calls = []
    monkeypatch.setattr(executor, "attempt_fix", lambda *a: calls.append(a) or
                        {"status": "pr_opened", "pr_number": 9})
    report = engine.CycleReport(repo="owner/project")
    engine._omni_fix_phase(config(), SimpleNamespace(name="github"), st, report)
    assert len(calls) == 1
    assert report.fix_prs_opened == 1


@pytest.mark.parametrize("line", [True, False, 0, -1])
def test_restart_reconciles_invalid_line_and_completion(tmp_path, line):
    st = restart(tmp_path, line=line)
    assert st["omni_findings"] == []
    assert "omni_complete" not in st
    assert "omni_head" not in st


def test_unknown_severity_already_skips_fix_without_crashing(tmp_path, monkeypatch):
    # Counterevidence to R15-002's claimed crash: the existing membership
    # guard precedes list.index. Keep this evidence executable.
    st = restart(tmp_path, sev="Severe")
    monkeypatch.setattr(executor, "attempt_fix", lambda *a: pytest.fail("invalid severity fixed"))
    report = engine.CycleReport(repo="owner/project")
    engine._omni_fix_phase(config(), SimpleNamespace(name="github"), st, report)
    assert report.fix_attempts == 0


@pytest.mark.parametrize("complete", [True, False])
def test_audit_issue_body_publishes_readiness_only_after_completion(complete):
    findings = [{"id": 1, "path": "README.md", "line": 1,
                 "rule": "general", "sev": "Minor", "msg": "Missing usage details."}]
    body = engine._omni_report_body(config(), findings, 4 if complete else 2, 4, complete)
    if complete:
        score, _ = engine._omni_readiness(findings)
        assert f"Readiness: {score}/100" in body
        assert "missing-evidence caps" in body
    else:
        assert "Readiness:" not in body


def test_completed_old_audit_is_refreshed_once_without_rescanning(monkeypatch, tmp_path):
    st = {"omni_complete": True, "omni_published": True, "omni_issue": 7,
          "omni_head": "a" * 40, "omni_total": 4,
          "omni_findings": [{"id": 1, "path": "README.md", "line": 1,
                             "rule": "general", "sev": "Minor", "msg": "Missing usage details."}]}
    bodies = []
    forge = SimpleNamespace(name="github", update_issue=lambda *a: bodies.append(a[-1]) or True)
    monkeypatch.setattr(engine, "_probe_head", lambda *a: "a" * 40)
    cfg = config().model_copy(update={"omnisweep": config().omnisweep.model_copy(update={"fix": False})})
    engine._omnisweep_step(cfg, forge, tmp_path / "state.json", None, st,
                          engine.CycleReport(repo=cfg.repo), None)
    assert len(bodies) == 1 and "Readiness:" in bodies[0]
    assert st["omni_report_version"] == 2
    engine._omnisweep_step(cfg, forge, tmp_path / "state.json", None, st,
                          engine.CycleReport(repo=cfg.repo), None)
    assert len(bodies) == 1


def test_failed_old_audit_refresh_defers_fixes(monkeypatch, tmp_path):
    st = {"omni_complete": True, "omni_published": True, "omni_issue": 7,
          "omni_head": "a" * 40, "omni_total": 1,
          "omni_findings": [{"id": 1, "path": "a.py", "line": 1,
                             "rule": "tests", "sev": "Major", "msg": "A concrete defect."}]}
    forge = SimpleNamespace(name="github", update_issue=lambda *a: False)
    monkeypatch.setattr(engine, "_probe_head", lambda *a: "a" * 40)
    monkeypatch.setattr(engine, "_omni_fix_phase", lambda *a: pytest.fail("fix before publication"))
    engine._omnisweep_step(config(), forge, tmp_path / "state.json", None, st,
                          engine.CycleReport(repo="owner/project"), None)
    assert st["omni_pub_fail"] == 1
    assert st.get("omni_report_version") != 2


@pytest.mark.parametrize("bad", [
    {"id": None}, {"id": True}, {"id": 0}, {"id": "3"},
    {"user": None}, {"user": {"login": 3}},
])
def test_uncertain_triage_marker_defers_before_model_and_publication(monkeypatch, bad):
    marker = {"id": 3, "body": "<!-- fl4write-triage:v1 -->",
              "user": {"login": "fl4write[bot]"}, **bad}
    forge = SimpleNamespace(_paginated=lambda *a, **k: iter([marker]),
                            create_comment=lambda *a: pytest.fail("duplicate comment"))
    monkeypatch.setattr(issues, "collect_new_issues", lambda *a, **k: [{"number": 7}])
    monkeypatch.setattr(issues, "triage_issue", lambda *a: pytest.fail("unnecessary model call"))
    st = {}
    result = issues.run_issues_cycle(config(), st, forge)
    assert result["errors"] == 1
    assert result["triaged"] == 0
    assert st["issues_retry"] == [7]
    assert "last_triaged_number" not in st
