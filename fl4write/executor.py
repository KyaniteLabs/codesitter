"""Fix lane executor — the part that actually fixes the code.

Takes findings from the analyzer, creates a worktree AT THE PR HEAD, asks the
model for a concrete patch, applies it, runs the repo's test suite in a
scrubbed environment, opens a PR, and CI-gates the merge. Merges ONLY its own
PRs (asserted in code, not config).

Rails enforced at call sites:
- fork PRs: never touched (the engine never routes them here)
- bot PRs: never touched (dependency_policy filters them upstream)
- fix-depth cap: tracked per PR, escalates instead of looping
- merge: re-verifies authorship + CI green at the merge call site

Audit 2026-09-01 (lanes B/C) — the fix lane was 100% dead AND dangerous:
- `git clone -b HEAD` is not a valid ref (clone always failed); when it did
  not, the tree was the DEFAULT branch while patched content came from the
  PR head — a whole-file overwrite that silently reverts main. Now: init +
  authenticated fetch of the PR head SHA, verified checkout.
- The patch write follows symlinks — a PR symlink plus injection could write
  through to ANY user-writable file on the runner host (the classic CI
  symlink attack). Now: containment check, `..`/absolute rejected.
- Tests inherited the full secret environment (installation token, model
  keys, ~/:~/.sinter readable). Now: env whitelist.
- Contents fetch: >1MB files return empty content (encoding "none") — the
  model then fabricated a whole file. Now: require base64, refuse otherwise.
- URL injection via unencoded path/ref; `git add` without `--`; token in the
  push URL argv; merge scan's dead head-filter/hardcoded org/raise-outside-
  try/vacuous CI green — all fixed below.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import shutil
import stat
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from . import scrub
from .analyzer import _call_model
from .config import RepoConfig
from .fixlane import FixLaneBlocked, dependency_depth, escalate, fix_allowed, merge_own_pr
from .models import Finding, PullRequest

log = logging.getLogger("fl4write.executor")

PATCH_SYSTEM = (
    "You are a code-fixer. You receive a finding, the file's current content, "
    "and the repo's law. Reply ONLY with JSON: {\"fixed_content\": str} where "
    "fixed_content is the ENTIRE file with the fix applied. Do not add comments "
    "explaining what you did. Do not change anything except what the finding "
    'requires. If you cannot fix it, reply {"fixed_content": null}.'
)

# Test subprocesses see a MINIMAL environment — model-generated patches are
# executed code and must never reach tokens, keys, or the secret store (the
# lethal trifecta: untrusted input + secrets access + network egress).
_TEST_ENV_ALLOW = ("PATH", "LANG", "LC_ALL", "HOME", "TMPDIR", "PYTHONPATH", "SYSTEMROOT")


def _run(cmd: list[str], cwd: Path | None = None, timeout: int = 120,
         env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # fixed argv, no shell

        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


def _sandbox_env() -> dict[str, str]:
    return {k: os.environ[k] for k in _TEST_ENV_ALLOW if k in os.environ}


def _gh_api(method: str, path: str, data: dict | None = None) -> Any:
    token = os.environ.get("CODESITTER_GITHUB_TOKEN", "")
    req = urllib.request.Request(

        f"https://api.github.com{path}",
        data=json.dumps(data).encode() if data else None,
        method=method,
        headers={"Authorization": f"token {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:

        return json.loads(resp.read().decode())


def _get_file_content(repo: str, path: str, ref: str) -> str | None:
    """Fetch a file at an exact ref. Files >1MB come back with empty content
    and encoding 'none' — the model must never 'fix' an empty premise."""
    qpath = urllib.parse.quote(path, safe="")
    qref = urllib.parse.quote(ref, safe="")
    try:
        data = _gh_api("GET", f"/repos/{repo}/contents/{qpath}?ref={qref}")
        if data.get("encoding") != "base64" or not data.get("content"):
            log.warning("contents API returned no base64 content for %s@%s (encoding=%s)",
                        path, ref[:8], data.get("encoding"))
            return None
        return base64.b64decode(data["content"]).decode("utf-8")
    except (urllib.error.HTTPError, urllib.error.URLError, UnicodeDecodeError) as exc:
        log.warning("file fetch failed for %s@%s: %s", path, ref[:8], exc)
        return None


def _default_branch(repo: str) -> str:
    return _gh_api("GET", f"/repos/{repo}").get("default_branch", "main")


def _write_contained(workdir: Path, rel_path: str, content: str) -> str | None:
    """Write `content` to workdir/rel_path, REFUSING symlinks and escapes.
    Returns an error reason, or None on success."""
    if not rel_path or rel_path.startswith(("/", "\\")) or ".." in Path(rel_path).parts:
        return f"refusing unsafe path {rel_path!r}"
    target = workdir / rel_path
    if target.is_symlink():
        return f"refusing symlink path {rel_path!r}"
    resolved = target.resolve()
    if not str(resolved).startswith(str(workdir.resolve()) + os.sep):
        return f"path escapes workdir: {rel_path!r}"
    resolved.parent.mkdir(parents=True, exist_ok=True)
    if resolved.exists() and resolved.is_symlink():
        return f"refusing symlink path {rel_path!r}"
    resolved.write_text(content, encoding="utf-8")
    return None


def _push_token_env(workdir: Path, token: str) -> dict[str, str]:
    """Env for authenticated git that keeps the token OUT of argv AND out of
    the workdir (audit A1, live-critical: the helper used to live at
    workdir/.git/fl4write-askpass.sh where the diff's own tests run — one
    Path read exfiltrated the installation token). It now lives in a sibling
    temp dir; callers MUST call _drop_askpass() before running any tests."""
    askpass_dir = Path(tempfile.mkdtemp(prefix="fl4write-askpass-"))
    helper = askpass_dir / "askpass.sh"
    helper.write_text(f"#!/bin/sh\necho '{token}'\n")
    helper.chmod(stat.S_IRUSR | stat.S_IXUSR)
    env = _sandbox_env()
    env["GIT_ASKPASS"] = str(helper)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["_FL4WRITE_ASKPASS_DIR"] = str(askpass_dir)
    return env


def _drop_askpass(env: dict[str, str]) -> None:
    """Remove the token-bearing helper; call before untrusted code runs."""
    d = env.pop("_FL4WRITE_ASKPASS_DIR", None)
    if d:
        shutil.rmtree(d, ignore_errors=True)


def _run_tests(cwd: Path, config: RepoConfig) -> bool:
    """Run the repo's test suite in the sandbox env; True if green."""
    test_cmd = os.environ.get("CODESITTER_TEST_CMD", "python3 -m pytest tests/ -x -q --tb=line")
    for excl in config.known_env_failures:
        test_cmd += f" --deselect {excl}"
    result = _run(test_cmd.split(), cwd=cwd, timeout=240, env=_sandbox_env())
    return result.returncode == 0


