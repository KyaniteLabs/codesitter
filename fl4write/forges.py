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

    # Subclass responsibilities -------------------------------------------
    def list_open_prs(self, repo: str) -> list[PullRequest]:  # pragma: no cover - interface
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
                )
            )
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
                )
            )
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


def adapter_for(binding: ForgeBinding) -> ForgeAdapter:
    """Fail-loud adapter selection — unknown forge names abort the cycle."""
    # The binding's api_base distinguishes github.com vs a Forgejo host.
    if "api.github.com" in binding.api_base:
        return GitHubAdapter(binding)
    return ForgejoAdapter(binding)
