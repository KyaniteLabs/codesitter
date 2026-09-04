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
import binascii
import json
import logging
import re
import os
import shutil
import shlex
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

# Test subprocesses see a MINIMAL environment — model-generated patches and
# organic-PR tests are EXECUTED CODE and must never reach tokens, keys, or the
# secret store (the lethal trifecta). MECE round-1 audit (luna F1-02): keeping
# the real HOME let executed code read ~/.sinter/config.json (all org keys) —
# HOME now points at a throwaway sandbox dir created per process.
_TEST_ENV_ALLOW = ("PATH", "LANG", "LC_ALL", "TMPDIR", "PYTHONPATH", "SYSTEMROOT")
_SANDBOX_HOME: str | None = None
_SECRET_ENV_KEYS = ("GITHUB_TOKEN", "CODESITTER", "MINIMAX", "ANTHROPIC", "OPENAI",
                    "AWS", "AZURE", "GOOGLE", "FL4WRITE_TELEMETRY", "GIT_ASKPASS")


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


def _sandbox_home() -> str:
    """One throwaway HOME per process for executed code. Residual boundary
    (documented, MECE round 1): a determined same-user process can still read
    ABSOLUTE paths (/Users/<runner>/.sinter/...) — true isolation needs OS
    privilege separation (dedicated runner user), tracked for the sandbox
    tranche. This closes every HOME-relative secret store (~/.sinter, ~/.ssh,
    ~/.aws, ~/.codex/auth.json) and the env-var secret surface."""
    global _SANDBOX_HOME
    if _SANDBOX_HOME is None:
        _SANDBOX_HOME = tempfile.mkdtemp(prefix="fl4write-sandbox-home-")
        # MECE round-4 (glm F4-8): one throwaway HOME per process leaked on
        # the runner host — remove it at exit
        import atexit as _atexit
        _atexit.register(shutil.rmtree, _SANDBOX_HOME, True)
    return _SANDBOX_HOME


def _sandbox_env_for(home: str) -> dict[str, str]:
    out = {k: os.environ[k] for k in _TEST_ENV_ALLOW if k in os.environ}
    out["HOME"] = home
    # user-site packages (e.g. pytest) live under the REAL home's .local —
    # re-expose ONLY that library dir (never the secret stores in ~/.sinter)
    try:
        import site as _site
        real_user = Path(_site.getusersitepackages())
        if real_user.is_dir():
            prev = out.get("PYTHONPATH")
            out["PYTHONPATH"] = str(real_user) + (os.pathsep + prev if prev else "")
    except Exception:
        pass
    for k in list(out):
        if any(s in k.upper() for s in _SECRET_ENV_KEYS):
            out.pop(k, None)
    return out


def _sandbox_env() -> dict[str, str]:
    return _sandbox_env_for(_sandbox_home())


def _git_hardened_env(base: dict[str, str]) -> dict[str, str]:
    """F12-B001 (round 12, sol DOM-B, reopened F1-001/F8-002): PRIVILEGED git
    (commit/push) must be blind to anything executed test code could write —
    a test that polluted its HOME with ~/.gitconfig (core.hooksPath, url
    rewrites) used to steer the post-test commit/push in the REAL worktree.
    Global/system config and hooks are disabled explicitly."""
    out = dict(base)
    out.update({
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "HOME": base.get("HOME", _sandbox_home()),
    })
    return out


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
        if not isinstance(data, dict):
            log.warning("contents API returned non-dict for %s@%s (dir match?)", path, ref[:8])
            return None
        if data.get("encoding") != "base64" or not data.get("content"):
            log.warning("contents API returned no base64 content for %s@%s (encoding=%s)",
                        path, ref[:8], data.get("encoding"))
            return None
        # MECE round-6 (luna F6-001, reopened F1-024): lenient b64decode made
        # an invalid payload ("!!!!") decode to b"" and return an EMPTY file —
        # the vacuous-premise law was bypassed and the model could fabricate a
        # whole-file fix from nothing. validate=True rejects garbage; empty
        # decodes return None, never "".
        try:
            # F8-001: the API line-wraps long payloads — strip ASCII
            # whitespace BEFORE strict validation or valid content is refused
            compact = "".join(data["content"].split())
            raw = base64.b64decode(compact, validate=True)
        except (binascii.Error, ValueError) as exc:
            log.warning("file fetch invalid base64 for %s@%s: %s", path, ref[:8], exc)
            return None
        if not raw:
            log.warning("file fetch empty payload for %s@%s (rejected)", path, ref[:8])
            return None
        return raw.decode("utf-8")
    except (urllib.error.HTTPError, urllib.error.URLError, UnicodeDecodeError,
            binascii.Error, ValueError, TypeError, AttributeError) as exc:
        # binascii: forged/invalid base64 payloads (MECE round-1, luna F1-10).
        # F11-B001: ValueError (malformed JSON), TypeError/AttributeError
        # (payload in an unexpected shape) used to escape this boundary and
        # bypass the fix lane's terminal outcome recorder
        log.warning("file fetch failed for %s@%s: %s", path, ref[:8], exc)
        return None


def _default_branch(repo: str) -> str:
    return _gh_api("GET", f"/repos/{repo}").get("default_branch", "main")


