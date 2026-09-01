"""Retro audit (old mistakes) + Forgejo-native diff — the ULTRAQA cycle-1
adversarial suite (CEO asks 2026-09-01: "catch any old mistakes" + "Forgejo
stuff that is ONLY on there").

Laws pinned:
- retro walks ONLY below the forward watermark, newest-first, capped,
  cursor-resumable, terminal on window exhaustion;
- ZOMBIE findings (path gone from HEAD) post NOTHING on old PRs — silence
  beats stale noise; a clean/zombie PR leaves state, not comments;
- a pruned-record re-review continues edit-in-place (no duplicate comment);
- deferred (diff unavailable) PRs are retried; the cursor never passes them;
- Forgejo get_pr_diff: a non-diff payload or empty body returns None — an
  error page must never masquerade as an empty diff (LEARNINGS #3);
- the freshness gate fails OPEN when path_exists is unqueryable (None).
"""

from __future__ import annotations

import pytest

from fl4write import config as cfg
from fl4write import state
from fl4write.engine import run_cycle
from fl4write.forges import ForgeAdapter, ForgeError, ForgejoAdapter
from fl4write.models import Finding, PullRequest

FRESH = Finding(rule_id="secrets", severity="Major", path="x.py", line=3, message="live finding")
ZOMBIE = Finding(rule_id="secrets", severity="Major", path="gone/old.py", line=3, message="stale finding")


def make_config(**over):
    raw = {
        "repo": "KyaniteLabs/kinocut",
        "forges": {
            "github": {"role": "primary", "api_base": "https://api.github.com", "token_env": "GHT"},
        },
        "model": {"endpoint": "http://model/v1/chat/completions", "model": "t", "key_env": "MK"},
        "review": {"secrets": "never commit secrets"},
        "severity_vocab": ["Critical", "Major", "Minor", "Nit"],
        "shadow": False,
        "retro_audit": {"enabled": True},
    }
    raw.update(over)
    return cfg.RepoConfig.model_validate(raw)


def make_pr(**over):
    base = dict(forge="github", number=1, repo="KyaniteLabs/kinocut", title="t",
                head_sha="a" * 40, author="dev")
    base.update(over)
    return PullRequest.model_validate(base)


class RetroForge(ForgeAdapter):
    name = "github"

    def __init__(self):
        super().__init__(cfg.ForgeBinding(role="primary", api_base="https://api.github.com", token_env="GHT"))
        self.merged: list[PullRequest] = []
        self.paths_on_head: set[str] = {"x.py"}
        self.posts: list[tuple[int, str]] = []
        self.updates: list[tuple[int, str]] = []
        self.path_probe_fail = False

    def list_open_prs(self, repo):
        return []

    def list_merged_prs(self, repo, since_iso):
        from fl4write.forges import _parse_iso

        s = _parse_iso(since_iso)
        out = [p for p in self.merged if _parse_iso(p.merged_at) > s]
        out.sort(key=lambda p: p.merged_at)
        return out

    def get_persistent_comment(self, repo, number):
        for n, b in self.posts + self.updates:
            if n == number:
                return 1, b
        return None

    def create_comment(self, repo, number, body):
        self.posts.append((number, body))
        return len(self.posts)

    def update_comment(self, repo, number, cid, body):
        self.updates.append((number, body))

    def path_exists(self, repo, path):
        if self.path_probe_fail:
            return None
        return path in self.paths_on_head


def _run(forge, monkeypatch, state_path, findings, **cfg_over):
    from fl4write.models import ReviewDoc

    c = make_config(**cfg_over)

    def fake_analyze(pr, files, text, config):
        return ReviewDoc(pr=pr, findings=list(findings))

    monkeypatch.setattr("fl4write.engine.adapter_for", lambda b: forge)
    monkeypatch.setattr("fl4write.analyzer.analyze", fake_analyze)
    return run_cycle(c, state_path, get_diff=lambda pr: ({"x.py"}, "diff"))


