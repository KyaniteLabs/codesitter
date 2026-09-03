"""Forge adapters — GitHub and Forgejo/Gitea over one interface.

Adapter laws (ralplan-approved):
- The engine speaks only normalized entities (models.py); adapters translate.
- Rendering degradation is ADAPTER responsibility: what a forge cannot render
  degrades to prose, never drops a finding.
- Capability flags: `supports_fork_ci_approval` etc.; a required-but-absent
  capability fails closed into a "manual action needed" note, never silence.
- Mirrors: adapters report the SAME PR identity (head SHA) so the engine's
  dedupe layer drops mirror copies without a second review.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import Any

from .config import ForgeBinding
from . import renderer
from .models import PullRequest

try:
    from importlib.metadata import PackageNotFoundError, version as _pkg_version
    USER_AGENT = f"fl4write/{_pkg_version('fl4write')}"
except PackageNotFoundError:  # running from a clone without install
    USER_AGENT = "fl4write/dev"

# The app was renamed kyanitelabs -> fl4write (2026-09-01), which changed the
# bot login. Comments authored under EITHER slug are ours; both are accepted
# so pre-rename comments still edit-in-place instead of duplicating.
# fl4write[bot] is in the LEGACY set too: under PAT-fallback auth the
# expected login is the personal account, but our app-authored comments
# must still be recognized as ours (audit F8 — storm reborn via dep gap).
LEGACY_BOT_LOGINS = ("kyanitelabs[bot]", "fl4write[bot]")


def is_own_identity(author: str, bot_login: str) -> bool:
    return author == bot_login or author in LEGACY_BOT_LOGINS


def _parse_iso(raw: str):
    """ISO timestamps from forges (trailing Z) and from our own state file
    (+00:00) into one comparable datetime; None when unparseable."""
    from datetime import datetime

    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


class ForgeError(RuntimeError):
    pass


class ForgeAdapter:
    name = "base"
    page_size_param = "per_page"  # Gitea/Forgejo uses `limit`

    def __init__(self, binding: ForgeBinding):
        self.binding = binding
        self.base = binding.api_base.rstrip("/")

    def _headers(self) -> dict[str, str]:
        h = {"Accept": "application/json", "User-Agent": USER_AGENT}
        token = os.environ.get(self.binding.token_env, "")
        if token:
            h["Authorization"] = f"token {token}"
        return h

    def _call(self, method: str, path: str, payload: dict[str, Any] | None = None,
              _retry: bool = True) -> Any:
        """One API call. GETs retry ONCE on throttle/transient (403/429/5xx),
        honoring Retry-After up to 30s; POSTs never blind-retry (double-post
        risk). Every failure names the forge, method, and path."""
        req = urllib.request.Request(
            f"{self.base}{path}",
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={**self._headers(), "Content-Type": "application/json"},
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read().decode()
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as exc:
            if method == "GET" and _retry and exc.code in (403, 429, 500, 502, 503, 504):
                wait = 0.0
                if exc.headers and exc.headers.get("Retry-After"):
                    try:
                        wait = min(float(exc.headers["Retry-After"]), 30.0)
                    except ValueError:
                        pass
                time.sleep(wait)
                return self._call(method, path, payload, _retry=False)
            raise ForgeError(f"{self.name} {method} {path}: HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            if method == "GET" and _retry:
                time.sleep(1)
                return self._call(method, path, payload, _retry=False)
            raise ForgeError(f"{self.name} {method} {path}: {exc}") from exc

    def _call_text(self, method: str, path: str, _retry: bool = True) -> str:
        """One API call returning RAW TEXT (the Gitea .diff endpoint is
        text/plain — json.loads would crash on it). Same retry/throttle
        semantics as _call."""
        req = urllib.request.Request(
            f"{self.base}{path}", headers=self._headers(), method=method
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read().decode()
        except urllib.error.HTTPError as exc:
            if method == "GET" and _retry and exc.code in (403, 429, 500, 502, 503, 504):
                time.sleep(1)
                return self._call_text(method, path, _retry=False)
            raise ForgeError(f"{self.name} {method} {path}: HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            if method == "GET" and _retry:
                time.sleep(1)
                return self._call_text(method, path, _retry=False)
            raise ForgeError(f"{self.name} {method} {path}: {exc}") from exc

    # Subclass responsibilities -------------------------------------------
    def list_open_prs(self, repo: str) -> list[PullRequest]:  # pragma: no cover - interface
        raise NotImplementedError

    def list_merged_prs(self, repo: str, since_iso: str) -> list[PullRequest]:  # pragma: no cover - interface
        """PRs merged AFTER since_iso (exclusive), oldest first. The post-merge
        sweep's discovery mechanism — a merged PR is invisible to list_open_prs."""
        raise NotImplementedError

    bot_login: str = "fl4write[bot]"

    def _paginated(self, path: str, page_size: int, max_pages: int = 10) -> list[dict]:
        """Page through until a short page (finding 6: PRs/comments past
        page one must not be invisible)."""
        out: list[dict] = []
        for page in range(1, max_pages + 1):
            batch = self._call(
                "GET", f"{path}{'&' if '?' in path else '?'}page={page}&{self.page_size_param}={page_size}"
            )
            if not isinstance(batch, list):
                raise ForgeError(f"paginated {path}: unexpected shape")
            out.extend(batch)
            if len(batch) < page_size:
                break
        return out

    def reaction_summary(self, repo: str, comment_id: int) -> dict[str, dict[str, int]] | None:
        """Reactions on one of OUR comments: {content: {login: 1}} — best-effort,
        returns None when the forge/repo has the endpoint disabled."""
        try:
            rows = self._paginated(f"/repos/{repo}/issues/comments/{comment_id}/reactions", page_size=100)
        except ForgeError:
            return None
        out: dict[str, dict[str, int]] = {}
        for r in rows if isinstance(rows, list) else []:
            content = r.get("content")
            login = ((r.get("user") or {}).get("login") or "?")
            if content:
                out.setdefault(content, {})[login] = 1
        return out

    # CI-watch surface. None everywhere = "cannot query" (the step degrades,
    # never crashes the cycle). check-runs (Actions/GHA) only in v1; commit
    # statuses API not polled.
    def head_check_runs(self, repo: str) -> tuple[str, list[dict]] | None:  # pragma: no cover - interface
        """(default-branch HEAD sha, check-run dicts) or None unqueryable."""
        raise NotImplementedError

    def get_pr_diff(self, repo: str, number: int) -> tuple[set[str], str] | None:  # pragma: no cover - interface
        """(changed-file set, unified diff text) or None when unfetchable.
        GitHub uses the gh-CLI path in cli.make_get_diff; adapters without a
        native endpoint must return None, never a fake empty diff."""
        raise NotImplementedError

    def path_exists(self, repo: str, path: str) -> bool | None:
        """Does `path` exist on the CURRENT default branch? True/False, or
        None when unqueryable (the retro freshness gate fails OPEN on None —
        keep the finding, a dropped real finding is worse than a stale one)."""
        from urllib.parse import quote

        try:
            self._call("GET", f"/repos/{repo}/contents/{quote(path, safe='')}")
            return True
        except ForgeError as exc:
            if "HTTP 404" in str(exc):
                return False
            return None

    def path_is_file(self, repo: str, path: str, ref: str | None = None) -> bool | None:
        """Is `path` a FILE (not a directory) at `ref` (default branch when
        None)? The contents API answers directories with a LIST — an HTTP 200
        is not a file. Live 2026-09-03: GH Actions run-level annotations anchor
        at the workflow dir (path ".github"), and the fix lane cannot fetch a
        directory. True/False, or None when unqueryable (callers keep the
        finding on None — fail-open, a dropped real finding is worse than a
        stale one)."""
        from urllib.parse import quote

        q = f"/repos/{repo}/contents/{quote(path, safe='')}"
        if ref:
            q += f"?ref={quote(ref, safe='')}"
        try:
            data = self._call("GET", q)
        except ForgeError as exc:
            if "HTTP 404" in str(exc):
                return False
            return None
        return isinstance(data, dict) and bool(data.get("content"))

    def check_annotations(self, repo: str, check_run_id: int) -> list[dict] | None:
        """Annotations for one check-run: [{path, start_line, message, level}]."""
        try:
            rows = self._paginated(f"/repos/{repo}/check-runs/{check_run_id}/annotations", page_size=50)
        except ForgeError:
            return None
        out = []
        for a in rows if isinstance(rows, list) else []:
            out.append({
                "path": a.get("path") or "",
                "start_line": a.get("start_line") or a.get("line") or 0,
                "message": a.get("message") or "",
                "level": a.get("annotation_level") or "",
            })
        return out

    # Omnisweep surface (issue-backed report + tree discovery). None/False
    # everywhere = degrade (findings live in state; the report retries).
    def open_issue(self, repo: str, title: str, body: str) -> int | None:  # pragma: no cover - interface
        """Create an issue; return its number, or None when creation failed."""
        raise NotImplementedError

    def update_issue(self, repo: str, number: int, body: str) -> bool:  # pragma: no cover - interface
        """Edit an issue body in place (edit-in-place never re-notifies)."""
        raise NotImplementedError

    def list_tree_files(self, repo: str) -> tuple[list[tuple[str, int]], bool] | None:
        """([(path, size_bytes), ...], truncated) for the default-branch HEAD,
        or None when unqueryable. One recursive git-trees call; `truncated`
        flags GitHub's 100k-entry/7MB cap — the caller must ALERT on it."""
        try:
            branch = self._call("GET", f"/repos/{repo}").get("default_branch") or "main"
            head = self._call("GET", f"/repos/{repo}/commits/{branch}")
            sha = head.get("sha") or ""
            if not sha:
                return None
            tree = self._call("GET", f"/repos/{repo}/git/trees/{sha}?recursive=1")
            files = [
                (e.get("path") or "", int(e.get("size") or 0))
                for e in (tree.get("tree") or [])
                if e.get("type") == "blob"
            ]
            return files, bool(tree.get("truncated"))
        except ForgeError:
            return None

    def get_file(self, repo: str, path: str, ref: str) -> str | None:
        """File content at an exact ref, or None when unfetchable. Refuses
        non-base64/empty responses (the >1MB vacuous-premise law — the model
        must never 'review' or fix an empty file it didn't get)."""
        import base64
        from urllib.parse import quote

        try:
            data = self._call("GET", f"/repos/{repo}/contents/{quote(path, safe='')}?ref={quote(ref, safe='')}")
        except ForgeError:
            return None
        if data.get("encoding") != "base64" or not data.get("content"):
            return None
        try:
            return base64.b64decode(data["content"]).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return None

    def get_persistent_comment(self, repo: str, number: int) -> tuple[int, str] | None:  # id, body  # pragma: no cover
        raise NotImplementedError

    def create_comment(self, repo: str, number: int, body: str) -> int:  # pragma: no cover
        raise NotImplementedError

    def update_comment(self, repo: str, number: int, comment_id: int, body: str) -> None:  # pragma: no cover
        raise NotImplementedError


