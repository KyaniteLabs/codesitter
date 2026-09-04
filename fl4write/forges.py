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

import logging

log = logging.getLogger("fl4write.forges")

try:
    from importlib.metadata import PackageNotFoundError, version as _pkg_version
    USER_AGENT = f"fl4write/{_pkg_version('fl4write')}"
except PackageNotFoundError:  # running from a clone without install
    USER_AGENT = "fl4write/dev"

# MECE round-4 (M3 F4-D08): hard page bound for the ci-watch check-runs scan
# — a server that keeps returning full pages must not spin the cycle forever.
_CHECK_RUN_PAGE_CAP = 100

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
                try:
                    return json.loads(body) if body else {}
                except ValueError as exc:  # MECE round-3 (terra F3-002): a 2xx
                    # non-JSON body (proxy/HTML) must degrade as ForgeError,
                    # not leak JSONDecodeError past the boundaries
                    raise ForgeError(f"{self.name} {method} {path}: non-JSON response") from exc
        except urllib.error.HTTPError as exc:
            if method == "GET" and _retry and exc.code in (403, 429, 500, 502, 503, 504):
                wait = 0.0
                if exc.headers and exc.headers.get("Retry-After"):
                    try:
                        _raw = float(exc.headers["Retry-After"])
                    except ValueError:
                        _raw = float("nan")
                    # F6-307: NaN/negative Retry-After -> bounded 1s, never
                    # time.sleep(raw) crashes or instant-spin
                    wait = min(_raw, 30.0) if _raw >= 0 and _raw == _raw else 1.0
                time.sleep(wait)
                return self._call(method, path, payload, _retry=False)
            raise ForgeError(f"{self.name} {method} {path}: HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            if method == "GET" and _retry:
                time.sleep(1)
                return self._call(method, path, payload, _retry=False)
            raise ForgeError(f"{self.name} {method} {path}: {exc}") from exc
        except (OSError, UnicodeDecodeError) as exc:
            # F6-306: ConnectionReset/other OSErrors and decode failures used
            # to escape as raw exceptions past the ForgeError boundary
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
                wait = 0.0
                if exc.headers and exc.headers.get("Retry-After"):
                    try:
                        _raw = float(exc.headers["Retry-After"])
                    except ValueError:
                        _raw = float("nan")
                    # F6-307: NaN/negative Retry-After -> bounded 1s
                    wait = min(_raw, 30.0) if _raw >= 0 and _raw == _raw else 1.0
                time.sleep(wait)
                return self._call_text(method, path, _retry=False)
            raise ForgeError(f"{self.name} {method} {path}: HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            if method == "GET" and _retry:
                time.sleep(1)
                return self._call_text(method, path, _retry=False)
            raise ForgeError(f"{self.name} {method} {path}: {exc}") from exc
        except (OSError, UnicodeDecodeError) as exc:
            # F6-306: same wrap as _call
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
        else:
            # MECE round-1 (luna F1-008): stopped at max_pages with every page
            # full — rows past the cap exist and are silently invisible
            import logging as _log
            _log.getLogger("fl4write.forges").warning(
                "paginated %s stopped at %d full pages (page_size=%d) — rows past "
                "the cap are invisible to this call", path, max_pages, page_size)
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
            data = self._call("GET", f"/repos/{repo}/contents/{quote(path, safe='')}")
        except ForgeError as exc:
            if "HTTP 404" in str(exc):
                return False
            return None
        # F6-315: a 2xx response that is NOT a contents object (null, scalar,
        # error-shaped JSON) proves nothing — None (unqueryable), so the
        # adoption-loss alert is never suppressed by a malformed success
        if isinstance(data, dict) and ("type" in data or "content" in data or "sha" in data):
            return True
        if isinstance(data, list):
            return True  # directory listing: the path exists
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
        # MECE round-1 (sol F1-004): a valid ZERO-BYTE file has empty content
        # but is still a file — judge by the base64 encoding marker, not by
        # content truthiness; directories answer with a LIST.
        if isinstance(data, dict):
            return data.get("encoding") == "base64" and "content" in data
        if isinstance(data, list):
            return False  # directory: queryable answer, not a file
        # F6-314: any other malformed-success payload is UNQUERYABLE (None),
        # never False — the ci_watch contract keeps findings on None
        return None

    def check_annotations(self, repo: str, check_run_id: int) -> list[dict] | None:
        """Annotations for one check-run: [{path, start_line, message, level}]."""
        try:
            rows = self._paginated(f"/repos/{repo}/check-runs/{check_run_id}/annotations", page_size=50)
        except ForgeError:
            return None
        out = []
        for a in rows if isinstance(rows, list) else []:
            if not isinstance(a, dict):  # MECE round-5 (luna F5-001): null /
                # non-object rows from a shape-drifted forge must degrade here,
                # not AttributeError past the adapter into the cycle
                continue
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
            from urllib.parse import quote

            repo_info = self._call("GET", f"/repos/{repo}")
            if not isinstance(repo_info, dict):
                return None  # F8-003: intermediate envelope validated
            branch = repo_info.get("default_branch") or "main"
            # MECE round-4 (M3 F4-D07): quote branch names containing path
            # chars (e.g. 'release/1.x' default branches) in URL paths
            head = self._call("GET", f"/repos/{repo}/commits/{quote(branch, safe='')}")
            if not isinstance(head, dict):
                return None  # F8-003: commit envelope validated
            sha = head.get("sha") or ""
            if not sha:
                return None
            tree = self._call("GET", f"/repos/{repo}/git/trees/{sha}?recursive=1")
            if not isinstance(tree, dict) or not isinstance(tree.get("tree"), list):
                # F6-309: response-level shape validation
                raise ForgeError(f"{self.name} tree response shape drift on {repo}")
            # MECE round-5 (luna F5-002): malformed (non-object) tree entries
            # must degrade — never AttributeError past the adapter into the
            # cycle. F6-309: sizes coerce-or-drop per row.
            files = []
            for e in tree.get("tree") or []:
                if not isinstance(e, dict) or e.get("type") != "blob":
                    continue
                try:
                    files.append(((e.get("path") or ""), int(e.get("size") or 0)))
                except (TypeError, ValueError):
                    continue  # non-numeric size: drop the row
            return files, bool(tree.get("truncated"))
        except ForgeError:
            return None

    def get_file(self, repo: str, path: str, ref: str) -> str | None:
        """File content at an exact ref, or None when unfetchable. Refuses
        non-base64/empty responses (the >1MB vacuous-premise law — the model
        must never 'review' or fix an empty file it didn't get)."""
        import base64
        import binascii
        from urllib.parse import quote

        try:
            data = self._call("GET", f"/repos/{repo}/contents/{quote(path, safe='')}?ref={quote(ref, safe='')}")
        except ForgeError:
            return None
        if data.get("encoding") != "base64" or not data.get("content"):
            return None
        try:
            # MECE round-1 (sol F1-003): validate=True rejects lenient garbage
            # that would decode to b"" or partial bytes (binascii.Error too)
            return base64.b64decode(data["content"], validate=True).decode("utf-8")
        except (ValueError, UnicodeDecodeError, binascii.Error):
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
            if not isinstance(p, dict):  # F7-D004: one bad row never kills
                continue  # the page translation (log-loud below)
            head = p.get("head")
            head_sha = head["sha"] if isinstance(head, dict) else ""
            head_repo = ((head.get("repo") or {}) if isinstance(head, dict) else {}).get("full_name")
            user = p.get("user") if isinstance(p.get("user"), dict) else {}
            try:
                number = int(p["number"])
            except (KeyError, TypeError, ValueError):
                number = -1
            if number <= 0 or not head_sha:
                log.warning("%s open-pr row malformed (skipped): %s", self.name, str(p)[:120])
                continue
            prs.append(
                PullRequest(
                    forge=self.name,
                    number=number,
                    repo=repo,
                    title=p.get("title") or "",
                    body=p.get("body") or "",
                    head_sha=head_sha,
                    is_fork=bool(head_repo and head_repo != repo),
                    author=user.get("login", ""),
                    is_bot_author=str(user.get("type", "")).lower() == "bot",
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
            if not isinstance(p, dict):  # F7-D004: row guard
                continue
            head = p.get("head")
            if not isinstance(head, dict):
                log.warning("%s merged-pr row malformed (skipped): %s", self.name, str(p)[:120])
                continue
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
            head_sha = head.get("sha") or ""
            head_repo = ((head.get("repo") or {}) if isinstance(head.get("repo"), dict) else {}).get("full_name")
            user = p.get("user") if isinstance(p.get("user"), dict) else {}
            try:
                number = int(p["number"])
            except (KeyError, TypeError, ValueError):
                number = -1
            if number <= 0 or not head_sha:
                log.warning("%s merged-pr row malformed (skipped): %s", self.name, str(p)[:120])
                continue
            prs.append(
                PullRequest(
                    forge=self.name,
                    number=number,
                    repo=repo,
                    title=p.get("title") or "",
                    body=p.get("body") or "",
                    head_sha=head_sha,
                    is_fork=bool(head_repo and head_repo != repo),
                    author=user.get("login", ""),
                    is_bot_author=str(user.get("type", "")).lower() == "bot",
                    merged_at=merged_raw,
                )
            )
        prs.sort(key=lambda pr: pr.merged_at)  # oldest first: catch-up order
        return prs

    def get_persistent_comment(self, repo: str, number: int) -> tuple[int, str] | None:
        # max_pages=100: our persistent comment must stay findable even on
        # pathological PRs (MECE round-4 M3 F4-D01: the 10-page default made
        # it invisible past 1000 comments → duplicate post). Cost is zero on
        # normal PRs — the loop stops at the first short page.
        for c in self._paginated(
            f"/repos/{repo}/issues/{number}/comments", page_size=100, max_pages=100
        ):
            if not isinstance(c, dict):  # F6-312: row-shape guard
                continue
            cid = c.get("id")
            cbody = c.get("body")
            cuser = c.get("user")
            if not isinstance(cid, int) or cid <= 0 \
                    or not isinstance(cbody, str) \
                    or not isinstance(cuser, dict) \
                    or not isinstance(cuser.get("login"), str):
                # F7-D005: rows need usable identity fields before marker
                # matching — malformed forge content never escapes
                log.warning("%s comment row malformed (skipped): %s", self.name, str(c)[:120])
                continue
            body = cbody
            author = cuser.get("login").lower()
            # Marker substring alone is hijackable by any commenter (review
            # finding 2): require BOTH marker and our own authorship.
            if any(prefix in body for prefix in renderer.LEGACY_MARKER_PREFIXES) and is_own_identity(
                author, self.bot_login
            ):
                return cid, body
        return None

    def create_comment(self, repo: str, number: int, body: str) -> int:
        resp = self._call("POST", f"/repos/{repo}/issues/{number}/comments", {"body": body})
        if not isinstance(resp, dict) or "id" not in resp:
            # F6-313: a 2xx without the comment id is an UNCERTAIN side effect
            # — refuse (ForgeError defers the PR; at-most-once markers win)
            raise ForgeError(f"{self.name} POST comment {repo}#{number}: no id in response")
        return resp["id"]

    def update_comment(self, repo: str, number: int, comment_id: int, body: str) -> None:
        self._call("PATCH", f"/repos/{repo}/issues/comments/{comment_id}", {"body": body})

    def head_check_runs(self, repo: str) -> tuple[str, list[dict]] | None:
        try:
            from urllib.parse import quote

            repo_info = self._call("GET", f"/repos/{repo}")
            if not isinstance(repo_info, dict):
                return None  # F8-003: repo envelope validated
            branch = repo_info.get("default_branch") or "main"
            head = self._call("GET", f"/repos/{repo}/commits/{quote(branch, safe='')}")
            if not isinstance(head, dict):
                return None  # F8-003: commit envelope validated
            sha = head.get("sha") or ""
            if not sha:
                return None
            page = 1
            check_runs: list[dict] = []
            while True:  # MECE round-3 (terra F3-001): failures beyond the
                # default page were invisible — ci_watch could call a red HEAD
                # clean
                if page > _CHECK_RUN_PAGE_CAP:  # MECE round-4 (M3 F4-D08):
                    # bounded pages — a misbehaving server must not spin the
                    # cycle forever
                    import logging as _log
                    _log.getLogger("fl4write.forges").warning(
                        "head_check_runs %s: >%d full pages — capped (rows past "
                        "the cap invisible to this call)", repo, _CHECK_RUN_PAGE_CAP)
                    break
                runs = self._call(
                    "GET",
                    f"/repos/{repo}/commits/{sha}/check-runs?per_page=100&page={page}")
                if not isinstance(runs, dict):
                    # F6-308: non-mapping envelope -> cannot trust the page
                    raise ForgeError(f"{self.name} check-runs shape drift on {repo}")
                _cr = runs.get("check_runs")
                if not isinstance(_cr, list):
                    raise ForgeError(f"{self.name} check_runs not a list on {repo}")
                batch = list(_cr)
                check_runs += batch
                if len(batch) < 100:
                    break
                page += 1
            return sha, check_runs
        except ForgeError:
            return None

    def open_issue(self, repo: str, title: str, body: str) -> int | None:
        try:
            resp = self._call("POST", f"/repos/{repo}/issues", {"title": title, "body": body})
        except ForgeError:
            return None
        # F7-D006: key presence is not a usable identifier — {'number': null}
        # must read as an UNCERTAIN write (None -> caller retries), never a
        # false success that later mints duplicate audit issues
        if not isinstance(resp, dict):
            return None
        n = resp.get("number")
        return n if isinstance(n, int) and n > 0 else None

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
    # MECE round-1 (sol F1-001): Gitea/Forgejo pagination param is `limit`,
    # not `per_page` — the inherited value was silently ignored by the server,
    # capping every Forgejo list at the server default page size.
    page_size_param = "limit"

    def list_open_prs(self, repo: str) -> list[PullRequest]:
        data = self._paginated(f"/repos/{repo}/pulls?state=open", page_size=50)
        prs = []
        for p in data:
            if not isinstance(p, dict):  # F7-D004: row guard
                continue
            head = p.get("head")
            if not isinstance(head, dict):
                log.warning("%s open-pr row malformed (skipped): %s", self.name, str(p)[:120])
                continue
            head_repo = ((head.get("repo") or {}) if isinstance(head.get("repo"), dict) else {}).get("full_name")
            user = p.get("user") if isinstance(p.get("user"), dict) else {}
            try:
                number = int(p["number"])
            except (KeyError, TypeError, ValueError):
                number = -1
            if number <= 0 or not head.get("sha"):
                log.warning("%s open-pr row malformed (skipped): %s", self.name, str(p)[:120])
                continue
            prs.append(
                PullRequest(
                    forge=self.name,
                    number=number,
                    repo=repo,
                    title=p.get("title") or "",
                    body=p.get("body") or "",
                    head_sha=head.get("sha", ""),
                    is_fork=bool(head_repo and head_repo != repo),
                    author=user.get("login", ""),
                    is_bot_author=str(user.get("type", "")).lower() == "bot",
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
            if not isinstance(p, dict):  # F8-004: per-row guard like GitHub
                log.warning("%s merged-pr row malformed (skipped): %s", self.name, str(p)[:120])
                continue
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
            head = p.get("head")
            if not isinstance(head, dict):
                log.warning("%s merged-pr row malformed (skipped): %s", self.name, str(p)[:120])
                continue
            head_repo = ((head.get("repo") or {}) if isinstance(head.get("repo"), dict) else {}).get("full_name")
            user = p.get("user") if isinstance(p.get("user"), dict) else {}
            try:
                number = int(p["number"])
            except (KeyError, TypeError, ValueError):
                number = -1
            if number <= 0 or not head.get("sha"):
                log.warning("%s merged-pr row malformed (skipped): %s", self.name, str(p)[:120])
                continue
            prs.append(
                PullRequest(
                    forge=self.name,
                    number=number,
                    repo=repo,
                    title=p.get("title") or "",
                    body=p.get("body") or "",
                    head_sha=head.get("sha", ""),
                    is_fork=bool(head_repo and head_repo != repo),
                    author=user.get("login", ""),
                    is_bot_author=str(user.get("type", "")).lower() == "bot",
                    merged_at=merged_raw,
                )
            )
        prs.sort(key=lambda pr: pr.merged_at)
        return prs

    def get_persistent_comment(self, repo: str, number: int) -> tuple[int, str] | None:
        # max_pages=100 (MECE round-4 M3 F4-D01): see GitHub variant — a
        # persistent comment past page 10 must stay findable, never double-post
        for c in self._paginated(
            f"/repos/{repo}/issues/{number}/comments", page_size=50, max_pages=100
        ):
            if not isinstance(c, dict):  # F6-312: row-shape guard
                continue
            cid = c.get("id")
            cbody = c.get("body")
            cuser = c.get("user")
            if not isinstance(cid, int) or cid <= 0 \
                    or not isinstance(cbody, str) \
                    or not isinstance(cuser, dict) \
                    or not isinstance(cuser.get("login"), str):
                # F7-D005: rows need usable identity fields before marker
                # matching — malformed forge content never escapes
                log.warning("%s comment row malformed (skipped): %s", self.name, str(c)[:120])
                continue
            body = cbody
            author = cuser.get("login").lower()
            if any(prefix in body for prefix in renderer.LEGACY_MARKER_PREFIXES) and is_own_identity(
                author, self.bot_login
            ):
                return cid, body
        return None

    def create_comment(self, repo: str, number: int, body: str) -> int:
        resp = self._call("POST", f"/repos/{repo}/issues/{number}/comments", {"body": body})
        if not isinstance(resp, dict) or "id" not in resp:
            # F6-313: uncertain write — degrade as ForgeError
            raise ForgeError(f"{self.name} POST comment {repo}#{number}: no id in response")
        return resp["id"]

    def update_comment(self, repo: str, number: int, comment_id: int, body: str) -> None:
        self._call("PATCH", f"/repos/{repo}/issues/comments/{comment_id}", {"body": body})

    def head_check_runs(self, repo: str) -> tuple[str, list[dict]] | None:
        return None  # v1: check-runs (GHA) only; Forgejo commit statuses unsupported

    def list_tree_files(self, repo: str) -> tuple[list[tuple[str, int]], bool] | None:
        """Forgejo variant: Gitea's ?recursive=true TRUNCATES at 1000 entries
        (live-caught on KyaniteLabs/liminal: 862 of a much larger tree) and
        Gitea accepts a branch NAME in the trees path — so walk manually:
        root non-recursive, then per-subtree descent. Complete at any size."""
        try:
            from urllib.parse import quote

            repo_info = self._call("GET", f"/repos/{repo}")
            if not isinstance(repo_info, dict):
                # F7-D003: the repo envelope is an intermediate contract too
                return None
            branch = repo_info.get("default_branch") or "main"
            # MECE round-4 (M3 F4-D07): a default branch containing '/' or
            # other path chars must not corrupt the trees URL — quote the name
            branch_q = quote(branch, safe="")
            out: list[tuple[str, int]] = []
            truncated = False
            fetch_budget = 2000  # F6-311: bounded API walk

            def add_blob(e: dict, prefix: str) -> None:
                nonlocal truncated
                # F7-D003: one coerce-or-drop helper for EVERY blob row (root
                # and subtree) — nonnumeric sizes never ValueError a cycle
                try:
                    out.append((prefix + str(e.get("path") or ""),
                                int(e.get("size") or 0)))
                except (TypeError, ValueError):
                    return
                if len(out) > 500_000:
                    truncated = True

            root = self._call("GET", f"/repos/{repo}/git/trees/{branch_q}")
            if not isinstance(root, dict) or not isinstance(root.get("tree"), list):
                # F6-310: malformed/truncated ROOT response -> truncated,
                # never a silent partial tree
                return out, True
            if root.get("truncated"):
                truncated = True

            # F7-D001: iterative worklist — deep acyclic trees used to hit
            # Python's recursion limit before the old call guard fired.
            # F7-D002: cycle detection is ANCESTRY-only (explicit frames keep
            # every open ancestor on_stack) — a content-addressed subtree
            # shared by two prefixes is legitimate and replays from the cache
            # under every prefix; only an ancestor reference truncates.
            tree_cache: dict[str, list] = {}
            _push_budget = 200_000
            on_stack: set[str] = set()
            stack: list[tuple[str, str, list]] = []  # (sha, prefix, entries)

            def entries_of(sha: str) -> list:
                nonlocal truncated, fetch_budget
                if sha in tree_cache:
                    return tree_cache[sha]
                if fetch_budget <= 0:
                    truncated = True
                    return []
                t = self._call("GET", f"/repos/{repo}/git/trees/{sha}")
                fetch_budget -= 1
                if not isinstance(t, dict) or not isinstance(t.get("tree"), list):
                    truncated = True
                    tree_cache[sha] = []
                    return []
                if t.get("truncated"):
                    truncated = True
                tree_cache[sha] = [e for e in (t.get("tree") or []) if isinstance(e, dict)]
                return tree_cache[sha]

            def push_task(sha: str, prefix: str) -> None:
                nonlocal _push_budget, truncated
                if sha in on_stack:
                    truncated = True  # ancestry cycle
                    return
                if _push_budget <= 0:
                    truncated = True
                    return
                _push_budget -= 1
                stack.append((sha, prefix, entries_of(sha)))

            for e in root.get("tree") or []:
                if not isinstance(e, dict):
                    continue
                if e.get("type") == "blob":
                    add_blob(e, "")
                elif e.get("type") == "tree" and str(e.get("sha") or ""):
                    push_task(str(e["sha"]), str(e.get("path") or "") + "/")
            while stack:
                item = stack.pop()
                if item[0] == "\x00exit":
                    # F8-002: ancestors stay on_stack until ALL descendants
                    # finished (EXIT marker below the children we pushed)
                    on_stack.discard(item[1])
                    continue
                sha, prefix, entries = item
                on_stack.add(sha)
                stack.append(("\x00exit", sha))
                for e in entries:
                    if e.get("type") == "blob":
                        add_blob(e, prefix)
                    elif e.get("type") == "tree" and str(e.get("sha") or ""):
                        push_task(str(e["sha"]), prefix + str(e.get("path") or "") + "/")
            return out, truncated
        except ForgeError:
            return None

    def open_issue(self, repo: str, title: str, body: str) -> int | None:
        try:
            resp = self._call("POST", f"/repos/{repo}/issues", {"title": title, "body": body})
        except ForgeError:
            return None
        # F7-D006: key presence is not a usable identifier — {'number': null}
        # must read as an UNCERTAIN write (None -> caller retries), never a
        # false success that later mints duplicate audit issues
        if not isinstance(resp, dict):
            return None
        n = resp.get("number")
        return n if isinstance(n, int) and n > 0 else None

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


def _is_github_base(api_base: str) -> bool:
    """MECE round-7 (sol F7-D007) + round-8 (terra F8-001): the GitHub route
    carries the App credential — it requires EXACT hostname equality AND
    https. Plaintext http://api.github.com must never receive the token."""
    from urllib.parse import urlsplit

    try:
        parts = urlsplit(api_base)
    except ValueError:
        return False
    return (parts.scheme == "https"
            and parts.hostname == "api.github.com"
            and parts.port in (None, 443))


def adapter_for(binding: ForgeBinding) -> ForgeAdapter:
    """Fail-loud adapter selection — unknown forge names abort the cycle."""
    # The binding's api_base distinguishes github.com vs a Forgejo host.
    # (F7-D007: hostname equality, never substring.)
    if _is_github_base(binding.api_base):
        return GitHubAdapter(binding)
    return ForgejoAdapter(binding)
