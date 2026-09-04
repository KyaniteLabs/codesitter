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


def _probe_adoption(config, forge_adapter=None) -> None:
    """Surveillance: verify the IN-REPO config still exists on the default
    branch; alert on loss. GitHub-primary uses the gh CLI; any other primary
    probes BOTH config names via the forge adapter (the gh path 404s there).
    Extracted for testability (the Critic's blocking item: the probe must be
    exercisable by tests, not re-implemented by them)."""
    import logging

    if forge_adapter is None:
        present = False
        inconclusive = False
        for name in (".fl4write.yaml", ".codesitter.yaml"):
            try:
                probe = subprocess.run(
                    ["gh", "api", f"repos/{config.repo}/contents/{name}", "--jq", ".name"],
                    capture_output=True, text=True, timeout=30,
                )
            except (subprocess.TimeoutExpired, OSError):
                # a failed probe is NOT an adoption loss (audit A9: rate-limit
                # 401/403 used to fire false re-adopt alerts)
                inconclusive = True
                break
            if probe.returncode == 0:
                present = True
                break
            if "404" not in (probe.stderr or ""):
                inconclusive = True
                break
        if inconclusive:
            print(f"ALERT: config probe inconclusive for {config.repo} (probe failed — not an adoption-loss claim)")
            return
    else:
        results = [
            forge_adapter.path_exists(config.repo, ".fl4write.yaml"),
            forge_adapter.path_exists(config.repo, ".codesitter.yaml"),
        ]
        if any(r is True for r in results):
            present = True
        elif any(r is None for r in results):
            # unqueryable is NOT absent (Sol audit + Critic residual): a
            # forge outage must not fire false re-adopt alerts
            print(f"ALERT: config probe inconclusive for {config.repo} (forge unqueryable — not an adoption-loss claim)")
            return
        else:
            present = False
    if not present:
        print(f"ALERT: adoption lost — no .fl4write.yaml or .codesitter.yaml on {config.repo} default branch (re-adopt)")
        logging.getLogger("fl4write.cli").warning("adoption probe negative for %s", config.repo)


_KNOWN_FLAGS = ("--live", "--fixes", "--issues", "--omni", "--shadow", "--once", "--sweep")


def _unknown_flags(argv: list[str]) -> list[str]:
    """Flags the CLI does not know. MECE round-1 (sol F1-006): unknown
    arguments were silently ignored — a typo like --lvie for --live ran the
    cycle in the WRONG mode (silent mis-operation, and worse for shadow-mode
    typos). Every flag must be explicit."""
    return [a for a in argv[1:] if a.startswith("--") and a not in _KNOWN_FLAGS]


def main() -> int:
    _install_sigterm_handler()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    unknown = _unknown_flags(sys.argv)
    if unknown:
        print(f"unknown flag(s): {', '.join(unknown)} — refusing to run (typo guard)",
              file=sys.stderr)
        return 2
    if len(sys.argv) < 2:
        print("usage: python3 -m fl4write.cli <config.yaml> [--live]", file=sys.stderr)
        return 2
    live = "--live" in sys.argv
    run_fixes = "--fixes" in sys.argv
    run_issues = "--issues" in sys.argv
    config = load_config(sys.argv[1])
    if "--omni" in sys.argv:
        # One-shot prelaunch kick: a NORMAL run_cycle (CycleLock, deadline,
        # one-state-owner all preserved) with the per-cycle file cap raised —
        # repeated capped cycles under the same lock, never a side door.
        # (audit A10: this used to reload the config right after, discarding
        # the override — the flag was dead.)
        config = config.model_copy(update={
            "omnisweep": config.omnisweep.model_copy(update={"enabled": True, "max_files_per_cycle": 50}),
        })
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
    # Config-presence surveillance (learning 16) — FORGE-AWARE (2026-09-01):
    # the old gh-only probe 404'd every cycle on Forgejo-primary repos and
    # fired false "adoption lost" alerts, live-observed on the 23:00 cycle.
    _probe_adoption(config, native if "api.github.com" not in primary_binding.api_base else None)
    from . import telemetry as _tel
    _cal = _tel.calibration_snapshot()
    if _cal:
        print(f"calibration: {_cal}")
    for model, st in _tel.route_stats().items():
        print(f"route {model}: {st['ok']}/{st['calls']} ok, parse_fail={st['parse_fail']}, "
              f"lat={st['latency_s']:.0f}s, tok_in={st['prompt_tokens']}, tok_out={st['completion_tokens']}")
    for a in report.alerts:
        print(f"ALERT: {a}")
    print(format_cycle_line(report, config))
    return 0


def format_cycle_line(report, config) -> str:
    """The per-repo cycle line, extracted for BEHAVIORAL testing (the Critic's
    residual: source-inspection is a tripwire, not a test). Pure: no prints."""
    return (
        f"fl4write cycle: repo={report.repo} scanned={report.scanned} "
        f"reviewed={report.reviewed} shadow={config.shadow} "
        f"postmerge={report.postmerge_reviewed} "
        f"retro={report.retro_reviewed} retro_zombie={report.retro_zombies} "
        f"omni={report.omni_scanned}/{report.omni_findings}f "
        f"ci_red={report.ci_red_heads} ci_fix={report.ci_fix_prs_opened} "
        f"ci_esc={report.ci_escalations} "
        f"dep_skipped={report.skipped_dependency} model_down={report.model_unavailable} "
        f"mirror_degraded={report.mirror_degraded} "
        f"gate_dropped={report.gatekeeper_dropped} gate_fail={report.gatekeeper_failed} "
        f"fix_attempts={report.fix_attempts} fix_fail={report.fix_failures} fix_prs={report.fix_prs_opened} "
        f"fix_merged={report.fix_prs_merged} issues_triaged={report.issues_triaged} "
        f"acceptance={report.acceptance.get('rate', 'n/a')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