def _seed_watermark(state_path, iso="2026-08-31T23:18:24Z"):
    state.save_state(state_path, {"version": 1, "prs": {}, "merged_since": iso})


class TestRetroSweep:
    def test_walks_below_watermark_newest_first_capped_and_resumes(self, tmp_path, monkeypatch):
        forge = RetroForge()
        forge.merged = [make_pr(number=n, merged_at=f"2026-08-15T12:0{n}:00Z") for n in range(1, 6)]
        sp = tmp_path / "s.json"
        _seed_watermark(sp)
        r = _run(forge, monkeypatch, sp, [FRESH], retro_audit={"enabled": True, "max_per_cycle": 3})
        assert r.retro_reviewed == 3
        assert [n for n, _ in forge.posts] == [5, 4, 3]  # newest first
        assert state.load_state(sp)["retro_cursor"] == "2026-08-15T12:03:00Z"
        r2 = _run(forge, monkeypatch, sp, [FRESH], retro_audit={"enabled": True, "max_per_cycle": 3})
        assert r2.retro_reviewed == 2  # resumed below the cursor, not restarted
        assert [n for n, _ in forge.posts] == [5, 4, 3, 2, 1]

    def test_zombie_and_clean_post_nothing(self, tmp_path, monkeypatch):
        forge = RetroForge()
        forge.merged = [make_pr(number=1, merged_at="2026-08-15T12:00:00Z")]
        sp = tmp_path / "s.json"
        _seed_watermark(sp)
        r = _run(forge, monkeypatch, sp, [ZOMBIE])
        assert r.retro_zombies == 1 and forge.posts == []
        assert state.load_state(sp)["prs"]["1"]["last_outcome"] == "retro:0"
        r2 = _run(forge, monkeypatch, sp, [])  # clean PR
        assert r2.retro_reviewed == 0 and forge.posts == []

    def test_mixed_findings_drop_only_zombies(self, tmp_path, monkeypatch):
        forge = RetroForge()
        forge.merged = [make_pr(number=1, merged_at="2026-08-15T12:00:00Z")]
        sp = tmp_path / "s.json"
        _seed_watermark(sp)
        r = _run(forge, monkeypatch, sp, [FRESH, ZOMBIE])
        assert r.retro_zombies == 1 and len(forge.posts) == 1
        assert "live finding" in forge.posts[0][1] and "stale finding" not in forge.posts[0][1]

    def test_freshness_gate_fails_open(self, tmp_path, monkeypatch):
        forge = RetroForge()
        forge.merged = [make_pr(number=1, merged_at="2026-08-15T12:00:00Z")]
        forge.path_probe_fail = True
        sp = tmp_path / "s.json"
        _seed_watermark(sp)
        r = _run(forge, monkeypatch, sp, [ZOMBIE])
        assert r.retro_zombies == 0 and len(forge.posts) == 1  # kept, not dropped

    def test_pruned_record_rereview_edits_in_place(self, tmp_path, monkeypatch):
        """State record pruned (normal) but the comment survives: a re-review
        must EDIT, never post a second comment (the notification law)."""
        forge = RetroForge()
        forge.merged = [make_pr(number=1, merged_at="2026-08-15T12:00:00Z")]
        sp = tmp_path / "s.json"
        _seed_watermark(sp)
        _run(forge, monkeypatch, sp, [FRESH])
        st = state.load_state(sp)
        st["prs"].pop("1")  # simulate prune
        st.pop("retro_seen", None)
        st.pop("retro_cursor", None)
        state.save_state(sp, st)
        _run(forge, monkeypatch, sp, [])
        assert len(forge.posts) == 1 and len(forge.updates) == 1  # edit, not duplicate

    def test_deferred_retried_cursor_holds(self, tmp_path, monkeypatch):
        from fl4write.models import ReviewDoc

        forge = RetroForge()
        forge.merged = [
            make_pr(number=1, merged_at="2026-08-15T12:01:00Z"),
            make_pr(number=2, merged_at="2026-08-15T12:02:00Z"),
        ]
        sp = tmp_path / "s.json"
        _seed_watermark(sp)
        c = make_config()

        def fake_analyze(pr, files, text, config):
            return ReviewDoc(pr=pr, findings=[FRESH])

        monkeypatch.setattr("fl4write.engine.adapter_for", lambda b: forge)
        monkeypatch.setattr("fl4write.analyzer.analyze", fake_analyze)

        def diff_fails_pr1_first_time(pr):
            return None if pr.number == 1 else ({"x.py"}, "d")

        r1 = run_cycle(c, sp, get_diff=diff_fails_pr1_first_time)
        assert r1.retro_reviewed == 1  # PR 2 (newer) done; PR 1 deferred
        r2 = run_cycle(c, sp, get_diff=lambda pr: ({"x.py"}, "d"))
        assert r2.retro_reviewed == 1  # PR 1 retried and completed
        assert [n for n, _ in forge.posts] == [2, 1]

    def test_completion_is_terminal(self, tmp_path, monkeypatch):
        forge = RetroForge()
        forge.merged = [make_pr(number=1, merged_at="2026-08-15T12:00:00Z")]
        sp = tmp_path / "s.json"
        _seed_watermark(sp)
        _run(forge, monkeypatch, sp, [])
        r = _run(forge, monkeypatch, sp, [])
        assert any("retro audit complete" in a for a in r.alerts)
        assert state.load_state(sp)["retro_complete"]
        forge.merged.append(make_pr(number=9, merged_at="2026-08-16T00:00:00Z"))
        r3 = _run(forge, monkeypatch, sp, [FRESH])
        assert r3.retro_reviewed == 0 and forge.posts == []  # never restarts

    def test_disabled_default_never_lists(self, tmp_path, monkeypatch):
        forge = RetroForge()
        forge.merged = [make_pr(number=1, merged_at="2026-08-15T12:00:00Z")]
        sp = tmp_path / "s.json"
        _seed_watermark(sp)
        _run(forge, monkeypatch, sp, [FRESH], retro_audit={"enabled": False})
        assert forge.posts == []