def _write_contained(workdir: Path, rel_path: str, content: str) -> str | None:
    """Write `content` to workdir/rel_path, REFUSING symlinks and escapes
    (incl. backslash separators — Windows semantics, UltraQA round 2).
    Returns an error reason, or None on success."""
    if (not rel_path or rel_path.startswith(("/", "\\"))
            or ".." in Path(rel_path).parts or "\\" in rel_path):
        return f"refusing unsafe path {rel_path!r}"
    target = workdir / rel_path
    if target.is_symlink():
        return f"refusing symlink path {rel_path!r}"
    resolved = target.resolve()  # dereferences symlinks; escape guard below
    if not str(resolved).startswith(str(workdir.resolve()) + os.sep):
        return f"path escapes workdir: {rel_path!r}"
    resolved.parent.mkdir(parents=True, exist_ok=True)
    # MECE round-4 (glm F4-5): the post-resolve is_symlink() re-check was
    # dead — resolve() already followed any symlink; containment is proven
    # by the startswith guard above
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


def _pytest_evidence(argv: list[str], cwd: Path, timeout: int,
                     env: dict[str, str], junit_path: Path) -> tuple[bool, subprocess.CompletedProcess[str]]:
    """Run a pytest-style suite and require COMPLETION evidence: a --junitxml
    file, which pytest writes only when the session genuinely finishes — this
    defeats the accidental-kill and flush-then-exit classes (a killed process
    never writes junit). Honest boundary (MECE round 1, luna F1-01): the
    junit path is visible in argv to the same-user test process, so a
    DETERMINED adversary in the executed code can forge the artifact; closing
    that needs OS privilege separation (sandbox tranche), not argv secrets.
    Green = tests>0, failures=0, errors=0. Returns (green, result)."""
    xml_argv = list(argv)
    # F11-B002 (round 11, luna DOM-B, reopened F1-002): CONFIGURED junit
    # options are STRIPPED — executed code must never control the evidence
    # path (a config --junitxml=results.xml used to survive, letting the
    # tested code write the very file the host then trusted)
    cleaned: list[str] = []
    i = 0
    while i < len(xml_argv):
        tok = xml_argv[i]
        if tok in ("--junitxml", "--junit-prefix"):
            i += 2  # drop the option and its separate value
            continue
        if tok.startswith("--junitxml=") or tok.startswith("--junit-prefix="):
            i += 1
            continue
        cleaned.append(tok)
        i += 1
    xml_argv = cleaned
    # MECE round-6 (sol F6-E03): file paths may sit behind a '--' separator —
    # options appended at the end would be parsed as positional paths and
    # fail the run. Insert the junit flag before the separator (or at the end
    # when there is none).
    try:
        sep = xml_argv.index("--")
    except ValueError:
        sep = len(xml_argv)
    xml_argv = xml_argv[:sep] + ["--junitxml", str(junit_path)] + xml_argv[sep:]
    result = _run(xml_argv, cwd=cwd, timeout=timeout, env=env)
    if result.returncode != 0:
        return False, result
    try:
        import xml.etree.ElementTree as ET
        if not junit_path.exists():
            log.warning("pytest exited 0 but wrote no junit evidence — treating as "
                        "failure (killed-suite class, UltraQA P4)")
            return False, result
        root = ET.parse(junit_path).getroot()
        # pytest emits <testsuites><testsuite tests=.. failures=.. errors=..>
        suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
        if not suites:
            log.warning("pytest junit evidence has no testsuite element — failure")
            return False, result
        # MECE round-4 (glm F4-1): aggregate every testsuite (some runners
        # emit several) — reading only the first could bless hidden failures
        tests = sum(int(s.get("tests", "0") or 0) for s in suites)
        failures = sum(int(s.get("failures", "0") or 0) for s in suites)
        errors = sum(int(s.get("errors", "0") or 0) for s in suites)
        if tests <= 0 or failures or errors:
            log.warning("pytest junit evidence not green (tests=%s failures=%s errors=%s)",
                        tests, failures, errors)
            return False, result
        return True, result
    except Exception as exc:  # noqa: BLE001 — evidence failure is a gate failure
        log.warning("pytest junit evidence unreadable (%s) — treating as failure", exc)
        return False, result


def _run_tests(cwd: Path, config: RepoConfig) -> bool:
    """Run the repo's test suite in the sandbox env; True only on a genuine
    green with host-controlled evidence.

    UltraQA round 3 (P4 + Sol audit): rc 0 is a promise, output is forgeable —
    a hostile 'fix' can flush a fake summary then os._exit(0) at import time.
    pytest-style cmds therefore require a --junitxml completion artifact.
    NON-pytest runners (vitest/pnpm/make) have no completion evidence yet:
    the fix gate FAILS CLOSED for them with a clear reason until a per-runner
    evidence mapping lands (the fix lane is GitHub-only v1 and 0 fixes have
    landed — blocking is free).
    """
    default = os.environ.get("CODESITTER_TEST_CMD", "python3 -m pytest tests/ -x -q --tb=line")
    if config.test_cmd and any(m in config.test_cmd for m in ("&&", ";", "|")):
        log.warning("fix-gate fail-closed: chained test_cmd %r has no host-controlled "
                    "runner evidence (UltraQA P4)", config.test_cmd)
        return False
    cmd = config.test_cmd or default
    try:
        argv = shlex.split(cmd)  # F7-B003: quoted paths survive argv
    except ValueError as exc:
        log.warning("fix-gate fail-closed: unparseable test_cmd %r (%s)", cmd, exc)
        return False
    if "pytest" in cmd:
        for excl in config.known_env_failures:
            argv += ["--deselect", excl]
        junit = Path(tempfile.mkdtemp(prefix="fl4write-junit-")) / "results.xml"
        # F12-B001: a FRESH disposable HOME per test run — the process-wide
        # sandbox home was reusable and writable by executed code, which
        # could plant ~/.gitconfig for the post-test privileged git calls
        home = tempfile.mkdtemp(prefix="fl4write-test-home-")
        try:
            green, _ = _pytest_evidence(argv, cwd, config.test_timeout,
                                        _sandbox_env_for(home), junit)
            return green
        finally:
            shutil.rmtree(home, ignore_errors=True)
            shutil.rmtree(junit.parent, ignore_errors=True)
    # Non-pytest runner: no host-controlled evidence -> fail closed (see docstring)
    log.warning("fix-gate fail-closed: non-pytest test_cmd %r has no host-controlled "
                "runner evidence (UltraQA P4)", cmd)
    return False


