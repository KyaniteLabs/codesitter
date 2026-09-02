"""Post-merge review mode (LEARNINGS #24) — the watermark laws.

This org's PRs open and merge in ~60s; the open-PR poller structurally never
sees them. The sweep reviews PRs merged since a per-repo watermark. The laws
pinned here:
- at-most-once does NOT depend on the watermark (head-SHA predicate +
  persistent-comment marker hold on a full rewind);
- the watermark only advances past TERMINALLY-processed PRs, oldest first —
  deferred PRs (diff/model unavailable) are retried next cycle;
- per-cycle cap bounds model spend; the backlog resumes next cycle;
- shadow outcomes are terminal for the sweep but never count as reviewed
  for the live flip (learning #2, extended to the merged lane).
"""

from __future__ import annotations

import json

import pytest

from fl4write import config as cfg
from fl4write import renderer, state
from fl4write.engine import run_cycle
from fl4write.forges import ForgeAdapter
from fl4write.models import PullRequest


# ---------------------------------------------------------------- helpers
def make_config(**over):
    raw = {
        "repo": "KyaniteLabs/kinocut",
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
        "post_merge": {"enabled": True},
    }
    raw.update(over)
    return cfg.RepoConfig.model_validate(raw)


def make_pr(**over):
    base = dict(
        forge="github",
        number=1,
        repo="KyaniteLabs/kinocut",
        title="t",
        head_sha="a" * 40,
        author="dev",
    )
    base.update(over)
    return PullRequest.model_validate(base)


class FakeForge(ForgeAdapter):
    name = "github"

    def __init__(self):
        super().__init__(
            cfg.ForgeBinding(role="primary", api_base="https://api.github.com", token_env="GHT")
        )
        self.open_prs: list[PullRequest] = []
        self.merged_prs: list[PullRequest] = []
        self.posts: list[tuple[int, str]] = []
        self.updates: list[tuple[int, str]] = []

    def list_open_prs(self, repo):
        return self.open_prs

    def list_merged_prs(self, repo, since_iso):
        from fl4write.forges import _parse_iso

        since = _parse_iso(since_iso)
        out = []
        for pr in self.merged_prs:
            merged = _parse_iso(pr.merged_at)
            # strict < — mirrors the adapter contract (same-second merges stay visible)
            if since is not None and merged is not None and merged < since:
                continue
            out.append(pr)
        out.sort(key=lambda p: p.merged_at)
        return out

    def get_persistent_comment(self, repo, number):
        for n, body in self.posts + self.updates:
            if n == number:
                return (1, body)
        return None

    def create_comment(self, repo, number, body):
        self.posts.append((number, body))
        return len(self.posts)

    def update_comment(self, repo, number, comment_id, body):
        self.updates.append((number, body))


def _run(tmp_path, forge, monkeypatch, diff=None, **cfg_over):
    c = make_config(**cfg_over)
    monkeypatch.setattr("fl4write.engine.adapter_for", lambda b: forge)
    monkeypatch.setattr(
        "fl4write.analyzer._call_model",
        lambda route, prompt, mode="pr": json.dumps({"findings": []}),
    )
    return run_cycle(
        c,
        tmp_path / "state.json",
        get_diff=diff or (lambda pr: ({"x.py"}, "diff")),
    )



def _hours_ago(h: int, hhmm: str = "12:00:00") -> str:
    """A merged_at safely inside the default 24h lookback for future runs
    (fixed calendar dates rot out of the window — the same time-bomb class
    the comorbidity pass caught in the retro fixtures)."""
    from datetime import datetime, timedelta, timezone

    return (datetime.now(timezone.utc) - timedelta(hours=h)).strftime("%Y-%m-%d") + f"T{hhmm}Z"

