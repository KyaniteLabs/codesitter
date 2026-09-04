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
    """Locality lock via kernel flock (MECE round-7, terra F7-001).

    The old O_EXCL + pid/age stale-breaking protocol had a fundamental
    compare-then-unlink race: two stale-breakers could interleave so one
    unlinked the OTHER's freshly-created LIVE lock and both cycles ran.
    flock has no stale-breaking at all: the kernel releases the lock when the
    holding process dies (no pid-reuse, no age math, no unlink). The lock
    FILE persists (harmless) and carries a diagnostic token.

    Semantics kept: a second concurrent holder raises CycleLockHeld (callers
    skip, never queue)."""

    def __init__(self, path: Path):
        self.path = path
        self._fd: int | None = None
        self._held = False
        self._token = ""

    def _acquire(self) -> bool:
        import fcntl

        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return False
        self._token = f"{os.getpid()} {int(time.time())} {os.urandom(6).hex()}"
        try:
            os.ftruncate(fd, 0)
            os.write(fd, self._token.encode())
        except OSError:  # diagnostics only — never fail the lock
            pass
        self._fd = fd
        return True

    def __enter__(self) -> "CycleLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self._acquire():
            return self
        raise CycleLockHeld(f"cycle lock held: {self.path}")

    def __exit__(self, *exc: object) -> None:
        if self._fd is not None:
            try:
                import fcntl
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            except OSError:
                pass
            os.close(self._fd)
            self._fd = None
            self._held = False


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
        elif (isinstance(data.get("version"), int)
              and not isinstance(data.get("version"), bool)
              and data.get("version") == STATE_VERSION):
            # MECE round-6 (luna-max F6-C019): True == 1 — boolean versions
            # must not pass the int check (bounded reconcile instead)
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
                # F11-C009 (reopened F5-204): record VALUES are consumed by
                # raw int() — normalize fix_depth and the per-PR failure maps
                _prs = data["prs"]
                _dirty = False
                for _rec in _prs.values():
                    if not isinstance(_rec, dict):
                        continue
                    _fd = _rec.get("fix_depth")
                    if _fd is not None and (isinstance(_fd, bool)
                                            or not isinstance(_fd, int)):
                        log.warning("state %s: non-int fix_depth dropped", path)
                        _rec.pop("fix_depth", None)
                        _dirty = True
                    _mf = _rec.get("model_failures")
                    if _mf is not None:
                        if not isinstance(_mf, dict):
                            log.warning("state %s: non-dict PR model_failures dropped", path)
                            _rec.pop("model_failures", None)
                            _dirty = True
                        else:
                            _kept = {k: x for k, x in _mf.items()
                                     if isinstance(x, int) and not isinstance(x, bool)}
                            if len(_kept) != len(_mf):
                                log.warning("state %s: dropping non-int PR model_failures", path)
                                _rec["model_failures"] = _kept
                                _dirty = True
                if _dirty:
                    data = dict(data)
                    data["prs"] = _prs
                return _normalize_aux(data)
            log.warning("state %s version ok but shape wrong; bounded reconcile", path)
        else:
            log.warning("state %s has unknown version %r; bounded reconcile", path, data.get("version"))
    except FileNotFoundError:
        pass
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        # MECE round-5 (sol F5-004): invalid UTF-8 escaped load_state as an
        # uncaught UnicodeDecodeError — same corrupt-state reconcile as bad JSON
        log.warning("state %s corrupt (%s); bounded reconcile — per-PR memory lost", path, exc)
    except OSError as exc:
        raise StateIOError(f"state {path} unreadable ({exc}) — aborting cycle, will retry") from exc
    return json.loads(json.dumps(_FRESH_STATE))


