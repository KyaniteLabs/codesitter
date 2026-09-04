"""Comorbidity-check #1 remediation pins (fl4write #3, 2026-09-01).

The probe that followed the merge-scan fix found three surfaces with ZERO
test references — each one a place where a silent feature-death or a security
regression could land without a red test:
- acceptance_snapshot: the metric the six-lane audit found structurally-dead
  (0% forever) — unpinned, it could regress to n/a silently again;
- _sandbox_env: the lethal-trifecta guard (model-run tests must NEVER see
  tokens) — an allowlist edit would otherwise fail nothing;
- fixlane.escalate: the human-escalation surface — dead escalation = silent
  fix-lane stops.
"""

from __future__ import annotations

import tempfile

from fl4write import config as cfg
from fl4write import fixlane, metrics
from fl4write.forges import ForgeAdapter
from fl4write.models import Finding, PullRequest


def _config(repo="KyaniteLabs/kinocut"):
    return cfg.RepoConfig.model_validate({
        "repo": repo,
        "forges": {"github": {"role": "primary", "api_base": "https://api.github.com", "token_env": "GHT"}},
        "model": {"endpoint": "http://m/v1/chat/completions", "model": "t", "key_env": "MK"},
    })


class MetricForge(ForgeAdapter):
    name = "github"

    def __init__(self, prs, comments):
        super().__init__(cfg.ForgeBinding(role="primary", api_base="https://api.github.com", token_env="GHT"))
        self.prs = prs
        self.comments = comments  # {pr_number: [(comment_id, body)]}

    def list_open_prs(self, repo):
        return self.prs

    def get_persistent_comment(self, repo, number):
        for cid, body in self.comments.get(number, []):
            return cid, body
        return None


def _pr(n):
    return PullRequest(forge="github", number=n, repo="KyaniteLabs/kinocut", head_sha="a" * 40)


class TestAcceptanceSnapshot:
    def test_counts_findings_and_resolved(self):
        body = (
            "### 🟠 Major — `x.py:3` — `tests`\nmsg\n"
            "- ✅ `~y.py:9` (security)\n"
        )
        forge = MetricForge([_pr(1)], {1: [(10, body)]})
        snap = metrics.acceptance_snapshot(forge, _config())
        assert snap["total"] == 2  # one live finding + one resolved
        assert snap["addressed"] >= 1  # the resolved one
        assert snap["rate"].endswith("%")

    def test_pr_without_comment_excluded(self):
        forge = MetricForge([_pr(1), _pr(2)], {1: [(10, "### 🟠 Major — `x.py:3` — `tests`\nm")]})
        snap = metrics.acceptance_snapshot(forge, _config())
        assert snap["total"] == 1  # PR 2 has no comment: out of the denominator

    def test_finding_lines_only_when_present(self):
        forge = MetricForge([_pr(1)], {1: [(10, "clean review")]})
        snap = metrics.acceptance_snapshot(forge, _config())
        assert snap["total"] == 0 and snap["rate"] == "n/a"


class TestSandboxEnv:
    def test_tokens_never_in_sandbox_env(self, monkeypatch):
        from fl4write import executor

        monkeypatch.setenv("CODESITTER_GITHUB_TOKEN", "ghs_secret")
        monkeypatch.setenv("CODESITTER_DEEPSEEK_KEY", "di_secret")
        monkeypatch.setenv("HOME", "/home/simon")
        monkeypatch.setenv("PYTHONPATH", "/custom")
        env = executor._sandbox_env()
        assert "CODESITTER_GITHUB_TOKEN" not in env and "CODESITTER_DEEPSEEK_KEY" not in env
        # MECE round-1 (luna F1-02): executed code must not see the real home
        # (~/.sinter etc.) — HOME points at a throwaway sandbox dir
        assert env.get("HOME") != "/home/simon"
        assert env["HOME"].startswith(tempfile.gettempdir()) or "sandbox-home" in env["HOME"]
        assert set(env) <= set(executor._TEST_ENV_ALLOW) | {"HOME", "PYTHONPATH"}


class TestEscalate:
    def test_body_carries_reason_and_findings(self):
        pr = _pr(7)
        f = Finding(rule_id="tests", severity="Major", path="x.py", line=3, message="no test ships")
        body = fixlane.escalate(pr, [f], "fix depth cap reached (2)")
        assert "fix depth cap" in body and "x.py:3" in body and "no test ships" in body
        assert "stops here" in body  # the not-a-retry contract line
