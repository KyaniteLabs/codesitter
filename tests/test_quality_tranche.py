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

            return ReviewDoc(pr=pr, findings=[GOOD, Finding(
                rule_id="secrets", severity="Major", path="x.py", line=7, message="second finding")])

        calls = {"n": 0}

        def flaky(pr, f, config):
            calls["n"] += 1
            return {"status": "testfail", "reason": "tests failed"} if calls["n"] == 1 else {"status": "nofix", "reason": "no fix"}

        # two Major+ findings so BOTH failure branches run in ONE cycle

        monkeypatch.setattr("fl4write.engine.adapter_for", lambda b: forge)
        monkeypatch.setattr("fl4write.analyzer.analyze", fake_analyze)
        monkeypatch.setattr("fl4write.executor.attempt_fix", flaky)
        monkeypatch.setattr("fl4write.executor.check_and_merge_own_prs", lambda cc, b, **kw: 0)
        r = run_cycle(c, tmp_path / "s.json", get_diff=lambda pr: ({"x.py"}, "d"), run_fixes=True)
        assert r.fix_attempts == 2  # Critical + Major both attempted
        assert r.fix_failures == 2  # one testfail AND one nofix — both branches
        assert sum(1 for a in r.alerts if a.startswith("fix failures:")) == 1  # ONE summary line
        assert any("testfail" in n for n in r._fix_failure_notes) and any("nofix" in n for n in r._fix_failure_notes)

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
            ok = ".codesitter.yaml" in cmd[2]
            return type("R", (), {"returncode": 0 if ok else 1,
                                  "stderr": "" if ok else '... HTTP 404: Not Found ...'})()

        monkeypatch.setattr(cli_mod.subprocess, "run", fake_run)
        cli_mod._probe_adoption(self._github_cfg(), forge_adapter=None)
        assert any(".fl4write.yaml" in c for c in calls) and any(".codesitter.yaml" in c for c in calls)
        assert "adoption lost" not in capsys.readouterr().out


class TestTelemetryAssertions:
    def test_cycle_line_carries_quality_counters(self):
        """BEHAVIORAL (the Critic's residual closed): the formatted line
        carries every quality counter, tested against a real CycleReport —
        not by source inspection."""
        from fl4write.cli import format_cycle_line
        from fl4write.engine import CycleReport

        r = CycleReport(repo="o/r")
        r.gatekeeper_failed = 2
        r.fix_attempts = 3
        r.fix_failures = 1
        r.mirror_degraded = 1
        r.postmerge_reviewed = 4
        r.retro_reviewed = 2
        r.omni_scanned = 5
        r.omni_findings = 7
        r.ci_red_heads = 1
        line = format_cycle_line(r, make_config())
        for expected in (
            "gate_fail=2", "fix_attempts=3", "fix_fail=1", "mirror_degraded=1",
            "postmerge=4", "retro=2", "omni=5/7f", "ci_red=1", "repo=o/r",
        ):
            assert expected in line, f"cycle line lost {expected}"

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


class TestOmniFixStale:
    def test_live_marking_marks_stale_and_short_circuits(self, tmp_path, monkeypatch):
        """GLM audit: the old test SEEDED fix_stale — circular, blind to
        deletion of the marking code. This drives the LIVE path: a finding
        whose file is gone from HEAD gets fix_stale written by the engine."""
        from fl4write import state
        from fl4write.engine import run_cycle as rc

        class StaleForge(ForgeAdapter):
            name = "github"

            def __init__(self):
                super().__init__(cfg.ForgeBinding(role="primary", api_base="https://api.github.com", token_env="GHT"))
                self.tree = [("gone.py", 10)]
                self.attempts = 0

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
                return [(p, s) for p, s in self.tree], False

            def get_file(self, repo, path, ref):
                return "x=1" if path == "gone.py" else None

            def open_issue(self, repo, title, body):
                return 1

            def update_issue(self, repo, number, body):
                return True

            def path_exists(self, repo, path):
                return False  # the file vanished from HEAD AFTER the scan

            def attempt_fix(self, pr, f, config):
                self.attempts += 1
                return {"status": "pr_opened"}

        from fl4write.models import ReviewDoc

        c = make_config(
            omnisweep={"enabled": True, "fix": True, "fix_min_severity": "Major", "max_files_per_cycle": 5},
            fix={"enabled": True, "merge_own_prs": False},
        )
        forge = StaleForge()
        monkeypatch.setattr("fl4write.engine.adapter_for", lambda b: forge)

        def fake_analyze(pr, files, text, config, mode="pr"):
            return ReviewDoc(pr=pr, findings=[Finding(
                rule_id="secrets", severity="Major", path="gone.py", line=1, message="m")])

        monkeypatch.setattr("fl4write.analyzer.analyze", fake_analyze)
        import fl4write.executor as ex
        monkeypatch.setattr(ex, "attempt_fix", forge.attempt_fix)
        sp = tmp_path / "s.json"
        rc(c, sp, get_diff=lambda pr: (set(), ""))  # cycle 1: scan completes
        rc(c, sp, get_diff=lambda pr: (set(), ""))  # cycle 2: fix phase runs
        st = state.load_state(sp)
        assert st["omni_findings"][0].get("fix_stale") is True  # LIVE-marked
        assert forge.attempts == 0  # never attempted — gated

    def test_stale_omni_finding_short_circuits_forever(self, tmp_path, monkeypatch):
        """fix_stale must short-circuit eligibility permanently (the gate's
        missing test): a stale finding is never re-gated, never attempted."""
        from fl4write import state
        from fl4write.engine import run_cycle as rc

        c = make_config(
            shadow=False,
            omnisweep={"enabled": True, "fix": True, "fix_min_severity": "Major", "max_files_per_cycle": 5},
            fix={"enabled": True, "merge_own_prs": False},
        )
        sp = tmp_path / "s.json"
        st = {"version": 1, "prs": {}, "omni_complete": True, "omni_head": "d" * 40,
              "omni_findings": [{"id": 1, "path": "gone.py", "line": 1, "rule": "secrets",
                                  "sev": "Major", "msg": "m", "via": "t", "fix_stale": True}]}
        state.save_state(sp, st)

        def must_not_attempt(pr, f, config):
            raise AssertionError("fix_stale must short-circuit before any attempt")

        class FakeForge(ForgeAdapter):
            name = "github"

            def __init__(self):
                super().__init__(cfg.ForgeBinding(role="primary", api_base="https://api.github.com", token_env="GHT"))

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

            def path_exists(self, repo, path):
                return False  # the file is gone — would gate anyway

        monkeypatch.setattr("fl4write.engine.adapter_for", lambda b: FakeForge())
        monkeypatch.setattr("fl4write.executor.attempt_fix", must_not_attempt)
        r = rc(c, sp, get_diff=lambda pr: (set(), ""))
        assert r.fix_attempts == 0
        st2 = state.load_state(sp)
        assert st2["omni_findings"][0].get("fix_stale") is True  # unchanged, not re-gated


