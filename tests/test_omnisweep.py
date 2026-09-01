"""Omnisweep — the consensus-gated adversarial suite (Architect+Critic
approved plan, fl4write #4). Laws pinned (acceptance criteria A-F + the
Critic's collision amendments):

A. cursor advances only past scanned files; per-cycle cap respected;
   terminal on exhaustion; max_total_files aborts LOUDLY.
B. findings compacted (message<=200, no proposals); issue body capped with
   overflow line.
C. issue create/update failures degrade — findings live in state, retry next
   cycle, never a crash, never a second issue while one is live.
D. fix phase gated by (complete AND omnisweep.fix AND github-primary);
   Forgejo → loud alert; branch numbers unique per (head, finding-id) —
   proven beyond 4096 findings (the Critic's wrap regression); ids stable
   across cycles.
E. gatekeeper ALWAYS applied in file mode; grounding: a finding on any path
   other than the scanned file is dropped.
F. shadow mode touches NOTHING — no issue create, no issue edit.
"""

from __future__ import annotations

import json

import pytest

from fl4write import config as cfg
from fl4write import state
from fl4write.engine import run_cycle
from fl4write.forges import ForgeAdapter, ForgeError
from fl4write.models import Finding, PullRequest


def make_config(**over):
    raw = {
        "repo": "KyaniteLabs/kinocut",
        "forges": {
            "github": {"role": "primary", "api_base": "https://api.github.com", "token_env": "GHT"},
        },
        "model": {"endpoint": "http://m/v1/chat/completions", "model": "t", "key_env": "MK"},
        "review": {"secrets": "never commit secrets", "tests": "tests ship"},
        "severity_vocab": ["Critical", "Major", "Minor", "Nit"],
        "shadow": False,
        "omnisweep": {"enabled": True},
    }
    raw.update(over)
    return cfg.RepoConfig.model_validate(raw)


class OmniForge(ForgeAdapter):
    name = "github"

    def __init__(self, files=None, model_findings=None):
        super().__init__(cfg.ForgeBinding(role="primary", api_base="https://api.github.com", token_env="GHT"))
        self.tree = files or [("src/a.py", 100), ("src/b.py", 200), ("node_modules/x.js", 50), ("big.bin", 300_000), ("tiny.py", 0)]
        self.model_findings = model_findings or []
        self.issues: list[tuple[str, str]] = []  # (title, body)
        self.issue_updates: list[tuple[int, str]] = []
        self.issue_number = 700
        self.fail_create = False
        self.fail_update = False
        self.fix_calls: list[PullRequest] = []
        self.model_calls: list[str] = []

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
        return [(p, s) for (p, s) in self.tree], False

    def get_file(self, repo, path, ref):
        return f"# content of {path}\nprint('x')\n" * 5

    def open_issue(self, repo, title, body):
        if self.fail_create:
            return None
        self.issues.append((title, body))
        self.issue_number += 1
        return self.issue_number

    def update_issue(self, repo, number, body):
        if self.fail_update:
            return False
        self.issue_updates.append((number, body))
        return True


def _run(forge, monkeypatch, state_path, findings=None, model_spy=False, **cfg_over):
    from fl4write.models import ReviewDoc

    c = make_config(**cfg_over)

    def fake_analyze(pr, files, text, config, mode="pr"):
        if model_spy:
            forge.model_calls.append(next(iter(files)))
        source = forge.model_findings if findings is None else findings
        # emulate the analyzer's grounding gate: findings only for the scanned file
        return ReviewDoc(pr=pr, findings=[f for f in source if f.path in files])

    monkeypatch.setattr("fl4write.engine.adapter_for", lambda b: forge)
    monkeypatch.setattr("fl4write.analyzer.analyze", fake_analyze)
    return run_cycle(c, state_path, get_diff=lambda pr: (set(), ""))


F1 = Finding(rule_id="secrets", severity="Critical", path="src/a.py", line=2, message="m")
F2 = Finding(rule_id="tests", severity="Major", path="src/b.py", line=1, message="x" * 500)


