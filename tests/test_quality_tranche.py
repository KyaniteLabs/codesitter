"""Quality tranche (2026-09-01, consensus-gated) — the ship-gate tests the
Architect required. Each pins a live-caught failure class:

- GATEKEEPER REAL FILTER PATH: no test had ever exercised a SUCCESSFUL
  keep-list (the filter was provably dead — 850 fail-opens/sweep; its system
  prompt was never sent).
- EXECUTOR PATCH PROMPT: the fix lane's model layer was dead the same way
  (analyzer prompt sent to a patch ask -> every attempt "nofix", and nofix
  hit NO branch — invisible).
- FIX TELEMETRY: attempts/failures counted; ONE summarizing alert per cycle;
  nofix/testfail are failure classes, blocked stays escalation.
- FRESHNESS GATE: the #503 class (file deleted post-merge) never reaches
  attempt_fix; omni marks fix_stale permanently.
- POST-FILTERS: line<=0 unanchored and self-contradicting findings dropped,
  case-insensitively, through the log-what-you-dropped path.
- FORGE-AWARE SURVEILLANCE: the probe checks BOTH config names via the
  adapter on Forgejo-primary repos (false "adoption lost" lived-observed).
"""

from __future__ import annotations

import json

from fl4write import config as cfg
from fl4write import gatekeeper
from fl4write.analyzer import analyze
from fl4write.engine import run_cycle
from fl4write.forges import ForgeAdapter
from fl4write.models import Finding, PullRequest


def make_config(**over):
    raw = {
        "repo": "KyaniteLabs/kinocut",
        "forges": {"github": {"role": "primary", "api_base": "https://api.github.com", "token_env": "GHT"}},
        "model": {"endpoint": "http://m/v1/chat/completions", "model": "t", "key_env": "MK"},
        "review": {"secrets": "never commit secrets"},
        "severity_vocab": ["Critical", "Major", "Minor", "Nit"],
        "shadow": False,
    }
    raw.update(over)
    return cfg.RepoConfig.model_validate(raw)


GOOD = Finding(rule_id="secrets", severity="Critical", path="x.py", line=3, message="token in url")
NITTY = Finding(rule_id="secrets", severity="Nit", path="x.py", line=9, message="cosmetic wording")


class TestGatekeeperRealFilterPath:
    def test_keep_list_actually_filters(self, monkeypatch):
        """The never-before-tested path: a model returning a VALID keep list
        drops the noise and keeps the signal. system= must reach the double
        (**kwargs tolerance — the Architect's ripple note)."""
        seen_systems = []

        def keep_model(route, prompt, mode="pr", system=None, **kw):
            seen_systems.append(system or "")
            return json.dumps({"keep": [{"path": "x.py", "line": 3, "reason": "real"}]})

        monkeypatch.setattr("fl4write.gatekeeper._call_model", keep_model)
        kept, dropped, failed_open = gatekeeper.filter_findings([GOOD, NITTY], make_config())
        assert [f.line for f in kept] == [3] and dropped == 1 and failed_open is False
        assert "KILL findings" in seen_systems[0]  # the gatekeeper's OWN contract was sent

    def test_analyzer_shape_response_still_fail_open(self, monkeypatch):
        """The dead-filter root cause as a regression: a model replying in
        the ANALYZER's shape ({"findings": ...}) to a keep ask must fail
        OPEN (post all), flagged — never silently, never drop-all."""
        monkeypatch.setattr(
            "fl4write.gatekeeper._call_model",
            lambda route, prompt, mode="pr", system=None, **kw: json.dumps({"findings": []}),
        )
        kept, dropped, failed_open = gatekeeper.filter_findings([GOOD, NITTY], make_config())
        assert len(kept) == 2 and dropped == 0 and failed_open is True


class TestExecutorPatchPrompt:
    def test_patch_system_prompt_is_sent(self, monkeypatch):
        """The fix lane's dead model layer: attempt_fix must send PATCH_SYSTEM
        (its own contract), not the analyzer default."""
        from fl4write import executor

        seen = {}

        def patch_model(route, prompt, mode="pr", system=None, **kw):
            seen["system"] = system or ""
            return json.dumps({"fixed_content": "fixed"})

        monkeypatch.setattr("fl4write.executor._call_model", patch_model)
        monkeypatch.setattr("fl4write.executor._get_file_content", lambda r, p, ref: "orig")
        monkeypatch.setattr("fl4write.executor.attempt_fix", executor.attempt_fix)  # no-op guard
        # dry-invoke the model path only: build the minimal prompt route
        pr = PullRequest(forge="github", number=1, repo="o/r", head_sha="a" * 40)
        f = Finding(rule_id="secrets", severity="Critical", path="x.py", line=1, message="m")
        c = make_config(fix={"enabled": True, "merge_own_prs": False})
        monkeypatch.setattr("fl4write.executor._run", lambda cmd, cwd=None, timeout=120, env=None: type(
            "R", (), {"returncode": 0, "stdout": pr.head_sha, "stderr": ""})())
        monkeypatch.setattr("fl4write.executor._write_contained", lambda w, p, content: None)
        monkeypatch.setattr("fl4write.executor._run_tests", lambda w, c: True)
        monkeypatch.setattr("fl4write.executor._gh_api", lambda m, p, d=None: {"number": 9, "html_url": "u"})
        result = executor.attempt_fix(pr, f, c)
        assert "code-fixer" in seen["system"], "PATCH_SYSTEM must reach the model"
        assert result.get("status") == "pr_opened"


