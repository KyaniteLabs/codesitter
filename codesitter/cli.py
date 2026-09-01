"""Cron adapter — the v1 trigger. One cycle for one configured repo.

Usage: python3 -m codesitter.cli <config.yaml> [--live]

Diff fetching (the required get_diff): gh pr diff for GitHub-primary repos,
git diff for Forgejo-primary when gh can't reach it. Keys are read at runtime
from the environment, falling back to the org config store for model routes
(never inlined). --live flips shadow off; default is shadow (log only).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from .config import load_config
from .engine import run_cycle
from .models import PullRequest


def _gh(*args: str) -> str:
    out = subprocess.run(  # noqa: S603,607 - fixed argv, gh-managed auth
        ["gh", *args], capture_output=True, text=True, timeout=120
    )
    if out.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:2])} failed: {out.stderr[-200:]}")
    return out.stdout


def _org_model_keys() -> None:
    """Populate model key envs from the org config store if unset (runtime
    key reading — keys are never inlined into prompts or configs)."""
    store = Path.home() / ".sinter/config.json"
    mapping = {
        "CODESITTER_QWEN_KEY": ("fallbacks", "harness", 0, "apiKey"),
        "CODESITTER_DEEPSEEK_KEY": None,  # filled below via providers.deepinfra
    }
    try:
        cfg = json.loads(store.read_text())
    except (OSError, json.JSONDecodeError):
        return
    if not os.environ.get("CODESITTER_QWEN_KEY"):
        try:
            os.environ["CODESITTER_QWEN_KEY"] = cfg["fallbacks"]["harness"][0]["apiKey"]
        except (KeyError, IndexError, TypeError):
            pass
    if not os.environ.get("CODESITTER_DEEPSEEK_KEY"):
        m = re.search(r'"deepinfra"[^}]*?"apiKey":\s*"([^"]+)"', json.dumps(cfg))
        if m:
            os.environ["CODESITTER_DEEPSEEK_KEY"] = m.group(1)
    del mapping


def make_get_diff(repo: str):
    def get_diff(pr: PullRequest) -> tuple[set[str], str]:
        try:
            text = _gh("pr", "diff", str(pr.number), "--repo", repo)
        except RuntimeError:
            # Oversized diffs (GitHub 406 >20k lines) — fall back to the file
            # list via the API and a truncated diff from the first file only.
            try:
                files_json = _gh("api", f"repos/{repo}/pulls/{pr.number}/files?per_page=100")
                names = {f["filename"] for f in json.loads(files_json) if isinstance(files_json, list) and f}
                return names, "(diff too large for API; reviewed from file list only)"
            except Exception:
                return set(), ""
        files = set(re.findall(r"^\+\+\+ b/(.+)$", text, re.MULTILINE))
        return files, text

    return get_diff


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python3 -m codesitter.cli <config.yaml> [--live]", file=sys.stderr)
        return 2
    live = "--live" in sys.argv
    run_fixes = "--fixes" in sys.argv
    run_issues = "--issues" in sys.argv
    config = load_config(sys.argv[1])
    if live:
        config = config.model_copy(update={"shadow": False})
    # GitHub App auth: every interaction signed as kyanitelabs[bot]
    try:
        from .appauth import install_token_to_env

        install_token_to_env()
    except Exception as exc:
        import sys

        print(f"WARNING: GitHub App auth failed ({exc}); falling back to PAT", file=sys.stderr)
    _org_model_keys()
    state_path = Path.home() / ".codesitter" / f"{config.repo.replace('/', '__')}.state.json"
    report = run_cycle(
        config,
        state_path,
        get_diff=make_get_diff(config.repo),
        run_fixes=run_fixes,
        run_issues=run_issues,
    )
    # Config-presence surveillance (learning 16): racing branches have twice
    # silently reverted adoptions; every cycle verifies the IN-REPO config
    # still exists on main and alerts if the adoption was lost.
    probe = subprocess.run(  # noqa: S603,607
        ["gh", "api", f"repos/{config.repo}/contents/.codesitter.yaml", "--jq", ".name"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if probe.returncode != 0:
        print(f"ALERT: adoption lost — .codesitter.yaml missing on {config.repo} main (re-adopt)")
    print(
        f"codesitter cycle: repo={report.repo} scanned={report.scanned} "
        f"reviewed={report.reviewed} shadow={config.shadow} "
        f"dep_skipped={report.skipped_dependency} model_down={report.model_unavailable} "
        f"gate_dropped={report.gatekeeper_dropped} fix_prs={report.fix_prs_opened} "
        f"fix_merged={report.fix_prs_merged} issues_triaged={report.issues_triaged} "
        f"acceptance={report.acceptance.get('rate', 'n/a')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
