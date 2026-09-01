"""Fix lane executor — the part that actually fixes the code.

Takes findings from the analyzer, creates a worktree, asks the model for a
concrete patch, applies it, runs the repo's test suite, opens a PR, and
CI-gates the merge. Merges ONLY its own PRs (asserted in code, not config).

Rails enforced at call sites:
- fork PRs: never touched (the engine never routes them here)
- bot PRs: never touched (dependency_policy filters them upstream)
- fix-depth cap: tracked per PR, escalates instead of looping
- merge: re-verifies authorship + CI green at the merge call site
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from . import scrub
from .analyzer import _call_model, ModelUnavailable
from .config import RepoConfig
from .fixlane import FixLaneBlocked, dependency_depth, escalate, fix_allowed, merge_own_pr
from .models import Finding, PullRequest

log = logging.getLogger("codesitter.executor")

PATCH_SYSTEM = (
    "You are a code-fixer. You receive a finding, the file's current content, "
    'and the repo\'s law. Reply ONLY with JSON: {"fixed_content": str} where '
    "fixed_content is the ENTIRE file with the fix applied. Do not add comments "
    "explaining what you did. Do not change anything except what the finding "
    'requires. If you cannot fix it, reply {"fixed_content": null}.'
)


def _run(cmd: list[str], cwd: Path | None = None, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed argv, no shell
        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _get_file_content(repo: str, path: str, ref: str = "HEAD") -> str | None:
    """Fetch a file from the PR head via the GitHub API."""
    import urllib.request

    token = os.environ.get("CODESITTER_GITHUB_TOKEN", "")
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/contents/{path}?ref={ref}",
        headers={"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            import base64

            data = json.loads(resp.read().decode())
            return base64.b64decode(data["content"]).decode("utf-8")
    except Exception:
        return None


def _run_tests(cwd: Path, config: RepoConfig) -> bool:
    """Run the repo's test suite; return True if green."""
    test_cmd = os.environ.get("CODESITTER_TEST_CMD", "python3 -m pytest tests/ -x -q --tb=line")
    for excl in config.known_env_failures:
        test_cmd += f" --deselect {excl}"
    result = _run(test_cmd.split(), cwd=cwd, timeout=600)
    return result.returncode == 0


