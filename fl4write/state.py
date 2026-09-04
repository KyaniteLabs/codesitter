"""Per-repo state: the head-SHA predicate, atomic writes, cycle lock.

Design law (ralplan-approved): correctness NEVER depends on the timestamp
watermark — every cycle compares each open PR's head_sha to last_reviewed_sha;
re-review fires on divergence, so missed events self-heal next cycle. Writes
are atomic (tmp+rename, kill-mid-write safe). A cycle lock prevents overlapping
runs from double-posting.

Audit 2026-09-01 hardening:
- Lock files carry pid+epoch and are age-broken after LOCK_MAX_AGE — a pid-0
  file (kill between open and write) or a reused pid can no longer wedge a
  repo forever (previously invisible: the skip printed a normal cycle line).
- mark_reviewed MERGES into the PR record — it used to replace it, wiping
  fix_depth so the per-PR fix cap never persisted across pushes.
- load_state logs what it dropped; transient OSError aborts the cycle instead
  of silently discarding all memory (reconcile is for corruption, not flaky IO).
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any

log = logging.getLogger("fl4write.state")

STATE_VERSION = 1
LOCK_MAX_AGE = 2 * 60 * 60  # hours-scale; no legitimate cycle holds a lock this long


class CycleLockHeld(RuntimeError):
    """Another cycle is running — the caller must skip, not queue."""


class StateIOError(RuntimeError):
    """Transient failure reading state — abort the cycle, retry next run."""


class CycleLock:
    """Locality lock via O_EXCL. Stale locks (pid dead OR older than
    LOCK_MAX_AGE) are broken; an empty or garbage lock file is always stale."""

    def __init__(self, path: Path):
        self.path = path
        self._held = False

    def _acquire(self) -> bool:
        fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, f"{os.getpid()} {int(time.time())}".encode())
        os.close(fd)
        return True

    def __enter__(self) -> "CycleLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._held = self._acquire()
            return self
        except FileExistsError:
            pass
        for _ in range(2):
            try:
                raw = self.path.read_text().strip()
            except FileNotFoundError:
                # holder exited between our failed open and this read — retry
                try:
                    self._held = self._acquire()
                    return self
                except FileExistsError:
                    continue
            pid, _, epoch_s = raw.partition(" ")
            try:
                pid_i, epoch = int(pid or "0"), int(float(epoch_s or 0))
            except ValueError:
                pid_i, epoch = 0, 0
            # pid 0 / garbage, or lock older than the max age: stale, break it.
            stale_by_age = epoch > 0 and (time.time() - epoch) > LOCK_MAX_AGE
            if pid_i > 0 and not stale_by_age:
                try:
                    os.kill(pid_i, 0)
                    alive = True
                except ProcessLookupError:
                    alive = False  # dead holder: stale
                except PermissionError:
                    alive = True  # foreign pid: treat as held (never break a live lock)
                if alive:
                    raise CycleLockHeld(f"cycle lock held by pid {pid_i}") from None
            # MECE round-4 (luna F4-001): re-validate BEFORE the unlink — a
            # fresh holder may have taken the lock since our read; unlink must
            # never remove a LIVE lock
            try:
                fresh = self.path.read_text().strip()
            except FileNotFoundError:
                fresh = raw
            if fresh != raw:
                continue  # content changed under us — re-read the new holder
            self.path.unlink(missing_ok=True)
            try:
                self._held = self._acquire()
                return self
            except FileExistsError:
                continue  # lost the retake race — re-read the new holder
        raise CycleLockHeld("lost lock retake race")


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


_FRESH_STATE = {"version": STATE_VERSION, "prs": {}}


def load_state(path: Path) -> dict[str, Any]:
    """Load or reconcile. Corrupt/unknown-version state -> bounded reconcile:
    keep the repo identity, forget per-PR memory (open PRs with unknown
    last_reviewed_sha re-review once — that is the bounded cost). Transient
    I/O errors ABORT the cycle (StateIOError) — discarding memory on a flaky
    read is silent data loss."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            # valid JSON of the wrong shape (list/str/int — hand-edited or a
            # foreign file at the path): same bounded reconcile, never an
            # AttributeError crash mid-cycle (UltraQA round 1, ADV-07)
            log.warning("state %s is %s, not an object; bounded reconcile", path, type(data).__name__)
        elif data.get("version") == STATE_VERSION:
            prs = data.get("prs")
            if isinstance(prs, dict):
                # MECE round-2 (terra F2-003): nested PR records must be sane —
                # a null record crashed needs_review; a non-numeric key crashed
                # prune_closed. Drop malformed entries (bounded reconcile).
                bad = [k for k, v in prs.items()
                       if not isinstance(v, dict)
                       or not (str(k).isdigit() or k.isdigit())]
                if bad:
                    log.warning("state %s: dropping %d malformed PR records (bounded reconcile)",
                                path, len(bad))
                    data = dict(data)
                    data["prs"] = {k: v for k, v in prs.items() if k not in bad}
                return data
            log.warning("state %s version ok but shape wrong; bounded reconcile", path)
        else:
            log.warning("state %s has unknown version %r; bounded reconcile", path, data.get("version"))
    except FileNotFoundError:
        pass
    except json.JSONDecodeError as exc:
        log.warning("state %s corrupt (%s); bounded reconcile — per-PR memory lost", path, exc)
    except OSError as exc:
        raise StateIOError(f"state {path} unreadable ({exc}) — aborting cycle, will retry") from exc
    return json.loads(json.dumps(_FRESH_STATE))


def save_state(path: Path, state: dict[str, Any]) -> None:
    _atomic_write(path, state)


def needs_review(state: dict[str, Any], pr_number: int, head_sha: str) -> bool:
    """The poll-invariant predicate: re-review iff SHA diverges, is unknown,
    or the only prior outcome was SHADOW (shadow reviews never count as
    reviewed — the dogfood cutover must post, not no-op)."""
    rec = state["prs"].get(str(pr_number), {})
    if rec.get("last_reviewed_sha") != head_sha:
        return True
    return str(rec.get("last_outcome", "")).startswith("shadow")


def mark_reviewed(state: dict[str, Any], pr_number: int, head_sha: str, outcome: str) -> None:
    """MERGE into the record — replacing it wiped fix_depth and reset the
    fix-loop cap on every push (audit finding A3)."""
    rec = state["prs"].setdefault(str(pr_number), {})
    rec["last_reviewed_sha"] = head_sha
    rec["last_outcome"] = outcome


def prune_closed(state: dict[str, Any], open_numbers: set[int]) -> None:
    """Drop records for PRs neither open nor carrying fix state — state files
    otherwise grow without bound."""
    state["prs"] = {
        n: rec
        for n, rec in state["prs"].items()
        if int(n) in open_numbers or "fix_depth" in rec or "model_failures" in rec
    }


# Post-merge sweep watermark. Unlike the open-PR path (where correctness NEVER
# depends on a timestamp — the head-SHA predicate self-heals), discovery of
# MERGED PRs needs a watermark: they are invisible to list_open_prs. At-most-
# once posting stays protected by the head-SHA predicate + persistent-comment
# marker even if the watermark rewinds.
MERGED_SINCE_KEY = "merged_since"


def merged_watermark(state: dict[str, Any]) -> str | None:
    return state.get(MERGED_SINCE_KEY)


def advance_merged_watermark(state: dict[str, Any], iso: str) -> None:
    """Only ever advances — a rewind would re-list already-swept merges."""
    current = merged_watermark(state)
    if current is None or iso > current:
        state[MERGED_SINCE_KEY] = iso