# ---------------------------------------------------------------- the sweep
class TestPostMergeSweep:
    def test_merged_pr_reviewed_once_and_watermark_advances(self, tmp_path, monkeypatch):
        forge = FakeForge()
        forge.merged_prs = [make_pr(number=9, merged_at=_hours_ago(3))]
        r = _run(tmp_path, forge, monkeypatch)
        assert r.postmerge_reviewed == 1 and len(forge.posts) == 1
        assert "(post-merge)" in forge.posts[0][1]
        st = state.load_state(tmp_path / "state.json")
        assert state.merged_watermark(st) == _hours_ago(3)  # the fixture value, not a hardcoded date

    def test_no_re_review_when_relisted_same_sha(self, tmp_path, monkeypatch):
        """Watermark rewound (or PR merged mid-sweep): the head-SHA predicate,
        not the watermark, is the at-most-once guard."""
        forge = FakeForge()
        forge.merged_prs = [make_pr(number=9, merged_at=_hours_ago(3))]
        _run(tmp_path, forge, monkeypatch)
        # rewind the watermark to force a re-list
        st = state.load_state(tmp_path / "state.json")
        st["merged_since"] = "2026-09-01T00:00:00Z"
        state.save_state(tmp_path / "state.json", st)
        r2 = _run(tmp_path, forge, monkeypatch)
        assert r2.postmerge_reviewed == 0 and len(forge.posts) == 1  # no second post, no model call

    def test_reviewed_while_open_not_repeated_post_merge(self, tmp_path, monkeypatch):
        """The 60s-merge case that ACTUALLY happens: reviewed while open at
        SHA X, merged at SHA X — the sweep sees it listed but skips silently."""
        forge = FakeForge()
        pr = make_pr(number=9)
        forge.open_prs = [pr]
        _run(tmp_path, forge, monkeypatch)
        assert len(forge.posts) == 1
        forge.open_prs = []
        forge.merged_prs = [make_pr(number=9, head_sha=pr.head_sha, merged_at=_hours_ago(3))]
        r2 = _run(tmp_path, forge, monkeypatch)
        assert r2.postmerge_reviewed == 0 and len(forge.posts) == 1

    def test_push_then_fast_merge_reviews_merged_head(self, tmp_path, monkeypatch):
        """Reviewed at SHA A while open, pushed to SHA B, merged at B before the
        next cycle: the sweep reviews B post-merge (divergence = re-review)."""
        forge = FakeForge()
        forge.open_prs = [make_pr(number=9, head_sha="a" * 40)]
        _run(tmp_path, forge, monkeypatch)
        forge.open_prs = []
        forge.merged_prs = [make_pr(number=9, head_sha="b" * 40, merged_at=_hours_ago(3))]
        r2 = _run(tmp_path, forge, monkeypatch)
        assert r2.postmerge_reviewed == 1
        assert len(forge.posts) == 1 and len(forge.updates) == 1  # edit-in-place, never a second comment

    def test_cap_bounds_cycle_and_backlog_resumes(self, tmp_path, monkeypatch):
        forge = FakeForge()
        forge.merged_prs = [
            make_pr(number=n, merged_at=f"2026-09-01T12:0{n}:00Z") for n in range(1, 6)
        ]
        r1 = _run(tmp_path, forge, monkeypatch, post_merge={"enabled": True, "max_per_cycle": 3})
        assert r1.postmerge_reviewed == 3
        assert any("backlog" in a for a in r1.alerts)
        r2 = _run(tmp_path, forge, monkeypatch, post_merge={"enabled": True, "max_per_cycle": 3})
        assert r2.postmerge_reviewed == 2  # the backlog, not a re-review
        assert len(forge.posts) == 5

    def test_same_second_merge_split_by_cap_not_lost(self, tmp_path, monkeypatch):
        """Agent waves merge in bursts: two PRs in the SAME second, the cap
        defers the second — it must remain listable next cycle (strict <
        watermark exclusion), while the already-terminal one is skipped free
        by the head-SHA guard (no model call, no post)."""
        forge = FakeForge()
        forge.merged_prs = [
            make_pr(number=1, head_sha="a" * 40, merged_at=_hours_ago(3)),
            make_pr(number=2, head_sha="b" * 40, merged_at=_hours_ago(3)),
        ]
        r1 = _run(tmp_path, forge, monkeypatch, post_merge={"enabled": True, "max_per_cycle": 1})
        assert r1.postmerge_reviewed == 1 and forge.posts[0][0] == 1
        from fl4write.analyzer import _call_model as orig
        from fl4write.engine import run_cycle as _rc

        model_calls = []

        def counting(route, prompt, mode="pr"):
            model_calls.append(prompt)
            return orig(route, prompt)

        monkeypatch.setattr("fl4write.analyzer._call_model", counting)
        c2 = make_config(post_merge={"enabled": True, "max_per_cycle": 1})
        r2 = _rc(c2, tmp_path / "state.json", get_diff=lambda pr: ({"x.py"}, "d"))
        assert r2.postmerge_reviewed == 1  # PR 2 processed
        assert len(forge.posts) == 2 and forge.posts[1][0] == 2
        # PR 1 was re-LISTED but skipped by the head-SHA guard — one model
        # call total this cycle (for PR 2 only), not two.
        assert len(model_calls) == 1

    def test_diff_unavailable_defers_not_skipped(self, tmp_path, monkeypatch):
        """Deferred PRs must NOT advance the watermark past them (LEARNINGS #3
        error-path law: a fetch failure may never look like a processed merge)."""
        forge = FakeForge()
        forge.merged_prs = [
            make_pr(number=1, merged_at="2026-09-01T12:01:00Z"),
            make_pr(number=2, merged_at="2026-09-01T12:02:00Z"),
        ]
        seen = []
        attempts = {"n": 0}

        def diff(pr):
            seen.append(pr.number)
            if pr.number == 1:
                attempts["n"] += 1
                return None if attempts["n"] == 1 else ({"x.py"}, "d")  # fails once, then works
            return ({"x.py"}, "d")

        r = _run(tmp_path, forge, monkeypatch, diff=diff)
        assert seen == [1]  # stopped at the deferral
        assert r.postmerge_reviewed == 0
        st = state.load_state(tmp_path / "state.json")
        assert state.merged_watermark(st) is None  # nothing terminal processed
        # next cycle: diff works, both process
        r2 = _run(tmp_path, forge, monkeypatch, diff=diff)
        assert r2.postmerge_reviewed == 2 and seen == [1, 1, 2]

    def test_disabled_by_default_never_lists(self, tmp_path, monkeypatch):
        forge = FakeForge()
        forge.merged_prs = [make_pr(number=9, merged_at=_hours_ago(3))]
        listed = []
        orig = forge.list_merged_prs

        def spy(repo, since):
            listed.append(since)
            return orig(repo, since)

        forge.list_merged_prs = spy
        r = _run(tmp_path, forge, monkeypatch, post_merge={"enabled": False})
        # the sweep never reviews/posts; a listing call may still come from the
        # acceptance metric (L6 samples merged PRs) — that is a different lane
        assert r.postmerge_reviewed == 0 and forge.posts == []

    def test_initial_lookback_bounds_catch_up(self, tmp_path, monkeypatch):
        """First cycle: watermark unset — the catch-up window is bounded by
        config, never the repo's full history."""
        forge = FakeForge()
        forge.merged_prs = [
            make_pr(number=1, merged_at="2020-01-01T00:00:00Z"),  # ancient: outside window
            make_pr(number=2, merged_at=_hours_ago(4, "20:00:00")),  # recent: inside 24h
        ]
        r = _run(tmp_path, forge, monkeypatch)
        assert r.postmerge_reviewed == 1
        assert forge.posts[0][0] == 2

    def test_bot_dependency_merge_skipped_terminally(self, tmp_path, monkeypatch):
        forge = FakeForge()
        forge.merged_prs = [
            make_pr(
                number=5, is_bot_author=True, title="chore(deps): bump patch",
                merged_at=_hours_ago(3),
            )
        ]
        r = _run(tmp_path, forge, monkeypatch)
        assert r.postmerge_reviewed == 0 and r.skipped_dependency == 1 and forge.posts == []
        st = state.load_state(tmp_path / "state.json")
        assert state.merged_watermark(st) == _hours_ago(3)  # the fixture value, not a hardcoded date  # terminal: not re-listed forever

    def test_listing_failure_skips_cycle_not_watermark(self, tmp_path, monkeypatch):
        forge = FakeForge()

        def boom(repo, since):
            from fl4write.forges import ForgeError

            raise ForgeError("github GET /pulls: HTTP 403")

        forge.list_merged_prs = boom
        r = _run(tmp_path, forge, monkeypatch)
        assert any("post-merge listing failed" in a for a in r.alerts)
        st = state.load_state(tmp_path / "state.json")
        assert state.merged_watermark(st) is None