def attempt_fix(
    pr: PullRequest,
    finding: Finding,
    config: RepoConfig,
    depth_used: int,
) -> dict[str, Any]:
    """One fix attempt: check rails → fetch file → model patch → worktree → test → PR.

    Returns a result dict with status and details for the cycle report.
    """
    # Rail 1: identity checks (before any work)
    blocked_reason = fix_allowed(pr, config, depth_used)
    if blocked_reason:
        return {"status": "blocked", "reason": blocked_reason, "escalation": escalate(pr, [finding], blocked_reason)}

    # Rail 2: dependency policy (bot PRs never reach here, but belt-and-suspenders)
    if dependency_depth(pr, pr.title, config) == "skip":
        return {"status": "skipped", "reason": "dependency PR"}

    # Fetch the file content from the PR head
    content = _get_file_content(pr.repo, finding.path, pr.head_sha)
    if content is None:
        return {"status": "error", "reason": f"cannot fetch {finding.path}@{pr.head_sha[:8]}"}

    # Ask the model for a fix
    prompt = (
        f"FINDING: [{finding.severity}] {finding.path}:{finding.line} — {finding.message}\n"
        f"PROPOSAL: {finding.proposal}\n"
        f"REPO LAW: {json.dumps(config.review, indent=1)}\n"
        f"FILE CONTENT ({finding.path}):\n```\n{scrub.scrub(content)}\n```"
    )
    try:
        response = _call_model(config.model, prompt)
        parsed = json.loads(response[response.index("{") : response.rindex("}") + 1])
        fixed = parsed.get("fixed_content")
    except (ModelUnavailable, ValueError, json.JSONDecodeError) as exc:
        return {"status": "error", "reason": f"model unavailable: {exc}"}

    if fixed is None or not isinstance(fixed, str):
        return {"status": "nofix", "reason": "model returned no fix"}

    # Create a temporary worktree
    workdir = Path(tempfile.mkdtemp(prefix="codesitter-fix-"))
    try:
        # Clone the PR branch
        clone = _run(
            ["git", "clone", "-q", "--depth", "1", "-b", "HEAD", f"https://github.com/{pr.repo}.git", str(workdir)],
            timeout=120,
        )
        if clone.returncode != 0:
            return {"status": "error", "reason": f"clone failed: {clone.stderr[-100:]}"}

        # Write the fixed file
        (workdir / finding.path).write_text(fixed, encoding="utf-8")

        # Run tests
        if not _run_tests(workdir, config):
            return {"status": "testfail", "reason": "tests failed with fix applied"}

        # Commit and push
        _run(["git", "add", finding.path], cwd=workdir)
        _run(
            [
                "git",
                "commit",
                "-q",
                "-m",
                f"fix({finding.rule_id}): {finding.message[:60]}\n\nCo-authored-by: codesitter <codesitter@kyanitelabs.tech>",
            ],
            cwd=workdir,
        )
        branch = f"codesitter/fix-{pr.number}-{finding.rule_id[:20]}"
        _run(["git", "branch", "-M", branch], cwd=workdir)
        push = _run(
            [
                "git",
                "push",
                "-q",
                f"https://x-access-token:{os.environ.get('CODESITTER_GITHUB_TOKEN', '')}@github.com/{pr.repo}.git",
                f"HEAD:refs/heads/{branch}",
            ],
            cwd=workdir,
            timeout=120,
        )
        if push.returncode != 0:
            return {"status": "error", "reason": f"push failed: {push.stderr[-100:]}"}

        # Open PR
        import urllib.request

        token = os.environ.get("CODESITTER_GITHUB_TOKEN", "")
        pr_body = json.dumps(
            {
                "title": f"fix({finding.rule_id}): {finding.message[:60]}",
                "head": branch,
                "base": "main",
                "body": f"Automated fix by codesitter.\n\nFinding: [{finding.severity}] {finding.path}:{finding.line} — {finding.message}\nProposal: {finding.proposal}\n\nTests pass. Review and merge.",
            }
        ).encode()
        req = urllib.request.Request(
            f"https://api.github.com/repos/{pr.repo}/pulls",
            data=pr_body,
            headers={"Authorization": f"token {token}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            new_pr = json.loads(resp.read().decode())

        return {
            "status": "pr_opened",
            "pr_number": new_pr["number"],
            "pr_url": new_pr["html_url"],
            "branch": branch,
        }

    except Exception as exc:
        return {"status": "error", "reason": str(exc)[:200]}
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def check_and_merge_own_prs(config: RepoConfig, bot_identity: str = "simongonzalezdc") -> list[dict]:
    """Check our own open fix PRs; merge those with green CI.

    The merge gate re-verifies at the call site: authorship + CI green.
    """
    import urllib.request

    token = os.environ.get("CODESITTER_GITHUB_TOKEN", "")
    headers = {"Authorization": f"token {token}", "Content-Type": "application/json"}

    def api(method: str, path: str, data: dict | None = None) -> Any:
        req = urllib.request.Request(
            f"https://api.github.com{path}",
            data=json.dumps(data).encode() if data else None,
            headers=headers,
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())

    merged = []
    try:
        prs = api("GET", f"/repos/{config.repo}/pulls?state=open&head=KyaniteLabs:codesitter/")
        for pr_data in prs:
            author = (pr_data.get("user") or {}).get("login", "")
            number = pr_data["number"]
            # Check CI
            try:
                checks = api("GET", f"/repos/{config.repo}/commits/{pr_data['head']['sha']}/check-runs")
                ci_green = all(
                    c.get("conclusion") == "success"
                    for c in checks.get("check_runs", [])
                    if c.get("status") == "completed"
                )
            except Exception:
                ci_green = False
            # Merge gate: assert authorship + CI IN CODE (never config-only)
            merge_own_pr(author=author, bot_identity=bot_identity, ci_green=ci_green, config=config)
            try:
                api("PUT", f"/repos/{config.repo}/pulls/{number}/merge", {"merge_method": "squash"})
                merged.append({"pr": number, "status": "merged"})
                log.info("merged own fix PR #%s on %s", number, config.repo)
            except FixLaneBlocked:
                pass
            except Exception as exc:
                log.warning("merge failed for #%s: %s", number, exc)
    except Exception as exc:
        log.warning("check_and_merge scan failed: %s", exc)
    return merged