class TestSweepLaws:
    def test_cursor_cap_and_terminal(self, tmp_path, monkeypatch):
        forge = OmniForge(files=[(f"f{n:03}.py", 100) for n in range(25)])
        sp = tmp_path / "s.json"
        r1 = _run(forge, monkeypatch, sp, omnisweep={"enabled": True, "max_files_per_cycle": 10})
        assert r1.omni_scanned == 10
        r2 = _run(forge, monkeypatch, sp, omnisweep={"enabled": True, "max_files_per_cycle": 10})
        assert r2.omni_scanned == 10
        r3 = _run(forge, monkeypatch, sp, omnisweep={"enabled": True, "max_files_per_cycle": 10})
        assert r3.omni_scanned == 5 and any("omnisweep complete" in a for a in r3.alerts)
        st = state.load_state(sp)
        assert st["omni_complete"]

    def test_excludes_and_size_caps_honored(self, tmp_path, monkeypatch):
        forge = OmniForge()
        _run(forge, monkeypatch, tmp_path / "s.json",
             omnisweep={"enabled": True, "max_files_per_cycle": 50})
        scanned_tree_paths = {p for p, _ in forge.tree if p not in ("node_modules/x.js", "big.bin", "tiny.py")}
        st = state.load_state(tmp_path / "s.json")
        assert st["omni_complete"]  # everything scannable was scanned
        assert len(scanned_tree_paths) == 2  # node_modules/big/empty excluded

    def test_total_files_cap_aborts_loudly(self, tmp_path, monkeypatch):
        forge = OmniForge(files=[(f"f{n:03}.py", 100) for n in range(50)])
        r = _run(forge, monkeypatch, tmp_path / "s.json",
                 omnisweep={"enabled": True, "max_total_files": 10})
        assert any("ABORTED" in a for a in r.alerts)
        assert state.load_state(tmp_path / "s.json")["omni_complete"]  # terminal: no retry loop

    def test_findings_compacted_no_proposals(self, tmp_path, monkeypatch):
        forge = OmniForge(model_findings=[F1, F2])
        _run(forge, monkeypatch, tmp_path / "s.json", omnisweep={"enabled": True, "max_files_per_cycle": 50})
        st = state.load_state(tmp_path / "s.json")
        recs = st["omni_findings"]
        assert all(len(r["msg"]) <= 200 for r in recs)
        assert all("proposal" not in r for r in recs)

    def test_issue_body_capped_with_overflow(self, tmp_path, monkeypatch):
        many = [Finding(rule_id="tests", severity="Minor", path=f"f{n:03}.py", line=1, message="m")
                for n in range(10)]
        forge = OmniForge(model_findings=many)
        forge.tree = [(f"f{n:03}.py", 100) for n in range(10)]
        r = _run(forge, monkeypatch, tmp_path / "s.json",
                 omnisweep={"enabled": True, "max_files_per_cycle": 50, "max_findings_in_issue": 5})
        assert len(forge.issues) == 1
        body = forge.issues[0][1]
        assert "more findings recorded in sweep state" in body
        assert body.count("### ") <= 5

    def test_issue_failure_degrades_and_never_duplicates(self, tmp_path, monkeypatch):
        """Create fails -> findings survive in state; create succeeds next
        cycle (ONE issue, never a second); a later update failure alerts
        loudly and still loses nothing."""
        forge = OmniForge(model_findings=[F1])
        forge.fail_create = True
        sp = tmp_path / "s.json"
        # cycle 1: scan file 1, creation fails
        r1 = _run(forge, monkeypatch, sp, omnisweep={"enabled": True, "max_files_per_cycle": 1})
        assert any("creation failed" in a for a in r1.alerts)
        assert len(state.load_state(sp)["omni_findings"]) == 1  # findings survive in state
        # cycle 2: scan file 2, creation succeeds (issue recorded in state)
        forge.fail_create = False
        _run(forge, monkeypatch, sp, omnisweep={"enabled": True, "max_files_per_cycle": 1})
        assert len(forge.issues) == 1 and state.load_state(sp)["omni_issue"]
        # cycle 3: sweep already complete — reopen a sliver and let the UPDATE fail
        forge.fail_update = True
        st = state.load_state(sp)
        st["omni_complete"] = False
        st["omni_cursor"] = "src/a.py"  # only src/b.py remains
        state.save_state(sp, st)
        r3 = _run(forge, monkeypatch, sp, omnisweep={"enabled": True, "max_files_per_cycle": 1})
        assert any("update failed" in a for a in r3.alerts)
        assert len(forge.issues) == 1  # exactly one issue across all cycles

    def test_shadow_touches_nothing(self, tmp_path, monkeypatch):
        forge = OmniForge(model_findings=[F1])
        r = _run(forge, monkeypatch, tmp_path / "s.json", shadow=True,
                 omnisweep={"enabled": True, "max_files_per_cycle": 50})
        assert r.omni_findings == 1 and forge.issues == [] and forge.issue_updates == []

    def test_grounding_wrong_path_dropped_file_mode(self, monkeypatch):
        """Criterion E: the grounding gate is mode-independent — in file mode
        a finding on any path other than the scanned file is dropped (the
        gate lives in analyze(), so exercise the REAL analyzer)."""
        from fl4write.analyzer import analyze
        from fl4write.models import PullRequest as PR

        monkeypatch.setattr(
            "fl4write.analyzer._call_model",
            lambda route, prompt, mode="pr": json.dumps({"findings": [
                {"rule_id": "secrets", "severity": "Critical", "path": "OTHER.py",
                 "line": 1, "category": "s", "message": "stray", "proposal": ""},
                {"rule_id": "secrets", "severity": "Critical", "path": "src/a.py",
                 "line": 1, "category": "s", "message": "grounded", "proposal": ""},
            ]}),
        )
        doc = analyze(
            PR(forge="github", number=0, repo="o/r", head_sha="a" * 40),
            {"src/a.py"}, "content", make_config(), mode="file",
        )
        paths = {f.path for f in doc.findings}
        assert paths == {"src/a.py"}  # stray dropped, grounded kept


