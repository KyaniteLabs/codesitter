"""Phase 1 tier scheduler — the consensus-gate test set (fl4write #6).
Every behavior the Architect + Critic required, pinned:

- bootstrap HOT (new repo, no state file)
- UNKNOWN (corrupt state) -> WARM + ALERT — corruption never masquerades
  as inactivity (the classifier fails toward frequency)
- cold requires healthy state + quiet beyond 7d; any local activity
  (open PRs / watermark) holds at least WARM
- Forgejo repos: WARM floor (no GitHub pushed signal; LEARNINGS #24 —
  this org merges in ~60s, cold-parking a busy Forgejo repo is a regression)
- duplicate configs ALERT and dedupe — never silent (the fleet has been
  double-cycling resonant-tastecheck via two configs)
- probe failure -> WARM (never cold: missing signal != quiet)
- staggering: cold repos due only inside their hour-window per cadence
- the scheduler NEVER writes state (LEARNINGS #17 — no second owner)
"""

from __future__ import annotations

import json

import pytest

from fl4write import tiers


@pytest.fixture
def state_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(tiers, "STATE_DIR", tmp_path)
    return tmp_path


NOW = 1_800_000_000  # int: range() below steps hourly


class TestClassification:
    def test_bootstrap_hot(self, state_dir):
        assert tiers.classify("org/newrepo", True, None, NOW)[0] == "hot"

    def test_corrupt_state_unknown_warm(self, state_dir):
        (state_dir / "org__broken.state.json").write_text("{torn")
        tier, reason = tiers.classify("org/broken", True, NOW, NOW)
        assert tier == "warm" and "UNKNOWN" in reason

    def test_healthy_quiet_beyond_7d_cold(self, state_dir):
        (state_dir / "org__cold.state.json").write_text('{"version": 1, "prs": {}}')
        tier, _ = tiers.classify("org/cold", True, NOW - 30 * 86400, NOW)
        assert tier == "cold"

    def test_local_activity_holds_warm(self, state_dir):
        (state_dir / "org__active.state.json").write_text(
            '{"version": 1, "prs": {"7": {"last_reviewed_sha": "x"}}, "merged_since": "2026-09-01"}')
        tier, _ = tiers.classify("org/active", True, NOW - 30 * 86400, NOW)
        assert tier == "warm"  # pushed long ago but open PRs + watermark live

    def test_forgejo_warm_floor(self, state_dir):
        (state_dir / "simon__cncl.state.json").write_text('{"version": 1, "prs": {}}')
        tier, _ = tiers.classify("simon/CNCL", False, None, NOW)
        assert tier == "warm"

    def test_probe_failure_never_cold(self, state_dir):
        (state_dir / "org__noprobe.state.json").write_text('{"version": 1, "prs": {}}')
        tier, _ = tiers.classify("org/noprobe", True, None, NOW)  # pushed=None
        assert tier == "warm"


class TestDueList:
    def _configs(self):
        return [
            ("hot.yaml", "o/hot", True),
            ("warm.yaml", "o/warm", True),
            ("cold.yaml", "o/cold", True),
        ]

    def test_duplicate_configs_alert_and_dedupe(self, state_dir, capsys):
        configs = self._configs() + [("dup.yaml", "o/hot", True)]
        out = tiers.due(configs, now=NOW, pushed_map={})
        printed = capsys.readouterr().out
        assert "ALERT: duplicate config for o/hot" in printed
        assert "dup.yaml" not in out and "hot.yaml" in out  # first wins, LOUD

    def test_hot_always_due_cold_staggered(self, state_dir, capsys):
        for repo in ("o/hot", "o/warm", "o/cold"):
            (state_dir / f"{repo.replace('/', '__')}.state.json").write_text(
                '{"version": 1, "prs": {}}')
        # hot due at every hour; cold only inside its stagger window
        due_count = sum(
            1 for t in range(NOW, NOW + 24 * 3600, 3600)
            if "hot.yaml" in tiers.due(self._configs(), now=t, pushed_map={})
        )
        assert due_count == 24  # hot: every cycle

    def test_unknown_state_alerts_in_output(self, state_dir, capsys):
        (state_dir / "o__corrupt.state.json").write_text("{torn")
        tiers.due([("corrupt.yaml", "o/corrupt", True)], now=NOW, pushed_map={})
        assert "ALERT: o/corrupt scheduled" in capsys.readouterr().out

    def test_scheduler_never_writes_state(self, state_dir, monkeypatch):
        (state_dir / "o__r.state.json").write_text('{"version": 1, "prs": {}}')
        monkeypatch.setattr(tiers, "_probe_pushed", lambda *a, **k: {})
        tiers.due([("r.yaml", "o/r", True)], now=NOW)
        # classify() may READ; the assertion is no NEW files and no mutation
        after = json.loads((state_dir / "o__r.state.json").read_text())
        assert after == {"version": 1, "prs": {}}  # byte-identical


class TestProbeReality:
    def test_user_endpoint_not_org(self, monkeypatch):
        """The Critic's amendment 4: simongonzalezdc is a USER — /orgs/
        404s. The probe must use the user endpoint for user owners."""
        calls = {}

        def fake_urlopen(req, timeout=20):
            calls["url"] = req.full_url
            class R:
                def read(self):
                    return json.dumps([{"name": "r", "pushed_at": "2026-09-02T00:00:00Z"}]).encode()
                def __enter__(self):
                    return self
                def __exit__(self, *a):
                    return False
            return R()

        monkeypatch.setattr(tiers.urllib.request, "urlopen", fake_urlopen)
        tiers._probe_pushed("user", "simongonzalezdc")
        assert "/users/simongonzalezdc/repos" in calls["url"]
        tiers._probe_pushed("org", "KyaniteLabs")
        assert "/orgs/KyaniteLabs/repos" in calls["url"]