class TestNoOpPatchGuard:
    def test_identical_patch_is_nofix_before_any_writes(self, monkeypatch, tmp_path):
        """Live-caught on the first real fix attempt: a model patch identical
        to the original walked worktree→commit→push→PR and died as an opaque
        422 with an empty branch left behind. Identical = nofix, pre-writes."""
        from fl4write import executor

        monkeypatch.setattr(executor, "_get_file_content", lambda r, p, ref: "original")
        monkeypatch.setattr(
            executor, "_call_model",
            lambda route, prompt, mode="pr", system=None, **kw: '{"fixed_content": "original"}')
        pr = PullRequest(forge="github", number=1, repo="o/r", head_sha="a" * 40)
        f = Finding(rule_id="secrets", severity="Critical", path="x.py", line=1, message="m")
        c = make_config(fix={"enabled": True, "merge_own_prs": False})
        def must_not_touch(wd, p, content):
            raise AssertionError("no-op patch must never reach the worktree")

        monkeypatch.setattr(executor, "_write_contained", must_not_touch)
        result = executor.attempt_fix(pr, f, c)
        assert result["status"] == "nofix" and "no-op" in result["reason"]


class TestThinkPreambleParsing:
    def test_m3_think_block_with_braces_parses(self):
        """The CEO's standing route (MiniMax-M3) emits <think>...</think> that
        can contain braces; the naive first-{ slice died on it (live-caught).
        The extractor must survive think-with-braces AND raw JSON."""
        from fl4write.analyzer import extract_json

        hostile = (
            "<think>the function looks like {broken: 'code'} so the fix is {a: 1}"
            "</think>\n{\"findings\": [{\"rule_id\": \"secrets\", \"severity\": \"Major\", "
            "\"path\": \"x.py\", \"line\": 1, \"category\": \"c\", \"message\": \"m\"}]}"
        )
        parsed = extract_json(hostile)
        assert parsed["findings"][0]["rule_id"] == "secrets"
        assert extract_json('{"keep": []}') == {"keep": []}
        import pytest as _pytest

        with _pytest.raises(ValueError):
            extract_json("no json here at all")


