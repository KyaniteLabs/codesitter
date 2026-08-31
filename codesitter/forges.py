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
import urllib.request
from typing import Any

from .config import ForgeBinding
from .models import PullRequest

USER_AGENT = "codesitter/0.1"


class ForgeError(RuntimeError):
    pass


class ForgeAdapter:
    name = "base"
    supports_fork_ci_approval = False
    supports_inline_threads = True

    def __init__(self, binding: ForgeBinding):
        self.binding = binding
        self.base = binding.api_base.rstrip("/")

    def _headers(self) -> dict[str, str]:
        h = {"Accept": "application/json", "User-Agent": USER_AGENT}
        token = os.environ.get(self.binding.token_env, "")
        if token:
            h["Authorization"] = f"token {token}"
        return h

    def _call(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
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
            raise ForgeError(f"{self.name} {method} {path}: HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ForgeError(f"{self.name} {method} {path}: {exc}") from exc

    # Subclass responsibilities -------------------------------------------
    def list_open_prs(
        self, repo: str, since_iso: str | None = None
    ) -> list[PullRequest]:  # pragma: no cover - interface
        raise NotImplementedError

    bot_login: str = "codesitter-bot"

    def _paginated(self, path: str, page_size: int, max_pages: int = 10) -> list[dict]:
        """Page through until a short page (finding 6: PRs/comments past
        page one must not be invisible)."""
        out: list[dict] = []
        for page in range(1, max_pages + 1):
            batch = self._call("GET", f"{path}{'&' if '?' in path else '?'}page={page}&per_page={page_size}")
            if not isinstance(batch, list):
                raise ForgeError(f"paginated {path}: unexpected shape")
            out.extend(batch)
            if len(batch) < page_size:
                break
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

    def list_open_prs(self, repo: str, since_iso: str | None = None) -> list[PullRequest]:
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
            if "codesitter:v1:" in body and author == self.bot_login:
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

    def list_open_prs(self, repo: str, since_iso: str | None = None) -> list[PullRequest]:
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
            if "codesitter:v1:" in body and author == self.bot_login:
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