def attempt_fix(pr: PullRequest, finding: Finding, config: RepoConfig) -> dict[str, Any]:
    """One fix attempt: rails → fetch file at PR head → model patch →
    worktree at PR head → sandboxed tests → PR. Returns a result dict."""
    blocked_reason = fix_allowed(pr, config, 0)
    if blocked_reason:
        return {"status": "blocked", "reason": blocked_reason,
                "escalation": escalate(pr, [finding], blocked_reason)}

    if dependency_depth(pr, pr.title, config) == "skip":
        return {"status": "skipped", "reason": "dependency PR"}

    content = _get_file_content(pr.repo, finding.path, pr.head_sha)
    if content is None:
        return {"status": "error", "reason": f"cannot fetch {finding.path}@{pr.head_sha[:8]}"}

    prompt = (
        f"FINDING: [{finding.severity}] {finding.path}:{finding.line} — {finding.message}\n"
        f"PROPOSAL: {finding.proposal}\n"
        f"REPO LAW: {json.dumps(config.review, indent=1)}\n"
        f"FILE CONTENT ({finding.path}):\n```\n{scrub.scrub(content)}\n```"
    )
    try:
        from .law import SYSTEM_PROMPT_ADDENDUM

        response = _call_model(
            config.model, prompt,
            system=PATCH_SYSTEM + "\n\n" + SYSTEM_PROMPT_ADDENDUM,
        )
        from .analyzer import extract_json

        parsed = extract_json(response)
        fixed = parsed.get("fixed_content")
    except Exception as exc:  # audit A6: network/HTTP/RuntimeError classes
        # crashed whole cycles through the narrow tuple — fail-open means
        # except Exception or it isn't (LEARNINGS #25c)
        return {"status": "error", "reason": f"model unavailable: {str(exc)[:120]}"}

    if fixed is None or not isinstance(fixed, str):
        return {"status": "nofix", "reason": "model returned no fix"}
    if fixed.strip() == content.strip():
        # Live-caught (first real attempt, 2026-09-02): a no-op patch flowed
        # through worktree→commit→push→PR and died as an opaque 422. A patch
        # identical to the original is a nofix, caught BEFORE any writes.
        return {"status": "nofix", "reason": "model patch identical to original (no-op)"}

    token = os.environ.get("CODESITTER_GITHUB_TOKEN", "")
    workdir = Path(tempfile.mkdtemp(prefix="fl4write-fix-"))
    try:
        # Fetch the EXACT PR head into a fresh workdir (clone -b HEAD was an
        # invalid ref; cloning the default branch reverted main-side changes).
        fetch_url = f"https://github.com/{pr.repo}.git"
        if _run(["git", "init", "-q"], cwd=workdir).returncode != 0:
            return {"status": "error", "reason": "git init failed"}
        pull_env = _push_token_env(workdir, token)
        fetch = _run(
            ["git", "fetch", "-q", "--depth", "1", fetch_url, pr.head_sha],
            cwd=workdir, timeout=180, env=pull_env,
        )
        _drop_askpass(pull_env)  # token helper gone before any code checkout
        if fetch.returncode != 0:
            return {"status": "error", "reason": f"fetch of PR head failed: {fetch.stderr[-100:]}"}
        if _run(["git", "checkout", "-q", "--detach", "FETCH_HEAD"], cwd=workdir).returncode != 0:
            return {"status": "error", "reason": "checkout of PR head failed"}
        head_verify = _run(["git", "rev-parse", "HEAD"], cwd=workdir)
        if head_verify.stdout.strip() != pr.head_sha:
            return {"status": "error", "reason": "checked-out SHA does not match PR head — refusing"}

        err = _write_contained(workdir, finding.path, fixed)
        if err:
            return {"status": "error", "reason": err}

        if not _run_tests(workdir, config):
            return {"status": "testfail", "reason": "tests failed with fix applied"}

        _run(["git", "add", "--", finding.path], cwd=workdir)
        commit = _run(
            ["git", "commit", "-q", "-m",
             f"fix({finding.rule_id}): {finding.message[:60]}\n\n"
             "Co-authored-by: fl4write <fl4write@kyanitelabs.tech>"],
            cwd=workdir, env=_sandbox_env(),
        )
        if commit.returncode != 0:
            # empty commit vs environmental failure must be told apart (A8):
            # nofix would misroute ops triage and the ci-watch break heuristic
            if "nothing to commit" in (commit.stderr or ""):
                return {"status": "nofix", "reason": "nothing to commit (patch was a no-op)"}
            return {"status": "error", "reason": f"git commit failed: {commit.stderr[-80:]}"}
        branch = f"fl4write/fix-{pr.number}-{finding.rule_id[:20]}"
        _run(["git", "branch", "-M", branch], cwd=workdir)
        push_env = _push_token_env(workdir, token)
        push = _run(
            ["git", "push", "-q", fetch_url, f"HEAD:refs/heads/{branch}"],
            cwd=workdir, timeout=120, env=push_env,
        )
        _drop_askpass(push_env)
        if push.returncode != 0:
            return {"status": "error", "reason": f"push failed: {push.stderr[-100:]}"}

        base = _default_branch(pr.repo)
        new_pr = _gh_api("POST", f"/repos/{pr.repo}/pulls", {
            "title": f"fix({finding.rule_id}): {finding.message[:60]}",
            "head": branch,
            "base": base,
            "body": (
                "Automated fix by FL4WRITE.\n\n"
                f"Finding: [{finding.severity}] {finding.path}:{finding.line} — {finding.message}\n"
                f"Proposal: {finding.proposal}\n\nTests pass. Review and merge."
            ),
        })
        return {"status": "pr_opened", "pr_number": new_pr["number"],
                "pr_url": new_pr["html_url"], "branch": branch}
    except Exception as exc:  # contained into a result dict

        return {"status": "error", "reason": str(exc)[:200]}
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def verify_diff_tests(pr: PullRequest, config: RepoConfig, test_files: list[str]) -> "Finding | None":
    """Deterministic spec check: check out the PR head in a sandbox worktree
    and run the repo's test command. If the diff's own tests FAIL, return a
    Critical Finding carrying the failure tail — no model in the loop for
    this class (both M3 and deepseek gave a planted, self-failing diff a
    clean review twice each; live-caught on the first-real-fix E2E).
    Returns None on any infrastructure trouble (never a false finding)."""
    from .models import Finding as _Finding

    token = os.environ.get("CODESITTER_GITHUB_TOKEN", "")
    workdir = Path(tempfile.mkdtemp(prefix="fl4write-verify-"))
    try:
        fetch_url = f"https://github.com/{pr.repo}.git"
        if _run(["git", "init", "-q"], cwd=workdir).returncode != 0:
            return None
        pull_env = _push_token_env(workdir, token)
        if _run(["git", "fetch", "-q", "--depth", "1", fetch_url, pr.head_sha],
                cwd=workdir, timeout=180, env=pull_env).returncode != 0:
            return None
        if _run(["git", "checkout", "-q", "--detach", "FETCH_HEAD"], cwd=workdir).returncode != 0:
            return None
        # ONLY the diff's own test files — the whole-suite default would
        # attribute MAIN's pre-existing red to this diff (audit A3: a
        # false-Critical machine wearing the word 'deterministic').
        py_tests = [f for f in test_files if f.endswith(".py")]
        if py_tests:
            cmd = f"python3 -m pytest {' '.join(py_tests)} -q --tb=line"
        else:
            cmd = os.environ.get("CODESITTER_TEST_CMD", "python3 -m pytest tests/ -x -q --tb=line")
        env = _push_token_env(workdir, token)
        _drop_askpass(env)  # tests never see the helper (A1)
        result = _run(cmd.split(), cwd=workdir, timeout=300, env=env)
        if result.returncode == 0:
            return None
        tail = (result.stdout + "\n" + result.stderr).strip().splitlines()
        return _Finding(
            rule_id="tests",
            severity="Critical",
            path=test_files[0] if test_files else "tests",
            line=1,
            category="CI",
            message="The diff's own tests FAIL against this code (sandbox run): "
                    + " | ".join(tail[-3:])[:300],
        )
    except Exception as exc:  # noqa: BLE001 — infrastructure trouble is never a finding
        log.warning("verify_diff_tests infra failure for %s#%s: %s", pr.repo, pr.number, exc)
        return None
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def open_issue(repo: str, title: str, body: str) -> int:
    """Open an issue as the bot (CI-watch escalation surface). The issues LANE
    stays comment-only; this is the one bounded exception, config-gated by
    ci_watch.escalate_issues."""
    return _gh_api("POST", f"/repos/{repo}/issues", {"title": title, "body": body})["number"]