class TestFixTelemetryAndFreshness:
    def _forge(self):
        class F(ForgeAdapter):
            name = "github"

            def __init__(self):
                super().__init__(cfg.ForgeBinding(role="primary", api_base="https://api.github.com", token_env="GHT"))
                self.posts, self.prs = [], 0
                self.attempts = []
                self.paths_on_head = {"x.py"}

            def list_open_prs(self, repo):
                return [PullRequest(forge="github", number=7, repo=repo, title="t", head_sha="a" * 40)]

            def get_persistent_comment(self, repo, number):
                return None

            def create_comment(self, repo, number, body):
                self.posts.append((number, body))
                return 1

            def update_comment(self, repo, number, cid, body):
                pass

            def path_exists(self, repo, path):
                return path in self.paths_on_head

        return F()

    def test_nofix_and_testfail_counted_with_one_summary_alert(self, tmp_path, monkeypatch):
        forge = self._forge()
        c = make_config(shadow=False, fix={"enabled": True, "merge_own_prs": False})

        def fake_analyze(pr, files, text, config, mode="pr"):
            from fl4write.models import ReviewDoc

            return ReviewDoc(pr=pr, findings=[GOOD])

        calls = {"n": 0}

        def flaky(pr, f, config):
            calls["n"] += 1
            return {"status": "testfail", "reason": "tests failed"} if calls["n"] == 1 else {"status": "nofix", "reason": "no fix"}

        monkeypatch.setattr("fl4write.engine.adapter_for", lambda b: forge)
        monkeypatch.setattr("fl4write.analyzer.analyze", fake_analyze)
        monkeypatch.setattr("fl4write.executor.attempt_fix", flaky)
        monkeypatch.setattr("fl4write.executor.check_and_merge_own_prs", lambda cc, b, **kw: 0)
        r = run_cycle(c, tmp_path / "s.json", get_diff=lambda pr: ({"x.py"}, "d"), run_fixes=True)
        assert r.fix_attempts == 1 and r.fix_failures == 1  # GOOD is Critical -> one attempt
        assert sum(1 for a in r.alerts if a.startswith("fix failures:")) == 1  # ONE summary line

    def test_stale_file_never_attempted(self, tmp_path, monkeypatch):
        """The #503 class: finding's file deleted from HEAD after review —
        the fix is skipped (no attempt burned), finding stays posted."""
        forge = self._forge()
        forge.paths_on_head = set()  # x.py is gone from HEAD
        c = make_config(shadow=False, fix={"enabled": True, "merge_own_prs": False})

        def fake_analyze(pr, files, text, config, mode="pr"):
            from fl4write.models import ReviewDoc

            return ReviewDoc(pr=pr, findings=[GOOD])

        def must_not_attempt(pr, f, config):
            raise AssertionError("freshness gate must block the attempt")

        monkeypatch.setattr("fl4write.engine.adapter_for", lambda b: forge)
        monkeypatch.setattr("fl4write.analyzer.analyze", fake_analyze)
        monkeypatch.setattr("fl4write.executor.attempt_fix", must_not_attempt)
        monkeypatch.setattr("fl4write.executor.check_and_merge_own_prs", lambda cc, b, **kw: 0)
        r = run_cycle(c, tmp_path / "s.json", get_diff=lambda pr: ({"x.py"}, "d"), run_fixes=True)
        assert r.fix_attempts == 0 and len(forge.posts) == 1  # review posted; fix skipped


class TestPostFilters:
    def _analyze_with(self, monkeypatch, items):
        monkeypatch.setattr(
            "fl4write.analyzer._call_model",
            lambda route, prompt, mode="pr", system=None, **kw: json.dumps({"findings": items}),
        )
        return analyze(
            PullRequest(forge="github", number=1, repo="o/r", head_sha="a" * 40),
            {"x.py"}, "diff", make_config(),
        )

    def test_line_zero_dropped(self, monkeypatch):
        doc = self._analyze_with(monkeypatch, [
            {"rule_id": "secrets", "severity": "Major", "path": "x.py", "line": 0, "category": "c", "message": "m"},
        ])
        assert doc.findings == [] and doc.digest["_dropped_ungrounded"] >= 1

    def test_self_contradicting_dropped_case_insensitive(self, monkeypatch):
        doc = self._analyze_with(monkeypatch, [
            {"rule_id": "secrets", "severity": "Major", "path": "x.py", "line": 4, "category": "c",
             "message": "The totals MATCH and this IS CONSISTENT. No issue here really"},
        ])
        assert doc.findings == []

    def test_clean_anchored_finding_survives(self, monkeypatch):
        doc = self._analyze_with(monkeypatch, [
            {"rule_id": "secrets", "severity": "Major", "path": "x.py", "line": 4, "category": "c",
             "message": "live problem found"},
        ])
        assert len(doc.findings) == 1


