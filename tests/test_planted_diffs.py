"""Planted-diff eval corpus (Sol-B1, L3): the standing eval set for detection
quality. Each case = a REAL planted bug + its failing test. The deterministic
layer (verify_diff_tests) must catch 100% by construction; the MODEL layer
(analyze) recall is measured live when FL4WRITE_EVAL=1 (needs keys) — the
quality loop's Q1 metric reads from here.

Evidence lineage: case 1 is the Epoch #198 planted bug — the diff both M3 and
deepseek each missed twice, which built verify_tests. New cases get added as
new miss-classes appear in the wild (the corpus grows from production).
"""

from __future__ import annotations

import os

import pytest

from fl4write import config as cfg

CASES = [
    {
        "id": "median-unsorted",
        "origin": "Epoch #198 E2E (2026-09-02): missed by M3 x2 + deepseek x2",
        "impl": "fl4write-proof/proof_target.py",
        "impl_code": (
            "def median(values):\n"
            "    n = len(values)\n"
            "    if n == 0:\n"
            "        raise ValueError('empty')\n"
            "    if n % 2 == 1:\n"
            "        return values[n // 2]\n"
            "    return (values[n // 2 - 1] + values[n // 2]) / 2\n"
        ),
        "test": "fl4write-proof/test_proof_target.py",
        "test_code": (
            "from proof_target import median\n\n\n"
            "def test_median_odd_unsorted():\n"
            "    assert median([5.0, 1.0, 3.0]) == 3.0\n"
        ),
    },
    {
        "id": "off-by-one-boundary",
        "origin": "class: boundary indexing (predicted by comorbidity #3 M3)",
        "impl": "paginate.py",
        "impl_code": (
            "def page(items, page_no, size):\n"
            "    'Return slice for 1-based page_no.'\n"
            "    start = page_no * size\n"
            "    return items[start:start + size]\n"
        ),
        "test": "test_paginate.py",
        "test_code": (
            "from paginate import page\n\n\n"
            "def test_first_page():\n"
            "    assert page(['a', 'b', 'c'], 1, 2) == ['a', 'b']\n"
        ),
    },
    {
        "id": "inverted-comparison",
        "origin": "class: comparison polarity",
        "impl": "threshold.py",
        "impl_code": (
            "def is_critical(sev_score):\n"
            "    'Critical when score >= 90.'\n"
            "    return sev_score < 90\n"
        ),
        "test": "test_threshold.py",
        "test_code": (
            "from threshold import is_critical\n\n\n"
            "def test_critical():\n"
            "    assert is_critical(95) is True\n"
        ),
    },
]


def _config():
    return cfg.RepoConfig.model_validate({
        "repo": "o/r",
        "forges": {"github": {"role": "primary", "api_base": "https://api.github.com", "token_env": "GHT"}},
        "model": {"endpoint": "http://m/v1/chat/completions", "model": "t", "key_env": "MK"},
        "review": {"tests": "Changes to logic ship with tests; tests stay green."},
        "severity_vocab": ["Critical", "Major", "Minor", "Nit"],
    })


class TestDeterministicLayer:
    """verify_diff_tests must catch 100% of the corpus — by construction."""

    @pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
    def test_verify_catches_every_planted_bug(self, case, tmp_path, monkeypatch):
        impl_path = tmp_path / case["impl"]
        impl_path.parent.mkdir(parents=True, exist_ok=True)
        impl_path.write_text(case["impl_code"])
        (tmp_path / case["test"]).write_text(case["test_code"])
        (tmp_path / "conftest.py").write_text("")  # rootdir anchor
        (tmp_path / "pytest.ini").write_text(
            "[pytest]\npython_files = test_*.py\n")  # sys.path = rootdir
        import subprocess as sp
        from types import SimpleNamespace as NS

        real_run = sp.run
        import fl4write.executor as ex
        from fl4write.models import PullRequest

        def fake_run(cmd, cwd=None, timeout=120, env=None, **kw):
            if cmd[:2] == ["python3", "-m"]:
                # the diff's test runs against the diff's code, FOR REAL,
                # in tmp_path where the case files live. env keeps the REAL
                # PATH — a narrowed PATH resolved python3 to a bare system
                # interpreter without pytest, and the old code minted false
                # deterministic Criticals from that infra failure (the exact
                # class F11-B005 closes)
                run_env = {k: v for k, v in os.environ.items()
                           if k not in ("PYTHONPATH", "VIRTUAL_ENV")}
                run_env["PYTHONDONTWRITEBYTECODE"] = "1"
                return real_run(cmd, cwd=str(tmp_path), timeout=timeout,
                                env=run_env, capture_output=True, text=True)
            if cmd[0] == "git":
                return NS(returncode=0, stdout="ok", stderr="")  # fetch/checkout stubbed
            return real_run(cmd, cwd=cwd, timeout=timeout, capture_output=True, text=True)

        monkeypatch.setattr(ex, "_run", fake_run)
        monkeypatch.setattr(ex, "_push_token_env",
                            lambda wd, tok: dict(os.environ))
        monkeypatch.setattr(ex, "_drop_askpass", lambda env: None)
        pr = PullRequest(forge="github", number=1, repo="o/r", head_sha="a" * 40)
        finding = ex.verify_diff_tests(pr, _config(), [case["test"]])
        assert finding is not None and finding.severity == "Critical", (
            f"deterministic layer missed planted bug {case['id']}"
        )
        assert case["test"] in finding.message  # auditable evidence (Sol-B2)


@pytest.mark.skipif(not os.environ.get("FL4WRITE_EVAL"), reason="live eval (needs model keys)")
class TestModelLayerLive:
    """Model recall on the corpus — the Q1 metric, measured when run with
    FL4WRITE_EVAL=1. Threshold per the #5 charter: >= 8/10 recall eventually;
    today's baseline was 0/4 — this suite makes the number reproducible."""

    @pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
    def test_model_finds_it(self, case, monkeypatch):
        from fl4write.analyzer import analyze
        from fl4write.models import PullRequest

        diff_text = (
            f"--- a/{case['impl']}\n+++ b/{case['impl']}\n"
            + "".join(f"+{ln}" for ln in case["impl_code"].splitlines(keepends=True))
            + f"--- a/{case['test']}\n+++ b/{case['test']}\n"
            + "".join(f"+{ln}" for ln in case["test_code"].splitlines(keepends=True))
        )
        pr = PullRequest(forge="github", number=1, repo="o/r", head_sha="a" * 40)
        doc = analyze(pr, {case["impl"], case["test"]}, diff_text, _config())
        assert doc.findings, f"MODEL LAYER MISS: {case['id']} ({case['origin']})"
        severities = [f.severity for f in doc.findings]
        assert any(s in ("Critical", "Major") for s in severities), severities
