"""Per-repo state: the head-SHA predicate, atomic writes, cycle lock.

Design law (ralplan-approved): correctness NEVER depends on the timestamp
watermark — every cycle compares each open PR's head_sha to last_reviewed_sha;
re-review fires on divergence, so missed events self-heal next cycle. The
watermark is a fetch optimization only. Writes are atomic (tmp+rename,
kill-mid-write safe). A cycle lock prevents overlapping runs from double-posting.
Corrupt state fails closed to a bounded reconcile (re-review open PRs whose
SHA is unknown), never re-review-everything, never silent skip.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

STATE_VERSION = 1


class CycleLockHeld(RuntimeError):
    """Another cycle is running — the caller must skip, not queue."""


class CycleLock:
    """Hard-locality lock via O_EXCL. Stale locks (pid dead) are broken."""

    def __init__(self, path: Path):
        self.path = path
        self._held = False

    def __enter__(self) -> "CycleLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            self._held = True
            return self
        except FileExistsError:
            try:
                pid = int(self.path.read_text().strip() or "0")
                os.kill(pid, 0)
                raise CycleLockHeld(f"cycle lock held by pid {pid}") from None
            except (ValueError, ProcessLookupError, PermissionError):
                # Stale or unreadable lock: break it and retake once.
                self.path.unlink(missing_ok=True)
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                self._held = True
                return self

    def __exit__(self, *exc: object) -> None:
        if self._held:
            self.path.unlink(missing_ok=True)


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    """Kill-mid-write safe: readers see the old or the new state, never torn."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".state-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=1)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def load_state(path: Path) -> dict[str, Any]:
    """Load or reconcile. Corrupt/unknown-version state -> bounded reconcile:
    keep the repo identity, forget per-PR memory (open PRs with unknown
    last_reviewed_sha re-review once — that is the bounded cost)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("version") == STATE_VERSION:
            return data
    except FileNotFoundError:
        pass
    except (json.JSONDecodeError, OSError):
        pass
    return {"version": STATE_VERSION, "prs": {}, "watermark": None}


def save_state(path: Path, state: dict[str, Any]) -> None:
    _atomic_write(path, state)


def needs_review(state: dict[str, Any], pr_number: int, head_sha: str) -> bool:
    """The poll-invariant predicate: re-review iff SHA diverges or unknown."""
    return state["prs"].get(str(pr_number), {}).get("last_reviewed_sha") != head_sha


def mark_reviewed(state: dict[str, Any], pr_number: int, head_sha: str, outcome: str) -> None:
    state["prs"][str(pr_number)] = {
        "last_reviewed_sha": head_sha,
        "last_outcome": outcome,
    }


def prune_closed(state: dict[str, Any], open_numbers: set[int], grace_keep: int = 50) -> None:
    """Prune closed PRs with a grace window (keep the most recent N records)."""
    keep = sorted(
        ((int(k), v) for k, v in state["prs"].items() if int(k) in open_numbers),
    )[-grace_keep:]
    state["prs"] = {str(n): v for n, v in keep}