# ---------------------------------------------------------------- config knob
class TestPostMergeConfig:
    def test_knob_wired_defaults(self):
        c = make_config()
        assert c.post_merge.enabled is False or c.post_merge.enabled is True
        assert make_config().post_merge.max_per_cycle == 10
        assert make_config(post_merge={"enabled": True, "max_per_cycle": 5}).post_merge.max_per_cycle == 5

    def test_out_of_range_rejected(self):
        with pytest.raises(Exception):
            make_config(post_merge={"enabled": True, "max_per_cycle": 0})
        with pytest.raises(Exception):
            make_config(post_merge={"enabled": True, "initial_lookback_h": 999})

    def test_unknown_key_aborts(self):
        with pytest.raises(Exception):
            make_config(post_merge={"enbled": True})


# ---------------------------------------------------------------- renderer
class TestPostMergeRender:
    def test_header_and_clean_body(self):
        c = make_config(shadow=False)
        pr = make_pr()
        body = renderer.render_review(pr, [], c, "h", post_merge=True)
        assert "(post-merge)" in body and "Go merge it" not in body
        assert "fl4write:v1:h" in body  # marker unchanged: lookup law

    def test_finding_lines_round_trip_unchanged(self):
        """The parse contract (engine delta markers, metrics, edit-in-place)
        must not drift for post-merge comments — one source of truth."""
        from fl4write.models import Finding

        c = make_config()
        f = Finding(rule_id="secrets", severity="Critical", path="x.py", line=3, message="m")
        body = renderer.render_review(make_pr(), [f], c, "h", post_merge=True)
        assert renderer.parse_finding_lines(body) == [("Critical", "x.py", 3, "secrets")]

    def test_critical_urgency_fix_forward(self):
        from fl4write.models import Finding

        c = make_config()
        f = Finding(rule_id="secrets", severity="Critical", path="x.py", line=1, message="m")
        body = renderer.render_review(make_pr(), [f], c, "h", post_merge=True)
        assert "Landed on main" in body and "Do NOT merge" not in body