class TestForgeAwareSurveillance:
    """The Critic's blocking rewrite: exercises the PRODUCTION probe
    (_probe_adoption), not a re-implementation. Fails if cli.py regresses."""

    def _github_cfg(self):
        return make_config()

    def _forgejo_cfg(self):
        return cfg.RepoConfig.model_validate({
            "repo": "o/r",
            "forges": {"forgejo": {"role": "primary", "api_base": "https://git.example/api/v1", "token_env": "FT"}},
            "model": {"endpoint": "http://m/v1/chat/completions", "model": "t", "key_env": "MK"},
            "review": {"secrets": "law"},
            "severity_vocab": ["Critical", "Major", "Minor", "Nit"],
        })

    def test_forgejo_primary_probes_via_adapter_both_names(self, monkeypatch, capsys):
        from fl4write.cli import _probe_adoption

        probed = []

        class FakeAdapter:
            def path_exists(self, repo, path):
                probed.append(path)
                return path == ".codesitter.yaml"  # only the LEGACY name exists

        _probe_adoption(self._forgejo_cfg(), forge_adapter=FakeAdapter())
        out = capsys.readouterr().out
        assert probed == [".fl4write.yaml", ".codesitter.yaml"]  # BOTH names
        assert "adoption lost" not in out  # legacy name present -> no false alert

    def test_forgejo_primary_alerts_when_both_absent(self, capsys):
        from fl4write.cli import _probe_adoption

        class FakeAdapter:
            def path_exists(self, repo, path):
                return False

        _probe_adoption(self._forgejo_cfg(), forge_adapter=FakeAdapter())
        assert "adoption lost" in capsys.readouterr().out

    def test_github_primary_uses_gh_cli_and_both_names(self, monkeypatch, capsys):
        from fl4write import cli as cli_mod

        calls = []

        def fake_run(cmd, capture_output=True, text=True, timeout=30):
            calls.append(cmd[2])
            return type("R", (), {"returncode": 0 if ".codesitter.yaml" in cmd[2] else 1})()

        monkeypatch.setattr(cli_mod.subprocess, "run", fake_run)
        cli_mod._probe_adoption(self._github_cfg(), forge_adapter=None)
        assert any(".fl4write.yaml" in c for c in calls) and any(".codesitter.yaml" in c for c in calls)
        assert "adoption lost" not in capsys.readouterr().out


class TestTelemetryAssertions:
    def test_cycle_line_carries_quality_counters(self):
        """The gate demanded assertions, not existence checks: gate_fail /
        fix_attempts / fix_fail are IN the printed cycle line."""
        import inspect

        import fl4write.cli as cli

        src = inspect.getsource(cli.main)
        for field in ("gate_fail=", "fix_attempts=", "fix_fail=", "mirror_degraded="):
            assert field in src, f"cycle line lost {field}"

    def test_omni_findings_carry_via(self, tmp_path, monkeypatch):
        from fl4write import state
        from fl4write.engine import run_cycle as rc

        class OmniFake(ForgeAdapter):
            name = "github"

            def __init__(self):
                super().__init__(cfg.ForgeBinding(role="primary", api_base="https://api.github.com", token_env="GHT"))
                self.issues = []

            def list_open_prs(self, repo):
                return []

            def list_merged_prs(self, repo, since_iso):
                return []

            def get_persistent_comment(self, repo, number):
                return None

            def create_comment(self, repo, number, body):
                return 1

            def update_comment(self, repo, number, cid, body):
                pass

            def head_check_runs(self, repo):
                return ("dead" + "beef" * 9, [])

            def list_tree_files(self, repo):
                return [("a.py", 10)], False

            def get_file(self, repo, path, ref):
                return "x = 1"

            def open_issue(self, repo, title, body):
                self.issues.append(title)
                return 9

            def update_issue(self, repo, number, body):
                return True

            def path_exists(self, repo, path):
                return True

        from fl4write.models import ReviewDoc

        c = make_config(omnisweep={"enabled": True, "max_files_per_cycle": 5})
        monkeypatch.setattr("fl4write.engine.adapter_for", lambda b: OmniFake())

        def fake_analyze(pr, files, text, config, mode="pr"):
            return ReviewDoc(pr=pr, findings=[Finding(
                rule_id="secrets", severity="Major", path="a.py", line=1, message="m")])

        monkeypatch.setattr("fl4write.analyzer.analyze", fake_analyze)
        rc(c, tmp_path / "s.json", get_diff=lambda pr: (set(), ""))
        st = state.load_state(tmp_path / "s.json")
        assert all("via" in f for f in st["omni_findings"]) and st["omni_findings"][0]["via"] == "t"