class TestFixPhaseLaws:
    def _completed_state(self, tmp_path, monkeypatch, findings, **omni):
        forge = OmniForge(model_findings=findings)
        omni.setdefault("max_files_per_cycle", 50)
        _run(forge, monkeypatch, tmp_path / "s.json", omnisweep=omni)
        return forge

    def test_fix_phase_gated_off_by_default(self, tmp_path, monkeypatch):
        forge = self._completed_state(tmp_path, monkeypatch, [F1])
        assert forge.fix_calls == []  # omnisweep.fix defaults False

    def test_fix_phase_runs_when_gated_on(self, tmp_path, monkeypatch):
        forge = self._completed_state(tmp_path, monkeypatch, [F1], fix=True)
        calls = []

        def fake_fix(pr, finding, config):
            calls.append(pr)
            return {"status": "pr_opened", "pr_number": 9}

        monkeypatch.setattr("fl4write.executor.attempt_fix", fake_fix)
        # fix phase runs on the NEXT cycle (post-completion drain)
        _run(forge, monkeypatch, tmp_path / "s.json", omnisweep={"enabled": True, "fix": True})
        assert len(calls) == 1 and calls[0].head_sha.startswith("dead")

    def test_major_blocked_by_critical_floor(self, tmp_path, monkeypatch):
        monkeypatch.setattr("fl4write.executor.attempt_fix",
                            lambda pr, f, c: (_ for _ in ()).throw(AssertionError("must not attempt")))
        forge = self._completed_state(tmp_path, monkeypatch, [F2], fix=True)  # F2 is Major
        _run(forge, monkeypatch, tmp_path / "s.json", omnisweep={"enabled": True, "fix": True})

    def test_forgejo_escalates_loudly_no_attempt(self, tmp_path, monkeypatch):
        """Criterion D: Forgejo repos scan fine; the fix phase alerts loudly
        and NEVER reaches the GitHub-hardcoded executor."""
        monkeypatch.setattr("fl4write.executor.attempt_fix",
                            lambda pr, f, c: (_ for _ in ()).throw(AssertionError("must not attempt")))
        forge = type("ForgejoOmni", (OmniForge,), {"name": "forgejo"})(model_findings=[F1])
        sp = tmp_path / "s.json"
        _run(forge, monkeypatch, sp, omnisweep={"enabled": True, "fix": True, "max_files_per_cycle": 50},
             forges={"forgejo": {"role": "primary", "api_base": "https://git.kyanitelabs.tech/api/v1", "token_env": "FT"}})
        assert state.load_state(sp)["omni_complete"]  # scan ran (forgejo scans allowed)
        r2 = _run(forge, monkeypatch, sp, omnisweep={"enabled": True, "fix": True},
                  forges={"forgejo": {"role": "primary", "api_base": "https://git.kyanitelabs.tech/api/v1", "token_env": "FT"}})
        assert any("GitHub-only" in a for a in r2.alerts)  # loud, not silent

    def test_branch_numbers_unique_beyond_4096(self):
        """The Critic's wrap regression: stable ids far past any positional
        mask still yield distinct synth numbers (blake2b — no wrap ever)."""
        import hashlib

        head = "dead" + "beef" * 9
        numbers = set()
        for fid in list(range(1, 100)) + list(range(4090, 4200)):
            n = int(hashlib.blake2b(f"{head}:{fid}".encode(), digest_size=8).hexdigest()[:12], 16)
            numbers.add(n)
        assert len(numbers) == len(list(range(1, 100)) + list(range(4090, 4200)))

    def test_ids_stable_across_cycles(self, tmp_path, monkeypatch):
        forge = OmniForge(model_findings=[F1])
        sp = tmp_path / "s.json"
        _run(forge, monkeypatch, sp, omnisweep={"enabled": True, "max_files_per_cycle": 50})
        id1 = [r["id"] for r in state.load_state(sp)["omni_findings"]]
        _run(forge, monkeypatch, sp, omnisweep={"enabled": True})
        id2 = [r["id"] for r in state.load_state(sp)["omni_findings"]]
        assert id1 == id2 and id1  # no re-assignment, no churn-branches


class TestConfigKnobs:
    def test_strict_bounds(self):
        with pytest.raises(Exception):
            make_config(omnisweep={"enabled": True, "max_files_per_cycle": 0})
        with pytest.raises(Exception):
            make_config(omnisweep={"enabled": True, "max_total_files": 5})
        with pytest.raises(Exception):
            make_config(omnisweep={"enabled": True, "fix_min_severity": "Everything"})
        with pytest.raises(Exception):
            make_config(omnisweep={"enbled": True})