def attempt_fix(pr: PullRequest, finding: Finding, config: RepoConfig) -> dict[str, Any]:
    """One fix attempt: rails → fetch file at PR head → model patch →
    worktree at PR head → sandboxed tests → PR. Returns a result dict."""
    from . import telemetry as _tel

    _t0 = __import__("time").time()

    def _finish(status: str, reason: str = "", **extra) -> dict[str, Any]:
        # F10-B002: ONE guarded terminal fix_attempt outcome event per attempt.
        # Infrastructure error returns used to omit the event entirely and
        # telemetry undercounted failures; every path records exactly once.
        try:
            _tel.emit("fix_attempt", repo=pr.repo, path=finding.path,
                      status=status, reason=reason[:80],
                      latency_s=round(__import__("time").time() - _t0, 1))
        except Exception:  # noqa: BLE001 — telemetry never aborts the attempt
            pass
        pass
        out: dict[str, Any] = {"status": status, "reason": reason}
        out.update(extra)
        return out

    blocked_reason = fix_allowed(pr, config, 0)
    if blocked_reason:
        return _finish("blocked", blocked_reason,
                       escalation=escalate(pr, [finding], blocked_reason))

    if dependency_depth(pr, pr.title, config) == "skip":
        return _finish("skipped", "dependency PR")

    try:
        content = _get_file_content(pr.repo, finding.path, pr.head_sha)
    except Exception as exc:  # noqa: BLE001 - F11-B001: containment belt
        log.warning("file fetch crashed for %s@%s: %s", finding.path, pr.head_sha[:8], exc)
        return _finish("error", f"cannot fetch {finding.path}@{pr.head_sha[:8]}: {type(exc).__name__}")
    if content is None:
        return _finish("error", f"cannot fetch {finding.path}@{pr.head_sha[:8]}")

    from .renderer import path_display  # MECE round-5 (terra F5-002): raw
    # paths in the fix prompt can carry control/credential-shaped content —
    # render via the display transform
    # F12-B002 (reopened F1-012): the premise must be the file's EXACT
    # bytes — destructively scrubbed content made compliant fixes delete
    # legitimate HTML/comments/literals the model never saw. The widened
    # fence contains raw bytes structurally; PATCH_SYSTEM already declares
    # file content to be DATA, never instructions.
    _fence = "`" * (1 + max((len(run) for run in re.findall(r"`+", content)),
                            default=0))
    prompt = (
        f"FINDING: [{finding.severity}] {path_display(finding.path)}:{finding.line} — {finding.message}\n"
        f"PROPOSAL: {finding.proposal}\n"
        f"REPO LAW: {json.dumps(config.review, indent=1)}\n"
        f"FILE CONTENT ({path_display(finding.path)}):\n{_fence}\n{content}\n{_fence}"
    )
    try:
        from .law import SYSTEM_PROMPT_ADDENDUM

        response = _call_model(
            config.model, prompt,
            system=PATCH_SYSTEM + "\n\n" + SYSTEM_PROMPT_ADDENDUM,
        )
        from .analyzer import extract_json

        parsed = extract_json(response, envelope_key="fixed_content")
        fixed = parsed.get("fixed_content")
    except ValueError as exc:  # parse-level (UltraQA round 2): ambiguous or
        # unparseable model output is NOT a transport failure — label it so ops
        # triage doesn't chase the model route for a parse problem
        return _finish("error", f"model output unparseable: {str(exc)[:120]}")
    except Exception as exc:  # audit A6: network/HTTP/RuntimeError classes
        # crashed whole cycles through the narrow tuple — fail-open means
        # except Exception or it isn't (LEARNINGS #25c)
        return _finish("error", f"model unavailable: {str(exc)[:120]}")

    if fixed is None or not isinstance(fixed, str):
        return _finish("nofix", "model returned no fix")
    if fixed == content:
        # F10-E001: the no-op compare is EXACT bytes — a whitespace-only
        # (indentation) change is a REAL fix and must reach the tree. The old
        # .strip() compare discarded indentation-sensitive fixes as no-ops.
        # Live-caught (first real attempt, 2026-09-02): a no-op patch flowed
        # through worktree→commit→push→PR and died as an opaque 422. A patch
        # identical to the original is a nofix, caught BEFORE any writes.
        return _finish("nofix", "model patch identical to original (no-op)")

    token = os.environ.get("CODESITTER_GITHUB_TOKEN", "")
    workdir = Path(tempfile.mkdtemp(prefix="fl4write-fix-"))
    askpass_envs: list[dict[str, str]] = []
    try:
        # Fetch the EXACT PR head into a fresh workdir (clone -b HEAD was an
        # invalid ref; cloning the default branch reverted main-side changes).
        fetch_url = f"https://github.com/{pr.repo}.git"
        if _run(["git", "init", "-q"], cwd=workdir).returncode != 0:
            return _finish("error", "git init failed")
        pull_env = _git_hardened_env(_push_token_env(workdir, token))
        askpass_envs.append(pull_env)
        fetch = _run(
            ["git", "fetch", "-q", "--depth", "1", fetch_url, pr.head_sha],
            cwd=workdir, timeout=180, env=pull_env,
        )
        _drop_askpass(pull_env)  # token helper gone before any code checkout
        if fetch.returncode != 0:
            return _finish("error", f"fetch of PR head failed: {fetch.stderr[-100:]}")
        if _run(["git", "checkout", "-q", "--detach", "FETCH_HEAD"], cwd=workdir).returncode != 0:
            return _finish("error", "checkout of PR head failed")
        head_verify = _run(["git", "rev-parse", "HEAD"], cwd=workdir)
        if head_verify.stdout.strip() != pr.head_sha:
            return _finish("error", "checked-out SHA does not match PR head — refusing")

        err = _write_contained(workdir, finding.path, fixed)
        if err:
            return _finish("error", err)

        # F8-002: untrusted test code must never run in the tree we commit
        # from — copy the tree (minus .git) and execute the suite there, so
        # hooks/target-file tampering cannot ride into the bot's commit
        testdir = Path(tempfile.mkdtemp(prefix="fl4write-fix-test-"))
        try:
            copy = _run(["cp", "-a", f"{workdir}/.", f"{testdir}/"], cwd=workdir)
            if copy.returncode != 0:
                return _finish("error", "test-tree copy failed")
            import shutil as _sh
            _sh.rmtree(testdir / ".git", ignore_errors=True)
            tested = _run_tests(testdir, config)
        finally:
            shutil.rmtree(testdir, ignore_errors=True)
        if not tested:
            return _finish("testfail", "tests failed with fix applied")

        # F8-002 + F10-E001: the bytes about to be staged must still be the
        # model-tested patch, byte for byte (tests ran in an isolated copy;
        # this is the workdir belt against same-process interference). Reads
        # FAIL CLOSED — a deleted/unreadable target must never ride into the
        # fix PR, and whitespace tampering is caught by exact comparison.
        try:
            staged_now = (workdir / finding.path).read_bytes().decode("utf-8")
        except OSError:
            return _finish("error", "target unreadable before staging (integrity) — refused")
        if staged_now != fixed:
            return _finish("error", "target changed after tests (integrity) — refused")
        staged = _run(["git", "add", "--", finding.path], cwd=workdir)
        if staged.returncode != 0:
            return _finish("error", f"git add failed: {staged.stderr[-80:]}")
        # F12-B001: privileged git ignores global/system config and hooks
        # (test-polluted HOME .gitconfig must never steer the real commit)
        commit_env = _git_hardened_env(_sandbox_env())
        # MECE round-3 (sol F3-003): the sandbox strips git identity vars and
        # HOME (~/.gitconfig) — every automated commit silently failed
        # "Please tell me who you are" (0 landed fixes explained). Identity is
        # explicit and bot-scoped.
        commit_env.update({
            "GIT_AUTHOR_NAME": "fl4write[bot]",
            "GIT_AUTHOR_EMAIL": "fl4write@kyanitelabs.tech",
            "GIT_COMMITTER_NAME": "fl4write[bot]",
            "GIT_COMMITTER_EMAIL": "fl4write@kyanitelabs.tech",
        })
        # the index tree is captured BEFORE the commit — post-commit the
        # committed tree must equal it (hook/race belt: untested bytes must
        # never ride into the commit)
        tree_before = _run(["git", "write-tree"], cwd=workdir, env=commit_env)
        if tree_before.returncode != 0 or not tree_before.stdout.strip():
            return _finish("error", "cannot capture pre-commit tree (integrity) — refused")
        commit = _run(
            ["git", "commit", "-q", "-m",
             f"fix({finding.rule_id}): {scrub.inline(finding.message, 60)}\n\n"
             "Co-authored-by: fl4write <fl4write@kyanitelabs.tech>"],
            cwd=workdir, env=commit_env,
        )
        if commit.returncode != 0:
            # empty commit vs environmental failure must be told apart (A8):
            # nofix would misroute ops triage and the ci-watch break heuristic
            if "nothing to commit" in (commit.stderr or ""):
                return _finish("nofix", "nothing to commit (patch was a no-op)")
            return _finish("error", f"git commit failed: {commit.stderr[-80:]}")
        tree_after = _run(["git", "rev-parse", "HEAD^{tree}"], cwd=workdir, env=commit_env)
        if tree_after.returncode != 0 or tree_after.stdout.strip() != tree_before.stdout.strip():
            # F12-B001: committed tree != the tree whose bytes were tested —
            # something modified content between staging and commit
            return _finish("error", "committed tree differs from staged tree (integrity) — refused")
        # F8-003: a stable hash of head/rule/path/line — plain rule-id
        # branches collided across fix rounds and findings (non-fast-forward
        # pushes failed silently)
        import hashlib as _hl
        _tag = _hl.blake2b(
            f"{pr.head_sha}:{finding.rule_id}:{finding.path}:{finding.line}".encode(),
            digest_size=6).hexdigest()
        branch = f"fl4write/fix-{pr.number}-{_tag}"
        _run(["git", "branch", "-M", branch], cwd=workdir)
        # F13-B001: privileged push env is hardened (global/system git config
        # can never steer an authenticated push)
        push_env = _git_hardened_env(_push_token_env(workdir, token))
        askpass_envs.append(push_env)
        push = _run(
            ["git", "push", "-q", fetch_url, f"HEAD:refs/heads/{branch}"],
            cwd=workdir, timeout=120, env=push_env,
        )
        _drop_askpass(push_env)
        if push.returncode != 0:
            # F12-B003 (reopened F8-003): a retry after a failed PR creation
            # re-created the same branch from the same parent (a NEW sibling
            # commit) and the plain push rejected forever as non-fast-forward.
            # The branch is bot-owned under the own-PR rail: one force-with-
            # lease retry reconciles it; anything else is a real error.
            # F13-B002: the retry needs a FRESH askpass helper — the first
            # helper is already dropped (GIT_ASKPASS would point at a deleted
            # file and the retry would fail authentication)
            push2_env = _git_hardened_env(_push_token_env(workdir, token))
            askpass_envs.append(push2_env)
            push2 = _run(
                ["git", "push", "-q", "--force-with-lease", fetch_url,
                 f"HEAD:refs/heads/{branch}"],
                cwd=workdir, timeout=120, env=push2_env,
            )
            _drop_askpass(push2_env)
            if push2.returncode != 0:
                return _finish("error", f"push failed: {push2.stderr[-100:]}")

        base = _default_branch(pr.repo)
        from .renderer import _md_escape_block, path_plain  # heading-safe
        # model prose; display-form paths (MECE round-5, terra F5-002)

        new_pr = _gh_api("POST", f"/repos/{pr.repo}/pulls", {
            "title": f"fix({finding.rule_id}): {scrub.inline(finding.message, 60)}",
            "head": branch,
            "base": base,
            "body": (
                "Automated fix by FL4WRITE.\n\n"
                f"Finding: [{finding.severity}] {path_plain(finding.path)}:{finding.line} — {scrub.inline(finding.message)}\n"
                f"Proposal: {_md_escape_block(finding.proposal)}\n\nTests pass. Review and merge."
            ),
        })
        return _finish("pr_opened", "", pr_number=new_pr["number"],
                       pr_url=new_pr["html_url"], branch=branch)
    except Exception as exc:  # contained into a result dict
        return _finish("error", str(exc)[:200])
    finally:
        # MECE round-1 (luna F1-04): token-bearing askpass helpers lived in
        # sibling temp dirs and survived EXCEPTION paths (timeouts etc.) —
        # always drop every helper created this attempt, then the workdir.
        for e in askpass_envs:
            _drop_askpass(e)
        shutil.rmtree(workdir, ignore_errors=True)


