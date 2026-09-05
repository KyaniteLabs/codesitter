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