def _valid_iso(value: str) -> bool:
    """MECE round-6 (luna-max F6-C011): ISO-8601-ish UTC stamp check for the
    persisted watermarks/cursors. Accepts 'YYYY-...T..Z' and '+00:00' forms
    the engine writes; rejects arbitrary strings like '0000'."""
    import datetime as _dt

    v = value.strip()
    if not v:
        return False
    try:
        _dt.datetime.fromisoformat(v.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def _normalize_aux(data: dict[str, Any]) -> dict[str, Any]:
    """MECE round-5 (sol F5-004): lane belts/counters read back through raw
    int()/comparison operations — a hand-edited or partially-written value of
    the wrong type must degrade to a safe default, never TypeError a cycle.
    Only the fields with DIRECT type-dependent readers are normalized; the
    rest ride as-is (a future reader normalizes at its own boundary)."""
    out = dict(data)
    for key in ("merged_since", "retro_cursor"):
        v = out.get(key)
        if v is None:
            continue
        if not isinstance(v, str) or not _valid_iso(v):
            # MECE round-6 (luna-max F6-C011): an arbitrary string watermark
            # ("0000") made the retro sweep skip current PRs and mark the
            # window COMPLETE — validate ISO semantics, not just type
            log.warning("state %s: invalid %s %r dropped (bounded reconcile)", key, key, v)
            out.pop(key, None)
    omni = out.get("omni_findings")
    if omni is not None:
        if not isinstance(omni, list):
            log.warning("state omni_findings: non-list dropped (bounded reconcile)")
            out.pop("omni_findings", None)
        else:
            bad = [r for r in omni if not (isinstance(r, dict)
                                           and isinstance(r.get("path"), str)
                                           and isinstance(r.get("rule"), str)
                                           and isinstance(r.get("sev"), str)
                                           and isinstance(r.get("msg"), str)
                                           and isinstance(r.get("id"), int)
                                           and not isinstance(r.get("id"), bool)
                                           and isinstance(r.get("line"), int))]
            if bad:
                log.warning("state omni_findings: dropping %d malformed rows (bounded reconcile)",
                            len(bad))
                out["omni_findings"] = [r for r in omni if r not in bad]
    # MECE round-7 (terra F7-002): omni cursors/counters drive raw
    # int()/comparison operations — wrong types used to TypeError/ValueError
    # the cycle outside its handled exceptions. F11-C008 (reopened F7-C002):
    # identity/progress fields are ATOMIC with the sweep — dropping only the
    # bad field used to leave omni_complete=True next to a lost cursor/head
    # and the engine stayed terminal without ever re-probing
    _omni_core_bad = False
    for key in ("omni_cursor", "omni_head", "omni_fp"):
        v = out.get(key)
        if v is not None and not isinstance(v, str):
            log.warning("state omni core %s: non-string %r — sweep state reset", key, v)
            _omni_core_bad = True
    for key in ("omni_scanned_total", "omni_next_id", "omni_total"):
        v = out.get(key)
        if v is not None and (isinstance(v, bool) or not isinstance(v, int)):
            log.warning("state omni core %s: non-int %r — sweep state reset", key, v)
            _omni_core_bad = True
    if _omni_core_bad:
        for key in ("omni_complete", "omni_published", "omni_cursor", "omni_head",
                    "omni_fp", "omni_findings", "omni_next_id", "omni_total",
                    "omni_scanned_total", "omni_unscannable", "omni_unfetchable",
                    "omni_file_fails"):
            out.pop(key, None)
        # omni_issue is deliberately kept: the next audit reuses the issue

    # F11-C009 (reopened F5-204): numeric VALUES inside failure maps are
    # consumed by raw int() — normalize the map values, not just containers
    for key in ("model_failures", "omni_file_fails"):
        v = out.get(key)
        if v is None:
            continue
        if not isinstance(v, dict):
            log.warning("state %s: non-dict %r dropped (bounded reconcile)", key, v)
            out.pop(key, None)
        else:
            kept = {k: int(x) for k, x in v.items()
                    if isinstance(x, int) and not isinstance(x, bool)}
            if len(kept) != len(v):
                log.warning("state %s: dropping non-int values (bounded reconcile)", key)
            out[key] = kept
    for key in ("omni_scanned_total", "omni_next_id", "omni_total"):
        v = out.get(key)
        if v is None:
            continue
        if isinstance(v, bool) or not isinstance(v, int):
            log.warning("state %s: non-int %r dropped (bounded reconcile)", key, v)
            out.pop(key, None)
    for key in ("omni_complete", "omni_published", "retro_complete", "omni_aborted"):
        v = out.get(key)
        if v is not None and not isinstance(v, bool):
            # a truthy STRING ("false") falsely terminalized lanes
            log.warning("state %s: non-bool %r dropped (bounded reconcile)", key, v)
            out.pop(key, None)
    open_ids = out.get("open_ids")
    if open_ids is not None:
        if not isinstance(open_ids, list):
            log.warning("state open_ids: non-list dropped (bounded reconcile)")
            out.pop("open_ids", None)
        else:
            out["open_ids"] = [int(x) for x in open_ids
                               if isinstance(x, int) and not isinstance(x, bool)]
    # F12-C002: quarantine/unscannable ledgers are consumed by .append() —
    # a persisted non-list used to survive unless another core field was bad
    for key in ("omni_unfetchable", "omni_unscannable"):
        v = out.get(key)
        if v is None:
            continue
        if not isinstance(v, list):
            log.warning("state %s: non-list %r dropped (bounded reconcile)", key, v)
            out.pop(key, None)
        else:
            out[key] = [x for x in v if isinstance(x, str)][:2000]
    # F12-C003: dynamic ci_acted:<head> markers are truthiness-READ — a
    # persisted string "false" used to suppress red-head remediation forever
    for k in [k for k in out if k.startswith("ci_acted:")]:
        if not isinstance(out[k], bool):
            log.warning("state %s: non-bool dropped (bounded reconcile)", k)
            out.pop(k, None)
    for key in ("retro_seen", "retro_parked", "pm_shadow_seen", "retro_shadow_seen",
                "model_failures", "omni_file_fails"):
        v = out.get(key)
        if v is not None and not isinstance(v, dict):
            log.warning("state %s: non-dict %r dropped (bounded reconcile)", key, v)
            out.pop(key, None)
    for key in ("retro_defer:",):  # prefix keys: retro_defer:<num>:<sha> -> int
        for k in [k for k in out if k.startswith(key)]:
            v = out[k]
            try:
                out[k] = int(v)
            except (TypeError, ValueError):
                log.warning("state %s: non-int %r dropped (bounded reconcile)", k, v)
                out.pop(k, None)
    return out


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
    otherwise grow without bound. MECE round-5 (sol F5-010): the SAME bounded-
    growth law applies to top-level lane belts — per-SHA model-failure keys
    whose PR is gone, expired retro parks, and ci_acted markers (insertion-
    bounded) were never collected."""
    state["prs"] = {
        n: rec
        for n, rec in state["prs"].items()
        if int(n) in open_numbers or "fix_depth" in rec or "model_failures" in rec
    }
    # MECE round-6 (luna-max F6-C015): fix-depth/model-failure records of
    # CLOSED PRs are kept for the depth rails while open, but a closed record
    # can never become open again — bound the retained history (insertion
    # order: the newest 2000 survive)
    closed_kept = [n for n, rec in state["prs"].items()
                   if int(n) not in open_numbers]
    if len(closed_kept) > 2000:
        for n in closed_kept[: len(closed_kept) - 2000]:
            state["prs"].pop(n, None)
    mf = state.get("model_failures")
    if isinstance(mf, dict):  # keys "{pr}:{sha10}"
        state["model_failures"] = {
            k: v for k, v in mf.items()
            if isinstance(k, str) and k.split(":", 1)[0].isdigit()
            and int(k.split(":", 1)[0]) in open_numbers
        }
    parked = state.get("retro_parked")
    if isinstance(parked, dict):
        import time as _t
        now_i = int(_t.time())
        state["retro_parked"] = {
            k: v for k, v in parked.items()
            if isinstance(v, int) and v > now_i  # expired parks are garbage
        }
    ci_keys = [k for k in state if k.startswith("ci_acted:")]
    if len(ci_keys) > 100:  # insertion-ordered: drop the oldest markers
        for k in ci_keys[: len(ci_keys) - 100]:
            state.pop(k, None)


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
