"""CI-watch (CEO directive 2026-09-01): red default-branch HEAD on an OWN
repo summons review + fix. Laws pinned here:
- SHA-keyed acting: same red head never re-acts; a new head re-arms the watch;
- findings come ONLY from check annotations (deterministic — no model in the
  finding);
- fix lane gets the synthetic red-head PR (rails apply: fork/bot never touched
  — the fleet is own-repos by construction);
- no fix landing escalates to an issue; every failure path degrades, never
  crashes the cycle;
- disabled by default — the forge is never queried.
"""

from __future__ import annotations

import json

from fl4write import config as cfg
from fl4write.engine import run_cycle
from fl4write.forges import ForgeAdapter
from fl4write.models import PullRequest


def make_config(**over):
    raw = {
        "repo": "KyaniteLabs/fl4write",
        "forges": {
            "github": {
                "role": "primary",
                "api_base": "https://api.github.com",
                "token_env": "GHT",
            }
        },
        "model": {
            "endpoint": "http://model/v1/chat/completions",
            "model": "test-model",
            "key_env": "MK",
        },
        "review": {"secrets": "never commit secrets"},
        "severity_vocab": ["Critical", "Major", "Minor", "Nit"],
        "shadow": False,
        "ci_watch": {"enabled": True},
        "fix": {"enabled": True, "merge_own_prs": False},
    }
    raw.update(over)
    return cfg.RepoConfig.model_validate(raw)


class CIRedForge(ForgeAdapter):
    name = "github"

    def __init__(self, head="deadbeef" + "0" * 32, checks=None, annotations=None, files=None):
        super().__init__(
            cfg.ForgeBinding(role="primary", api_base="https://api.github.com", token_env="GHT")
        )
        self.head = head
        self.checks = checks if checks is not None else [
            {"id": 1, "name": "test", "status": "completed", "conclusion": "failure",
             "output": {"summary": "2 tests failed"}},
        ]
        self.annotations = annotations if annotations is not None else [
            {"path": "tests/test_x.py", "start_line": 12, "message": "assert 1 == 2", "level": "failure"},
        ]
        self.issues_opened: list[tuple[str, str]] = []
        self.fix_attempts: list[PullRequest] = []
        self.files = files if files is not None else {
            "tests/test_x.py", "tests/test_1.py", "tests/test_2.py", "tests/test_3.py",
        }

    # -- engine surface
    def list_open_prs(self, repo):
        return []

    def path_exists(self, repo, path):
        return True  # freshness-gate double: files exist

    def list_merged_prs(self, repo, since_iso):
        return []

    def get_persistent_comment(self, repo, number):
        return None

    def create_comment(self, repo, number, body):
        return 1

    def update_comment(self, repo, number, comment_id, body):
        pass

    # -- ci-watch surface
    def path_is_file(self, repo, path, ref=None):
        if path in self.files:
            return True
        if path.startswith("UNQUERYABLE"):
            return None  # fail-open: caller keeps the finding
        return False

    def head_check_runs(self, repo):
        return self.head, list(self.checks)

    def check_annotations(self, repo, check_run_id):
        return list(self.annotations)


def _run(tmp_path, forge, monkeypatch, fix_result=None, **cfg_over):
    c = make_config(**cfg_over)
    monkeypatch.setattr("fl4write.engine.adapter_for", lambda b: forge)
    monkeypatch.setattr(
        "fl4write.analyzer._call_model",
        lambda route, prompt, mode="pr": json.dumps({"findings": []}),
    )
    if fix_result is not None:
        def fake_fix(pr, finding, config):
            forge.fix_attempts.append((pr, finding))
            return fix_result
        monkeypatch.setattr("fl4write.executor.attempt_fix", fake_fix)

        def fake_issue(repo, title, body):
            forge.issues_opened.append((title, body))
            return 1
        monkeypatch.setattr("fl4write.executor.open_issue", fake_issue)
    return run_cycle(c, tmp_path / "state.json", get_diff=lambda pr: (set(), ""), run_fixes=True)


