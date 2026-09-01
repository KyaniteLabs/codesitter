"""Cron adapter — the v1 trigger. One cycle for one configured repo.

Usage: python3 -m fl4write.cli <config.yaml> [--live]

Diff fetching (the required get_diff): gh pr diff for GitHub-primary repos,
git diff for Forgejo-primary when gh can't reach it. Keys are read at runtime
from the environment, falling back to the org config store for model routes
(never inlined). --live flips shadow off; default is shadow (log only).
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import subprocess
import sys
from pathlib import Path

from .config import load_config
from .engine import run_cycle
from .models import PullRequest

log = logging.getLogger("fl4write.cli")


def _gh(*args: str) -> str:
    try:
        out = subprocess.run(  # fixed argv, gh-managed auth

            ["gh", *args], capture_output=True, text=True, timeout=120
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"gh {' '.join(args[:2])} timed out after 120s") from exc
    if out.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:2])} failed: {out.stderr[-200:]}")
    return out.stdout


def _org_model_keys() -> None:
    """Populate model key envs from the org config store if unset (runtime
    key reading — keys are never inlined into prompts or configs)."""
    store = Path.home() / ".sinter/config.json"
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


def make_get_diff(repo: str):
    def get_diff(pr: PullRequest) -> tuple[set[str], str] | None:
        """None = the diff could NOT be fetched. The engine then skips the PR
        WITHOUT marking it reviewed — an empty set here used to ground NOTHING,
        post "🎉 clean" over real findings, and record the SHA as reviewed
        forever (LEARNINGS #3, reborn on the error path — audit C1)."""
        try:
            text = _gh("pr", "diff", str(pr.number), "--repo", repo)
        except RuntimeError:
            # Oversized diffs (GitHub 406 >20k lines) — fall back to the FULL
            # file list via the API (paginated, not just page one).
            try:
                names: set[str] = set()
                page = 1
                while True:
                    files_json = _gh("api", f"repos/{repo}/pulls/{pr.number}/files?per_page=100&page={page}")
                    batch = json.loads(files_json)
                    if not isinstance(batch, list) or not batch:
                        break
                    names |= {f["filename"] for f in batch if isinstance(f, dict) and f.get("filename")}
                    if len(batch) < 100:
                        break
                    page += 1
                if not names:
                    return None
                return names, "(diff too large for API; reviewed from file list only)"
            except (RuntimeError, json.JSONDecodeError) as exc:
                log.warning("diff unavailable for %s#%s: %s", repo, pr.number, exc)
                return None
        files = set(re.findall(r"^\+\+\+ b/(.+)$", text, re.MULTILINE))
        return files, text

    return get_diff


def _install_sigterm_handler() -> None:
    import signal

    def _handler(signum: int, frame: object) -> None:
        raise SystemExit(128 + signum)

    try:
        signal.signal(signal.SIGTERM, _handler)
    except (ValueError, OSError):
        pass


def main() -> int:
    _install_sigterm_handler()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if len(sys.argv) < 2:
        print("usage: python3 -m fl4write.cli <config.yaml> [--live]", file=sys.stderr)
        return 2
    live = "--live" in sys.argv
    run_fixes = "--fixes" in sys.argv
    run_issues = "--issues" in sys.argv
    config = load_config(sys.argv[1])
    if live:
        config = config.model_copy(update={"shadow": False})
    # Diff getter is FORGE-AWARE: GitHub-primary keeps the gh-CLI path;
    # Forgejo-primary uses the adapter's native .diff endpoint (the gh path
    # 404s there — every PR would defer forever, the dead-adapter failure).
    primary_binding = next(b for b in config.forges.values() if b.role == "primary")
    if "api.github.com" in primary_binding.api_base:
        diff_getter = make_get_diff(config.repo)
    else:
        from .forges import adapter_for as _af

        native = _af(primary_binding)

        def diff_getter(pr: PullRequest):  # noqa: E731 - closure over adapter
            return native.get_pr_diff(config.repo, pr.number)
    # GitHub App auth: every interaction signed as fl4write[bot].
    # Installation resolved PER REPO — the app has separate org and user
    # installations and a token from the wrong one 404s.
    try:
        from .appauth import install_token_to_env

        install_token_to_env(repo=config.repo)
        config = config.model_copy(update={"bot_login": "fl4write[bot]"})
    except Exception as exc:
        print(f"WARNING: GitHub App auth failed ({exc}); falling back to PAT", file=sys.stderr)
        config = config.model_copy(update={"bot_login": "simongonzalezdc"})
    _org_model_keys()
    state_path = Path.home() / ".fl4write" / f"{config.repo.replace('/', '__')}.state.json"
    budget_s = int(os.environ.get("FL4WRITE_CYCLE_BUDGET_S", "840"))
    report = run_cycle(
        config,
        state_path,
        get_diff=diff_getter,
        run_fixes=run_fixes,
        run_issues=run_issues,
        deadline=time.monotonic() + budget_s,
    )
    # Config-presence surveillance (learning 16): racing branches have twice
    # silently reverted adoptions; every cycle verifies the IN-REPO config
    # still exists on main and alerts if the adoption was lost. Accepts the
    # renamed .fl4write.yaml and the legacy .codesitter.yaml during migration.
    try:
        probe = subprocess.run(

            ["gh", "api", f"repos/{config.repo}/contents/.fl4write.yaml", "--jq", ".name"],
            capture_output=True, text=True, timeout=30,
        )
        if probe.returncode != 0:
            probe = subprocess.run(

                ["gh", "api", f"repos/{config.repo}/contents/.codesitter.yaml", "--jq", ".name"],
                capture_output=True, text=True, timeout=30,
            )
        if probe.returncode != 0:
            print(f"ALERT: adoption lost — no .fl4write.yaml or .codesitter.yaml on {config.repo} main (re-adopt)")
    except subprocess.TimeoutExpired:
        print(f"ALERT: config probe timed out for {config.repo} (inconclusive — not an adoption-loss claim)")
    for a in report.alerts:
        print(f"ALERT: {a}")
    print(
        f"fl4write cycle: repo={report.repo} scanned={report.scanned} "
        f"reviewed={report.reviewed} shadow={config.shadow} "
        f"postmerge={report.postmerge_reviewed} "
        f"retro={report.retro_reviewed} retro_zombie={report.retro_zombies} "
        f"ci_red={report.ci_red_heads} ci_fix={report.ci_fix_prs_opened} "
        f"ci_esc={report.ci_escalations} "
        f"dep_skipped={report.skipped_dependency} model_down={report.model_unavailable} "
        f"mirror_degraded={report.mirror_degraded} "
        f"gate_dropped={report.gatekeeper_dropped} fix_prs={report.fix_prs_opened} "
        f"fix_merged={report.fix_prs_merged} issues_triaged={report.issues_triaged} "
        f"acceptance={report.acceptance.get('rate', 'n/a')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