class GitHubAdapter(ForgeAdapter):
    name = "github"
    supports_fork_ci_approval = True

    def list_open_prs(self, repo: str) -> list[PullRequest]:
        data = self._paginated(f"/repos/{repo}/pulls?state=open", page_size=50)
        prs = []
        for p in data:
            prs.append(
                PullRequest(
                    forge=self.name,
                    number=p["number"],
                    repo=repo,
                    title=p.get("title") or "",
                    body=p.get("body") or "",
                    head_sha=p["head"]["sha"],
                    is_fork=bool(p["head"].get("repo") and p["head"]["repo"]["full_name"] != repo),
                    author=(p.get("user") or {}).get("login", ""),
                    is_bot_author=str((p.get("user") or {}).get("type", "")).lower() == "bot",
                    merged_at=p.get("merged_at") or "",
                )
            )
        return prs

    def list_merged_prs(self, repo: str, since_iso: str) -> list[PullRequest]:
        # state=closed includes unmerged (closed-without-merge) PRs: filter on
        # merged_at. sort=updated keeps freshly-touched PRs first, so recent
        # merges arrive in the first pages; the pagination cap (10x50) is the
        # documented discovery bound for very high-volume repos.
        data = self._paginated(
            f"/repos/{repo}/pulls?state=closed&sort=updated&direction=desc", page_size=50
        )
        since = _parse_iso(since_iso)
        prs = []
        for p in data:
            merged_raw = p.get("merged_at") or ""
            if not merged_raw:
                continue
            merged = _parse_iso(merged_raw)
            # STRICT less-than: PRs merged in the SAME second as the watermark
            # stay visible. Bulk waves merge same-second; if the per-cycle cap
            # splits such a pair, the deferred sibling must remain listable —
            # already-terminal ones are skipped free by the head-SHA guard.
            if since is not None and merged is not None and merged < since:
                continue
            prs.append(
                PullRequest(
                    forge=self.name,
                    number=p["number"],
                    repo=repo,
                    title=p.get("title") or "",
                    body=p.get("body") or "",
                    head_sha=p["head"]["sha"],
                    is_fork=bool(p["head"].get("repo") and p["head"]["repo"]["full_name"] != repo),
                    author=(p.get("user") or {}).get("login", ""),
                    is_bot_author=str((p.get("user") or {}).get("type", "")).lower() == "bot",
                    merged_at=merged_raw,
                )
            )
        prs.sort(key=lambda pr: pr.merged_at)  # oldest first: catch-up order
        return prs

    def get_persistent_comment(self, repo: str, number: int) -> tuple[int, str] | None:
        for c in self._paginated(f"/repos/{repo}/issues/{number}/comments", page_size=100):
            body = c.get("body") or ""
            author = ((c.get("user") or {}).get("login") or "").lower()
            # Marker substring alone is hijackable by any commenter (review
            # finding 2): require BOTH marker and our own authorship.
            if any(prefix in body for prefix in renderer.LEGACY_MARKER_PREFIXES) and is_own_identity(
                author, self.bot_login
            ):
                return c["id"], body
        return None

    def create_comment(self, repo: str, number: int, body: str) -> int:
        return self._call("POST", f"/repos/{repo}/issues/{number}/comments", {"body": body})["id"]

    def update_comment(self, repo: str, number: int, comment_id: int, body: str) -> None:
        self._call("PATCH", f"/repos/{repo}/issues/comments/{comment_id}", {"body": body})

    def head_check_runs(self, repo: str) -> tuple[str, list[dict]] | None:
        try:
            branch = self._call("GET", f"/repos/{repo}").get("default_branch") or "main"
            head = self._call("GET", f"/repos/{repo}/commits/{branch}")
            sha = head.get("sha") or ""
            if not sha:
                return None
            runs = self._call("GET", f"/repos/{repo}/commits/{sha}/check-runs")
            return sha, list(runs.get("check_runs") or [])
        except ForgeError:
            return None

    def open_issue(self, repo: str, title: str, body: str) -> int | None:
        try:
            return self._call("POST", f"/repos/{repo}/issues", {"title": title, "body": body})["number"]
        except ForgeError:
            return None

    def update_issue(self, repo: str, number: int, body: str) -> bool:
        try:
            self._call("PATCH", f"/repos/{repo}/issues/{number}", {"body": body})
            return True
        except ForgeError:
            return False