class TestCIWatch:
    def test_red_head_fix_pr_opened_and_acted_once(self, tmp_path, monkeypatch):
        forge = CIRedForge()
        r = _run(tmp_path, forge, monkeypatch, fix_result={"status": "pr_opened", "pr_number": 42})
        assert r.ci_red_heads == 1 and r.ci_fix_prs_opened == 1 and forge.issues_opened == []
        pr, finding = forge.fix_attempts[0]
        assert pr.head_sha == forge.head  # fix targets the RED head
        assert finding.rule_id == "ci" and finding.path == "tests/test_x.py" and finding.line == 12
        # second cycle, same SHA: never re-acts
        r2 = _run(tmp_path, forge, monkeypatch, fix_result={"status": "pr_opened", "pr_number": 43})
        assert r2.ci_fix_prs_opened == 0 and len(forge.fix_attempts) == 1

    def test_new_head_re_arms(self, tmp_path, monkeypatch):
        forge = CIRedForge()
        _run(tmp_path, forge, monkeypatch, fix_result={"status": "pr_opened", "pr_number": 1})
        forge.head = "cafe1234" + "0" * 32
        r2 = _run(tmp_path, forge, monkeypatch, fix_result={"status": "pr_opened", "pr_number": 2})
        assert r2.ci_fix_prs_opened == 1 and len(forge.fix_attempts) == 2

    def test_green_head_is_quiet(self, tmp_path, monkeypatch):
        forge = CIRedForge(checks=[
            {"id": 1, "name": "test", "status": "completed", "conclusion": "success"},
            {"id": 2, "name": "lint", "status": "completed", "conclusion": "skipped"},
        ])
        r = _run(tmp_path, forge, monkeypatch, fix_result={"status": "pr_opened"})
        assert r.ci_red_heads == 0 and forge.fix_attempts == [] and forge.issues_opened == []

    def test_pending_checks_are_not_red(self, tmp_path, monkeypatch):
        forge = CIRedForge(checks=[
            {"id": 1, "name": "test", "status": "in_progress", "conclusion": None},
        ])
        r = _run(tmp_path, forge, monkeypatch, fix_result={"status": "pr_opened"})
        assert r.ci_red_heads == 0 and forge.fix_attempts == []

    def test_no_fix_lands_escalates_to_issue(self, tmp_path, monkeypatch):
        forge = CIRedForge()
        r = _run(tmp_path, forge, monkeypatch, fix_result={"status": "nofix", "reason": "model returned no fix"})
        assert r.ci_fix_prs_opened == 0 and r.ci_escalations == 1
        title, body = forge.issues_opened[0]
        assert forge.head[:8] in title and "test" in title and "assert 1 == 2" in body

    def test_no_annotations_still_escalates_with_summary(self, tmp_path, monkeypatch):
        forge = CIRedForge(annotations=[])
        r = _run(tmp_path, forge, monkeypatch, fix_result={"status": "nofix"})
        assert r.ci_escalations == 1 and "2 tests failed" in forge.issues_opened[0][1]

    def test_unqueryable_head_degrades(self, tmp_path, monkeypatch):
        forge = CIRedForge()
        forge.head_check_runs = lambda repo: None
        r = _run(tmp_path, forge, monkeypatch, fix_result={"status": "pr_opened"})
        assert r.ci_red_heads == 0 and forge.fix_attempts == [] and not any(
            "escalat" in a for a in r.alerts
        )

    def test_disabled_by_default_never_queries(self, tmp_path, monkeypatch):
        forge = CIRedForge()
        queried = []
        orig = forge.head_check_runs
        forge.head_check_runs = lambda repo: (queried.append(1), orig(repo))[1]
        r = _run(tmp_path, forge, monkeypatch, ci_watch={"enabled": False})
        assert queried == [] and r.ci_red_heads == 0

    def test_fix_error_stops_attempts_not_cycle(self, tmp_path, monkeypatch):
        forge = CIRedForge(annotations=[
            {"path": f"tests/test_{i}.py", "start_line": i, "message": f"fail {i}", "level": "failure"}
            for i in range(1, 4)
        ])
        r = _run(tmp_path, forge, monkeypatch, fix_result={"status": "error", "reason": "fetch failed"})
        assert len(forge.fix_attempts) == 1  # environmental error stops the batch
        assert r.ci_escalations == 1 and r.ci_red_heads == 1  # cycle completed, escalated

    def test_runlevel_meta_annotations_are_not_code_findings(self, tmp_path, monkeypatch):
        """GH Actions auto-annotations anchor at the workflow dir (".github"):
        not code findings — no fix attempt is burned on an unfetchable dir
        (live 2026-09-03: the 10h red-main incident), and the red head still
        escalates."""
        forge = CIRedForge(annotations=[
            {"path": ".github", "start_line": 2,
             "message": "Node.js 20 is deprecated...", "level": "warning"},
            {"path": ".github", "start_line": 39,
             "message": "Process completed with exit code 1.", "level": "failure"},
        ])
        r = _run(tmp_path, forge, monkeypatch, fix_result={"status": "pr_opened"})
        assert r.ci_red_heads == 1
        assert forge.fix_attempts == []  # nothing burnable
        assert r.ci_fix_prs_opened == 0
        assert r.ci_escalations == 1  # red head still summons the human

    def test_mixed_annotations_only_file_paths_attempted(self, tmp_path, monkeypatch):
        forge = CIRedForge(annotations=[
            {"path": ".github", "start_line": 39,
             "message": "Process completed with exit code 1.", "level": "failure"},
            {"path": "tests/test_x.py", "start_line": 12,
             "message": "assert 1 == 2", "level": "failure"},
        ])
        r = _run(tmp_path, forge, monkeypatch, fix_result={"status": "pr_opened"})
        assert len(forge.fix_attempts) == 1
        assert forge.fix_attempts[0][1].path == "tests/test_x.py"
        assert r.ci_fix_prs_opened == 1 and r.ci_escalations == 0

    def test_unqueryable_path_keeps_the_finding(self, tmp_path, monkeypatch):
        """path_is_file None (transport failure) must NOT drop the finding —
        fail-open: a dropped real finding is worse than a stale attempt."""
        forge = CIRedForge(annotations=[
            {"path": "UNQUERYABLE/new.py", "start_line": 1,
             "message": "flaky network", "level": "failure"},
        ])
        _run(tmp_path, forge, monkeypatch, fix_result={"status": "pr_opened"})
        assert len(forge.fix_attempts) == 1
        assert forge.fix_attempts[0][1].path == "UNQUERYABLE/new.py"

    def test_shadow_never_touches_the_repo(self, tmp_path, monkeypatch):
        forge = CIRedForge()
        r = _run(tmp_path, forge, monkeypatch, fix_result={"status": "pr_opened"}, shadow=True)
        assert r.ci_fix_prs_opened == 0 and forge.fix_attempts == []
        assert forge.issues_opened == []  # no escalation from shadow either

    def test_config_knob_bounds(self):
        with __import__("pytest").raises(Exception):
            make_config(ci_watch={"enabled": True, "max_checks": 0})
        with __import__("pytest").raises(Exception):
            make_config(ci_watch={"enbled": True})  # typo aborts (fail-loud)


class TestCIWatchRails:
    def test_synthetic_pr_passes_fork_rail_never(self):
        """The synthetic CI PR is own-repo by construction; the fork rail
        stays hard for real fork PRs (regression guard of the boundary)."""
        from fl4write import fixlane

        pr = PullRequest(
            forge="github", number=1, repo="KyaniteLabs/fl4write",
            title="t", head_sha="a" * 40, is_fork=True,
        )
        assert "fork" in fixlane.fix_allowed(pr, make_config(), 0)