# ------------------------------------------------- Forgejo-native diff
def _gitea():
    return ForgejoAdapter(cfg.ForgeBinding(role="primary", api_base="https://g.example/api/v1", token_env="FT"))


class TestForgejoDiff:
    def test_parses_unified_diff(self):
        g = _gitea()
        g._call_text = lambda m, p, _retry=True: (
            "diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n+pass\n"
            "diff --git a/y.rs b/y.rs\n--- a/y.rs\n+++ b/y.rs\n+fn main(){}"
        )
        out = g.get_pr_diff("o/r", 7)
        assert out is not None and out[0] == {"x.py", "y.rs"} and "diff --git" in out[1]

    def test_error_page_is_none_not_empty(self):
        g = _gitea()
        g._call_text = lambda m, p, _retry=True: "<html>502 Bad Gateway</html>"
        assert g.get_pr_diff("o/r", 7) is None  # never a vacuous diff

    def test_transport_failure_is_none(self):
        g = _gitea()

        def boom(m, p, _retry=True):
            raise ForgeError("forgejo GET .diff: HTTP 500")

        g._call_text = boom
        assert g.get_pr_diff("o/r", 7) is None

    def test_empty_body_is_none(self):
        g = _gitea()
        g._call_text = lambda m, p, _retry=True: ""
        assert g.get_pr_diff("o/r", 7) is None


class TestRetroConfigKnobs:
    def test_bounds(self):
        with pytest.raises(Exception):
            make_config(retro_audit={"enabled": True, "lookback_days": 0})
        with pytest.raises(Exception):
            make_config(retro_audit={"enabled": True, "max_per_cycle": 99})
        with pytest.raises(Exception):
            make_config(retro_audit={"enbled": True})