def check_and_merge_own_prs(config: RepoConfig, bot_identity: str) -> list[dict]:
    """Check our own open fix PRs; merge those with ALL checks completed green.

    Per-PR containment: a blocked/not-green PR skips; it never aborts the scan
    (the gate used to raise outside the try that was written to catch it).
    """
    merged: list[dict] = []
    owner = config.repo.split("/")[0]
    try:
        prs = _gh_api("GET", f"/repos/{config.repo}/pulls?state=open&per_page=100")
    except Exception as exc:

        log.warning("own-PR scan failed for %s: %s", config.repo, exc)
        return merged
    for pr_data in prs:
        number = pr_data["number"]
        try:
            head_ref = (pr_data.get("head") or {}).get("ref", "")
            if not head_ref.startswith("fl4write/"):
                continue
            author = (pr_data.get("user") or {}).get("login", "")
            checks = _gh_api("GET", f"/repos/{config.repo}/commits/{pr_data['head']['sha']}/check-runs")
            runs = [c for c in checks.get("check_runs", []) if c.get("status") == "completed"]
            pending = [c for c in checks.get("check_runs", []) if c.get("status") != "completed"]
            # Non-vacuous gate: no checks at all is NOT green; pending runs
            # are NOT green (all([]) used to bless both).
            ci_green = bool(runs) and not pending and all(c.get("conclusion") == "success" for c in runs)
            # The gate re-verifies authorship + CI IN CODE. is_own_identity
            # accepts the current + legacy bot slugs across renames.
            merge_own_pr(author=author, bot_identity=bot_identity, ci_green=ci_green, config=config)
            _gh_api("PUT", f"/repos/{config.repo}/pulls/{number}/merge", {"merge_method": "squash"})
            merged.append({"pr": number, "status": "merged"})
            log.info("merged own fix PR #%s on %s (owner=%s)", number, config.repo, owner)
        except FixLaneBlocked as exc:
            log.info("PR #%s not mergeable yet: %s", number, exc)  # per-PR skip, scan continues
        except Exception as exc:

            log.warning("merge failed for #%s: %s", number, exc)
    return merged