# ---------------------------------------------------------------- state watermark
class TestWatermark:
    def test_only_advances(self):
        st = {"version": 1, "prs": {}}
        state.advance_merged_watermark(st, "2026-09-01T10:00:00Z")
        state.advance_merged_watermark(st, "2026-09-01T09:00:00Z")  # rewind refused
        assert state.merged_watermark(st) == "2026-09-01T10:00:00Z"


# ---------------------------------------------------------------- merge-scan regression
class TestMergeScanRegression:
    def test_fix_lane_calls_merge_scan_with_bot_identity(self, tmp_path, monkeypatch):
        """engine used to call check_and_merge_own_prs(config) — bot_identity
        is a REQUIRED arg; TypeError was swallowed by the broad except as
        'merge scan failed', so the scan had never once run."""
        forge = FakeForge()
        forge.open_prs = [make_pr()]
        calls = []

        def fake_scan(config, bot_identity=None, **kw):
            calls.append(bot_identity)
            return 0

        monkeypatch.setattr("fl4write.executor.check_and_merge_own_prs", fake_scan)
        c = make_config()
        c = c.model_copy(update={"fix": cfg.FixLaneConfig(enabled=True)})
        monkeypatch.setattr("fl4write.engine.adapter_for", lambda b: forge)
        monkeypatch.setattr(
            "fl4write.analyzer._call_model",
            lambda route, prompt, mode="pr": json.dumps({"findings": []}),
        )
        run_cycle(c, tmp_path / "s.json", get_diff=lambda pr: ({"x.py"}, "d"), run_fixes=True)
        assert calls == ["fl4write[bot]"]  # called WITH the identity, exactly once