def _pytest_verify_argv(parts: list[str]) -> list[str] | None:
    """Model the pytest part of a configured test_cmd for the DIFF-OWN-TESTS
    run. Options ride through with EXPLICIT arity; anything outside the model
    returns None — the caller degrades to UNVERIFIED instead of mis-parsing
    (F10-B001/E002, reopened F8-006: '-q tests/' used to swallow the suite
    path as -q's 'value'; value-taking options like -k lost their values).

    Model: long attached (--opt=val) kept; single-dash tokens are short-flag
    bundles (-q, -xv) OR short-with-attached-value (-kexpr) OR known separate
    forms; positional tokens are DROPPED (replaced by the diff's own files).
    """
    # short flags (no value) and short options that take a separate value
    _SHORT_FLAGS = frozenset("qvxsl")
    _SHORT_VALUE = frozenset("ckmoprW")
    # long flags (no value) with the pytest core grammar fl4write knows
    _LONG_FLAGS = frozenset({
        "--verbose", "--quiet", "--exitfirst", "--lf", "--ff", "--collect-only",
        "--no-header", "--disable-warnings", "--strict", "--strict-markers",
        "--continue-on-collection-errors", "--no-summary", "--keep-duplicates",
        "--no-cov", "--pdb", "--tb-native", "--pyargs",
    })
    # long options (and short options) that take a separate value
    _LONG_VALUE = frozenset({
        "-c", "-k", "-m", "-o", "-p", "-r", "-W",
        "--maxfail", "--tb", "--rootdir", "--basetemp", "--deselect",
        "--ignore", "--ignore-glob", "--confcutdir", "--override-ini",
        "--junitxml", "--junit-prefix", "--color", "--log-level", "--timeout",
        "--durations", "--durations-min", "--cov", "--cov-report",
    })
    try:
        i = parts.index("pytest")
    except ValueError:
        return None
    out = list(parts[: i + 1])
    j = i + 1
    while j < len(parts):
        tok = parts[j]
        if tok == "--":
            break  # everything after the separator is pytest's own paths
        if not tok.startswith("-"):
            j += 1  # positional path — replaced by the diff's own files
            continue
        if tok.startswith("--") and "=" in tok:
            out.append(tok)  # --opt=value rides through verbatim
            j += 1
            continue
        if tok.startswith("--"):
            if tok in _LONG_FLAGS:
                out.append(tok)
                j += 1
            elif tok in _LONG_VALUE and j + 1 < len(parts):
                out += [tok, parts[j + 1]]
                j += 2
            else:
                return None  # unmodeled long grammar — fail closed
            continue
        # single-dash: bundle of short flags, short+attached value, or known
        # short option with a separate value
        if len(tok) == 2:
            if tok in _LONG_VALUE and j + 1 < len(parts):
                out += [tok, parts[j + 1]]
                j += 2
            elif tok in _LONG_VALUE:
                return None  # value missing — pytest itself would refuse
            elif all(c in _SHORT_FLAGS for c in tok[1:]):
                out.append(tok)
                j += 1
            else:
                return None
            continue
        body = tok[1:]
        if body[0] in _SHORT_VALUE:
            out.append(tok)  # -kexpr / -mexpr attached form
            j += 1
        elif all(c in _SHORT_FLAGS for c in body):
            out.append(tok)  # -qx bundled flags
            j += 1
        else:
            return None
    return out


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
        verify_askpass: list[dict[str, str]] = []
        fetch_url = f"https://github.com/{pr.repo}.git"
        if _run(["git", "init", "-q"], cwd=workdir).returncode != 0:
            return None
        pull_env = _push_token_env(workdir, token)
        verify_askpass.append(pull_env)
        if _run(["git", "fetch", "-q", "--depth", "1", fetch_url, pr.head_sha],
                cwd=workdir, timeout=180, env=pull_env).returncode != 0:
            return None
        _drop_askpass(pull_env)  # MECE round-3 (sol F3-002): the token helper
        # must be gone BEFORE untrusted test code executes — it used to live
        # until finally, readable by same-user tests during the run
        if _run(["git", "checkout", "-q", "--detach", "FETCH_HEAD"], cwd=workdir).returncode != 0:
            return None
        # ONLY the diff's own test files — the whole-suite default would
        # attribute MAIN's pre-existing red to this diff (audit A3: a
        # false-Critical machine wearing the word 'deterministic').
        import shlex

        py_tests = [f for f in test_files if f.endswith(".py")]
        chain = bool(config.test_cmd and any(m in config.test_cmd for m in ("&&", ";", "|")))
        if config.test_cmd and "pytest" not in config.test_cmd.split():
            # F10-E003 (sol DOM-E, reopened F8-007): chained test_cmds
            # (DialectOS class: install+suite) and custom runners CANNOT run
            # THE DIFF'S OWN tests with host-controlled evidence — a whole-
            # suite chain run would attribute unrelated baseline red to the
            # changed file as a deterministic Critical. UNVERIFIED, no run.
            log.warning("verify_diff_tests: test_cmd %r cannot isolate the "
                        "diff's own tests — UNVERIFIED (no run, no finding)",
                        config.test_cmd)
            return None
        if chain:
            # reached only when test_cmd mentions pytest in a chain word
            # (e.g. 'pytest x && ...'): same UNVERIFIED contract
            log.warning("verify_diff_tests: chained test_cmd %r cannot isolate "
                        "the diff's own tests — UNVERIFIED (no run, no finding)",
                        config.test_cmd)
            return None
        else:
            # MECE round-6 (sol F6-E02/E03): the verify gate runs THE DIFF'S
            # OWN TESTS ONLY (audit A3) — an explicit pytest test_cmd must not
            # silently replace the changed-test paths with the whole suite
            # (unrelated baseline red minted false deterministic Criticals),
            # filenames stay LIST ELEMENTS (never joined then split — spaces
            # and option-like names corrupt), and paths ride behind '--' so
            # pytest never parses a 'test_-x.py' as an option.
            if config.test_cmd:
                parts = shlex.split(config.test_cmd)
                cmd = config.test_cmd
                if "pytest" in parts:
                    # F10-B001/E002 (reopened F8-006): option arity is modeled
                    # explicitly (_pytest_verify_argv); unmodeled grammar
                    # degrades to UNVERIFIED — never a mis-parsed argv
                    argv = _pytest_verify_argv(parts)
                    if argv is None:
                        log.warning("verify_diff_tests: pytest test_cmd %r uses "
                                    "option grammar outside the modeled "
                                    "allowlist — UNVERIFIED (no run, no finding)",
                                    config.test_cmd)
                        return None
                else:
                    log.warning("verify_diff_tests: test_cmd %r is not pytest — "
                                "UNVERIFIED (no run, no finding)", config.test_cmd)
                    return None
            else:
                argv = ["python3", "-m", "pytest"]
                cmd = "python3 -m pytest"
            if py_tests:
                argv += ["--"] + py_tests
            elif test_files:
                # F8-007: changed tests pytest cannot target (non-.py files
                # under an explicit pytest runner) must never fall back to a
                # whole-suite run — UNVERIFIED, never a misattributed
                # deterministic Critical
                log.warning("verify_diff_tests: changed tests are not python "
                            "under a pytest runner — UNVERIFIED")
                return None
            else:
                argv += ["tests/"]  # no changed python tests: repo default
            # options ride BEFORE the '--' separator (never after the file
            # paths): default quiet/line output + configured deselects.
            # F12-B006: known_env_failures used to apply ONLY to explicit
            # test_cmds — the default pytest path silently ran a changed
            # known-broken test and minted a false deterministic Critical
            extra: list[str] = ["-q", "--tb=line"] if not config.test_cmd else []
            for excl in config.known_env_failures:
                if not any(excl in a for a in extra):
                    extra += ["--deselect", excl]
            if extra:
                try:
                    sep = argv.index("--")
                except ValueError:
                    sep = len(argv)
                argv = argv[:sep] + extra + argv[sep:]
        # F13-B001 (round 13, CRITICAL, reopened F12-B001): verifier tests are
        # EXECUTED untrusted code — they used to run with the REAL HOME (the
        # token helper was dropped but ~/.sinter stayed readable) and could
        # plant ~/.gitconfig that later privileged git honored. Fresh
        # disposable HOME per run, sandbox env; cleaned in the function
        # finally alongside the workdir.
        _vhome = tempfile.mkdtemp(prefix="fl4write-verify-home-")
        env = _sandbox_env_for(_vhome)
        import time as _time
        _t0 = _time.time()
        from . import telemetry as _tel
        if "pytest" in cmd and not chain:
            # host-controlled evidence (UltraQA P4/Sol): junit is written only
            # by a suite that genuinely completed; os._exit(0) at import can
            # fake rc and text, never the junit artifact.
            junit_dir = Path(tempfile.mkdtemp(prefix="fl4write-verify-junit-"))
            junit = junit_dir / "results.xml"
            try:
                green, result = _pytest_evidence(argv, workdir, config.test_timeout, env, junit)
                if not green:
                    # F11-B005 (round 11, luna DOM-B, reopened F8-008): a
                    # non-green junit run is a REAL test failure only when the
                    # suite COMPLETED and wrote failures. Missing evidence with
                    # a NONZERO exit (import/collection/env failures) and
                    # errors-only junit are infrastructure trouble = UNVERIFIED,
                    # never a deterministic Critical. A zero-exit with NO junit
                    # stays the hostile killed-suite class (a finding).
                    import xml.etree.ElementTree as _ET
                    if not junit.exists() and result.returncode != 0:
                        log.warning("verify_diff_tests: pytest exited %s with no "
                                    "junit evidence — infra UNVERIFIED, no finding",
                                    result.returncode)
                        # F12-B012: infra paths emit their terminal outcome too
                        _tel.emit("verify_tests", repo=pr.repo, head=pr.head_sha[:10],
                                  cmd=cmd, files=test_files, ok=False, unverified=True,
                                  latency_s=round(_time.time() - _t0, 1))
                        return None
                    if junit.exists():
                        try:
                            _root = _ET.parse(junit).getroot()
                            _suites = [_root] if _root.tag == "testsuite" \
                                else _root.findall("testsuite")
                            _fails = sum(int(s.get("failures", "0") or 0) for s in _suites)
                            _errs = sum(int(s.get("errors", "0") or 0) for s in _suites)
                            if _fails == 0 and _errs > 0:
                                log.warning("verify_diff_tests: junit shows errors-only "
                                            "(%s) — infra UNVERIFIED, no finding", _errs)
                                _tel.emit("verify_tests", repo=pr.repo,
                                          head=pr.head_sha[:10], cmd=cmd,
                                          files=test_files, ok=False, unverified=True,
                                          latency_s=round(_time.time() - _t0, 1))
                                return None
                        except Exception as exc:  # noqa: BLE001
                            log.warning("verify_diff_tests: junit unreadable (%s) — "
                                        "infra UNVERIFIED, no finding", exc)
                            _tel.emit("verify_tests", repo=pr.repo,
                                      head=pr.head_sha[:10], cmd=cmd,
                                      files=test_files, ok=False, unverified=True,
                                      latency_s=round(_time.time() - _t0, 1))
                            return None
            finally:
                shutil.rmtree(junit_dir, ignore_errors=True)
        else:
            # chained or non-pytest runner: no host-controlled evidence yet —
            # rc is the only signal; a zero-exit with NO output is treated as
            # UNPROVEN (never a clean claim, never a false "did not run")
            result = _run(argv, cwd=workdir, timeout=config.test_timeout, env=env)
            green = result.returncode == 0
            if green and not f"{result.stdout}\n{result.stderr}".strip():
                green = False
        _tel.emit("verify_tests", repo=pr.repo, head=pr.head_sha[:10], cmd=cmd,
                  files=test_files, ok=green, latency_s=round(_time.time() - _t0, 1))
        if green:
            return None
        if not green and "pytest" in cmd and not chain:
            pass  # junit-gated pytest failures ARE test failures
        elif not green:
            # F8-008: distinguish setup/infrastructure failure (install,
            # missing deps, env) from a COMPLETED failing test run — the
            # DialectOS chain begins with 'corepack pnpm install', and an
            # install error used to mint a deterministic Critical
            text_all = f"{result.stdout}\n{result.stderr}"
            setup_err = bool(re.search(
                r"(npm|pnpm|corepack|yarn|pip|poetry|go (?:mod|build|install)|"
                r"EACCES|ENOENT|Cannot find module|command not found|Install failed|"
                r"Could not resolve|Network (?:error|timeout))",
                text_all, re.IGNORECASE))
            test_signal = bool(re.search(
                r"(collected \d+|\d+ (?:passed|failed)|passed|FAILED|failed|"
                r"All tests passed|Tests:|\bOK\b|not ok)",
                text_all, re.IGNORECASE))
            if setup_err and not test_signal:
                log.warning("verify_diff_tests: setup/infrastructure failure \u2014 "
                            "UNVERIFIED, no finding (rc=%s)", result.returncode)
                return None
        tail = (result.stdout + "\n" + result.stderr).strip().splitlines()
        # Sol-B2: the verifier records the EXACT evidence it ran — command,
        # files, head SHA — so the claim is auditable, not asserted
        return _Finding(
            rule_id="tests",
            severity="Critical",
            path=test_files[0] if test_files else "tests",
            line=1,
            category="CI",
            message=(
                f"The diff's own tests FAIL or did not run (verified: cmd={cmd!r}; "
                f"files={test_files!r}; head={pr.head_sha[:10]}): "
                + " | ".join(tail[-3:])[:240]
            ),
        )
    except Exception as exc:  # noqa: BLE001 — infrastructure trouble is never a finding
        log.warning("verify_diff_tests infra failure for %s#%s: %s", pr.repo, pr.number, exc)
        return None
    finally:
        for e in verify_askpass:  # MECE round-1 (luna F1-04): drop on every path
            _drop_askpass(e)
        shutil.rmtree(workdir, ignore_errors=True)
        # F13-B001: the per-run disposable test HOME dies with the attempt
        try:
            shutil.rmtree(_vhome, ignore_errors=True)
        except NameError:
            pass


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
    prs: list = []
    try:
        page = 1
        while True:  # MECE round-3 (sol F3-007): paginate — fix PRs past the
            # first page were never evaluated or merged
            if page > 20:
                # F11-B008: a liveness bound — a forge that keeps returning
                # full pages must not block the cycle forever
                log.warning("own-PR scan on %s: >20 full pages — capped "
                            "(rows past the cap invisible to this scan)", config.repo)
                break
            batch = _gh_api("GET",
                            f"/repos/{config.repo}/pulls?state=open&per_page=100&page={page}")
            if not isinstance(batch, list):
                break
            prs += batch
            if len(batch) < 100:
                break
            page += 1
    except Exception as exc:

        log.warning("own-PR scan failed for %s: %s", config.repo, exc)
        return merged
    for pr_data in prs:
        number = None  # F7-B001: excepts below must never NameError
        try:  # F7-B001: row-level containment starts BEFORE field access —
            # a malformed row must skip, never kill the scan for later PRs
            if not isinstance(pr_data, dict):
                log.warning("own-PR scan: malformed row skipped: %s", str(pr_data)[:120])
                continue
            # F10-B004: booleans are not numbers — int(True) == 1 would make a
            # forged boolean row target PR #1
            number = pr_data.get("number")
            if isinstance(number, bool) or not isinstance(number, int) or number <= 0:
                log.warning("own-PR scan: unusable row number %r skipped", number)
                continue
            head_ref = (pr_data.get("head") or {}).get("ref", "")
            if not head_ref.startswith("fl4write/"):
                continue
            author = (pr_data.get("user") or {}).get("login", "")
            # MECE round-1 (luna F1-05): check-runs must be PAGINATED — the
            # default page (~100) hid failing runs on CI-heavy repos, which
            # would let the merge gate bless a red PR as green
            page = 1
            check_runs: list[dict] = []
            checks_capped = False
            while True:
                if page > 20:
                    # F11-B008: liveness bound — CI-heavy repos must not block
                    # the whole cycle on an endless check-run stream.
                    # F12-B004: capped evidence is INCOMPLETE — a pending or
                    # failing run past the cap must never merge (ci_green is
                    # forced False below)
                    log.warning("check-runs scan on %s#%s: >20 full pages — capped "
                                "(ci_green forced false)", config.repo, number)
                    checks_capped = True
                    break
                checks = _gh_api(
                    "GET",
                    f"/repos/{config.repo}/commits/{pr_data['head']['sha']}/check-runs"
                    f"?per_page=100&page={page}")
                batch = checks.get("check_runs") or []
                check_runs += batch
                if len(batch) < 100:
                    break
                page += 1
            runs = [c for c in check_runs if c.get("status") == "completed"]
            pending = [c for c in check_runs if c.get("status") != "completed"]
            # Non-vacuous gate: no checks at all is NOT green; pending runs
            # are NOT green (all([]) used to bless both).
            ci_green = bool(runs) and not pending and all(c.get("conclusion") == "success" for c in runs)
            if checks_capped:
                ci_green = False  # F12-B004: partial evidence never merges
            # F8-005: legacy commit STATUSES also gate — check-runs green with
            # a failing commit status must never authorize a merge
            try:
                combined = _gh_api("GET",
                                   f"/repos/{config.repo}/commits/{pr_data['head']['sha']}/status")
            except Exception:  # noqa: BLE001 - status probe failure = not green
                combined = {}
            combined_state = (combined or {}).get("state") if isinstance(combined, dict) else None
            if combined_state != "success":
                ci_green = False
            # The gate re-verifies authorship + CI IN CODE. is_own_identity
            # accepts the current + legacy bot slugs across renames.
            merge_own_pr(author=author, bot_identity=bot_identity, ci_green=ci_green, config=config)
            _gh_api("PUT", f"/repos/{config.repo}/pulls/{number}/merge", {
                "merge_method": "squash",
                "sha": pr_data["head"]["sha"],  # F8-004: precondition
            })
            merged.append({"pr": number, "status": "merged"})
            log.info("merged own fix PR #%s on %s (owner=%s)", number, config.repo, owner)
        except FixLaneBlocked as exc:
            log.info("PR #%s not mergeable yet: %s", number, exc)  # per-PR skip, scan continues
        except Exception as exc:

            log.warning("merge failed for #%s: %s", number, exc)
    return merged