class ForgejoAdapter(ForgeAdapter):
    """Forgejo/Gitea share the v1 API shape; differences degrade to prose."""

    name = "forgejo"
    supports_fork_ci_approval = False

    def list_open_prs(self, repo: str) -> list[PullRequest]:
        data = self._paginated(f"/repos/{repo}/pulls?state=open", page_size=50)
        prs = []
        for p in data:
            head_repo = ((p.get("head") or {}).get("repo") or {}).get("full_name")
            prs.append(
                PullRequest(
                    forge=self.name,
                    number=p["number"],
                    repo=repo,
                    title=p.get("title") or "",
                    body=p.get("body") or "",
                    head_sha=(p.get("head") or {}).get("sha", ""),
                    is_fork=bool(head_repo and head_repo != repo),
                    author=(p.get("user") or {}).get("login", ""),
                    is_bot_author=str((p.get("user") or {}).get("type", "")).lower() == "bot",
                    merged_at=p.get("merged_at") or "",
                )
            )
        return prs

    def list_merged_prs(self, repo: str, since_iso: str) -> list[PullRequest]:
        # Forgejo/Gitea: closed pulls carry `merged` + `merged_at`; same
        # filtered-paginate shape as GitHub.
        data = self._paginated(f"/repos/{repo}/pulls?state=closed", page_size=50)
        since = _parse_iso(since_iso)
        prs = []
        for p in data:
            merged_raw = p.get("merged_at") or ""
            if not merged_raw or not p.get("merged"):
                continue
            merged = _parse_iso(merged_raw)
            # STRICT less-than: PRs merged in the SAME second as the watermark
            # stay visible. Bulk waves merge same-second; if the per-cycle cap
            # splits such a pair, the deferred sibling must remain listable —
            # already-terminal ones are skipped free by the head-SHA guard.
            if since is not None and merged is not None and merged < since:
                continue
            head_repo = ((p.get("head") or {}).get("repo") or {}).get("full_name")
            prs.append(
                PullRequest(
                    forge=self.name,
                    number=p["number"],
                    repo=repo,
                    title=p.get("title") or "",
                    body=p.get("body") or "",
                    head_sha=(p.get("head") or {}).get("sha", ""),
                    is_fork=bool(head_repo and head_repo != repo),
                    author=(p.get("user") or {}).get("login", ""),
                    is_bot_author=str((p.get("user") or {}).get("type", "")).lower() == "bot",
                    merged_at=merged_raw,
                )
            )
        prs.sort(key=lambda pr: pr.merged_at)
        return prs

    def get_persistent_comment(self, repo: str, number: int) -> tuple[int, str] | None:
        for c in self._paginated(f"/repos/{repo}/issues/{number}/comments", page_size=50):
            body = c.get("body") or ""
            author = ((c.get("user") or {}).get("login") or "").lower()
            if any(prefix in body for prefix in renderer.LEGACY_MARKER_PREFIXES) and is_own_identity(
                author, self.bot_login
            ):
                return c["id"], body
        return None

    def create_comment(self, repo: str, number: int, body: str) -> int:
        return self._call("POST", f"/repos/{repo}/issues/{number}/comments", {"body": body})["id"]

    def update_comment(self, repo: str, number: int, comment_id: int, body: str) -> None:
        self._call("PATCH", f"/repos/{repo}/issues/comments/{comment_id}", {"body": body})

    def head_check_runs(self, repo: str) -> tuple[str, list[dict]] | None:
        return None  # v1: check-runs (GHA) only; Forgejo commit statuses unsupported

    def list_tree_files(self, repo: str) -> tuple[list[tuple[str, int]], bool] | None:
        """Forgejo variant: Gitea's ?recursive=true TRUNCATES at 1000 entries
        (live-caught on KyaniteLabs/liminal: 862 of a much larger tree) and
        Gitea accepts a branch NAME in the trees path — so walk manually:
        root non-recursive, then per-subtree recursion. Complete at any size."""
        try:
            branch = self._call("GET", f"/repos/{repo}").get("default_branch") or "main"
            out: list[tuple[str, int]] = []
            truncated = False

            def walk(sha: str, prefix: str) -> None:
                nonlocal truncated
                t = self._call("GET", f"/repos/{repo}/git/trees/{sha}")
                if t.get("truncated"):
                    truncated = True
                for e in t.get("tree") or []:
                    if e.get("type") == "blob":
                        out.append((prefix + (e.get("path") or ""), int(e.get("size") or 0)))
                    elif e.get("type") == "tree":
                        walk(e.get("sha"), prefix + (e.get("path") or "") + "/")

            root = self._call("GET", f"/repos/{repo}/git/trees/{branch}")
            for e in root.get("tree") or []:
                if e.get("type") == "blob":
                    out.append(((e.get("path") or ""), int(e.get("size") or 0)))
                elif e.get("type") == "tree":
                    walk(e.get("sha"), (e.get("path") or "") + "/")
            return out, truncated
        except ForgeError:
            return None

    def open_issue(self, repo: str, title: str, body: str) -> int | None:
        try:
            return self._call("POST", f"/repos/{repo}/issues", {"title": title, "body": body})["number"]
        except ForgeError:
            return None

    def update_issue(self, repo: str, number: int, body: str) -> bool:
        try:
            self._call("PATCH", f"/repos/{repo}/issues/{number}", {"body": body})
            return True
        except ForgeError:
            return False

    def get_pr_diff(self, repo: str, number: int) -> tuple[set[str], str] | None:
        """(changed-file set, unified diff text) or None when unfetchable.
        Gitea/Forgejo native: the .diff endpoint (probe-verified live on
        git.kyanitelabs.tech, 2026-09-01). Non-diff payloads return None —
        an error page must never masquerade as an empty diff (LEARNINGS #3)."""
        try:
            raw = self._call_text("GET", f"/repos/{repo}/pulls/{number}.diff")
        except ForgeError:
            return None
        if not raw or not raw.startswith("diff --git"):
            return None
        files = set(re.findall(r"^\+\+\+ b/(.+)$", raw, re.MULTILINE))
        if not files:
            return None
        return files, raw


def adapter_for(binding: ForgeBinding) -> ForgeAdapter:
    """Fail-loud adapter selection — unknown forge names abort the cycle."""
    # The binding's api_base distinguishes github.com vs a Forgejo host.
    if "api.github.com" in binding.api_base:
        return GitHubAdapter(binding)
    return ForgejoAdapter(binding)