class TestVerifyDiffTests:
    def test_failing_diff_yields_deterministic_critical(self, monkeypatch, tmp_path):
        """The planted-bug lesson: prompt-only tracing missed self-failing
        diffs (both M3 and deepseek, twice each). verify_diff_tests RUNS the
        diff's tests sandboxed and files a Critical carrying the failure."""
        from fl4write import executor
        from fl4write.models import PullRequest

        class R:
            def __init__(self, code, out):
                self.returncode, self.stdout, self.stderr = code, out, ""

        def fake_run(cmd, cwd=None, timeout=120, env=None):
            if cmd[:2] == ["git", "init"]:
                return R(0, "")
            if cmd[0] == "git":
                return R(0, "")
            if cmd[0] == "python3":
                return R(1, "FAILED test_proof_target - assert 1.0 == 3.0")
            return R(0, "")

        monkeypatch.setattr(executor, "_run", fake_run)
        pr = PullRequest(forge="github", number=198, repo="KyaniteLabs/Epoch", head_sha="a" * 40)
        c = make_config()
        f = executor.verify_diff_tests(pr, c, ["fl4write-proof/test_proof_target.py"])
        assert f is not None and f.severity == "Critical"
        assert "assert 1.0 == 3.0" in f.message and f.path == "fl4write-proof/test_proof_target.py"

    def test_infra_trouble_is_never_a_finding(self, monkeypatch):
        from fl4write import executor
        from fl4write.models import PullRequest

        def broken(cmd, **kw):
            raise RuntimeError("network gone")

        monkeypatch.setattr(executor, "_run", broken)
        pr = PullRequest(forge="github", number=1, repo="o/r", head_sha="a" * 40)
        assert executor.verify_diff_tests(pr, make_config(), ["test_x.py"]) is None

    def test_regex_matches_real_test_names(self):
        from fl4write.engine import _TEST_FILE_RE

        for good in ("tests/test_foo.py", "pkg/test_foo.py", "src/a.test.ts", "x/y_test.rs", "tests.py"):
            assert _TEST_FILE_RE.search(good), good
        for bad in ("src/main.py", "README.md", "testing.md"):
            assert not _TEST_FILE_RE.search(bad), bad


class TestSolAuditFixes:
    def test_envelope_key_survives_fenced_and_broken_think(self):
        """Sol reproduced three extract_json failures: fenced ```json with a
        trailing-brace prose, unclosed <think>, uppercase <THINK>. Envelope-
        key parsing must survive all three."""
        from fl4write.analyzer import extract_json

        fenced = '```json\n{"keep": []}\n``` prose {x}'
        unclosed = '<think>{analysis}\n{"keep": []}'
        upper = '<THINK>{analysis}</THINK>\n{"keep": []}'
        for hostile in (fenced, unclosed, upper):
            assert extract_json(hostile, envelope_key="keep") == {"keep": []}

    def test_merge_counter_counts_not_concatenates(self):
        """Sol: fix_prs_merged += list was a runtime TypeError swallowed by
        the broad except — the merge scan never counted. Source-level pin
        until the behavioral seam exists."""
        import inspect

        import fl4write.engine as eng

        src = inspect.getsource(eng)
        assert "fix_prs_merged += len(merged)" in src and "fix_prs_merged += merged\n" not in src

    def test_probe_none_is_inconclusive_not_lost(self, capsys):
        """Forgejo outage (path_exists None) must not fire adoption-lost."""
        from fl4write.cli import _probe_adoption
        from fl4write.config import RepoConfig

        class DeadForge:
            def path_exists(self, repo, path):
                return None  # unqueryable

        c = RepoConfig.model_validate({
            "repo": "o/r",
            "forges": {"forgejo": {"role": "primary", "api_base": "https://g.example/api/v1", "token_env": "FT"}},
            "model": {"endpoint": "http://m/v1/chat/completions", "model": "t", "key_env": "MK"},
            "review": {"secrets": "law"},
            "severity_vocab": ["Critical", "Major", "Minor", "Nit"],
        })
        _probe_adoption(c, forge_adapter=DeadForge())
        out = capsys.readouterr().out
        assert "inconclusive" in out and "adoption lost" not in out


class TestVerifyWiring:

    """GLM audit: the engine wiring (engine.py verify block) was untested —
    deleting it kept the suite green. This drives run_cycle end-to-end with a
    failing diff and asserts the deterministic Critical reaches the POST."""

    def test_failing_diff_reaches_posted_review_through_engine(self, tmp_path, monkeypatch, capsys):
        from fl4write.engine import run_cycle as rc
        from fl4write.models import ReviewDoc

        class WiredForge(ForgeAdapter):
            name = "github"

            def __init__(self):
                super().__init__(cfg.ForgeBinding(role="primary", api_base="https://api.github.com", token_env="GHT"))
                self.posts = []

            def list_open_prs(self, repo):
                return [PullRequest(forge="github", number=9, repo=repo, title="t", head_sha="a" * 40)]

            def get_persistent_comment(self, repo, number):
                return None

            def create_comment(self, repo, number, body):
                self.posts.append((number, body))
                return 1

            def update_comment(self, repo, number, cid, body):
                pass

            def path_exists(self, repo, path):
                return True

        c = make_config(shadow=False, verify_tests=True)
        forge = WiredForge()
        monkeypatch.setattr("fl4write.engine.adapter_for", lambda b: forge)
        monkeypatch.setattr(
            "fl4write.analyzer.analyze",
            lambda pr, files, text, config, mode="pr": ReviewDoc(pr=pr, findings=[]))
        monkeypatch.setattr(
            "fl4write.executor.verify_diff_tests",
            lambda pr, config, test_files: Finding(
                rule_id="tests", severity="Critical", path=test_files[0], line=1,
                category="CI", message="the diff's own tests FAIL (wired)"))
        rc(c, tmp_path / "s.json", get_diff=lambda pr: (
            {"fl4write-proof/test_proof_target.py", "fl4write-proof/proof_target.py"}, "diff"))
        assert len(forge.posts) == 1
        body = forge.posts[0][1]
        assert "tests FAIL" in body and "Critical" in body  # deterministic finding POSTED


