"""Plus-ultra telemetry — the append-only event stream future improvement
rounds read (CEO order 2026-09-02: "plus ultra the telemetry for future
runs"). One JSONL line per event; never raises, never blocks, never truncates
the truth. The calibration loop (fl4write #5) consumes this instead of
asking models to re-derive history.

Event kinds:
  model_call   — route, latency, tokens (prompt/completion), finish_reason,
                 parse_ok. The usage field was previously DISCARDED — the
                 single richest calibration signal we had and threw away.
  gatekeeper   — kept/dropped/demoted counts + demotion identities.
  review       — lane (pr/postmerge/retro/omni), findings by severity
                 BEFORE and AFTER gates, posted_severity final, route mix.
  fix_attempt  — status, reason head, latency, lane.
  verify_tests — cmd, files, head, outcome.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

_STREAM: Path | None = None


def _path() -> Path:
    global _STREAM
    if _STREAM is None:
        _STREAM = Path(os.environ.get(
            "FL4WRITE_TELEMETRY",
            Path.home() / ".fl4write" / "telemetry.jsonl",
        ))
        try:
            _STREAM.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
    return _STREAM


def emit(kind: str, **fields: Any) -> None:
    """Append one event. Telemetry must never take the product down: every
    failure is swallowed (a lost metric line beats a lost review cycle)."""
    try:
        event = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                 "kind": kind, **fields}
        with _path().open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, default=str) + "\n")
    except Exception:  # noqa: BLE001 — telemetry is best-effort by contract
        pass


def route_stats() -> dict[str, dict[str, float]]:
    """Aggregate the current process's model-call stats (per route/model):
    calls, ok, parse_failures, total latency, tokens. Surfaced per cycle."""
    return {k: dict(v) for k, v in _ROUTE_STATS.items()}


_ROUTE_STATS: dict[str, dict[str, float]] = {}


def _safe_int(v: object) -> int:
    # F12-B011 (reopened F2-108): provider numbers can be non-finite
    # (1e309 parses to inf and int(inf) raises OverflowError) — a hostile or
    # corrupt event used to crash calibration AFTER a completed cycle
    try:
        if isinstance(v, float) and (v != v or v in (float("inf"), float("-inf"))):
            return 0
        n = int(v or 0)  # "unknown"/None/floats never raise (Sol#5)
        return n if n > 0 else 0  # negative token counts are corrupt
    except (TypeError, ValueError, OverflowError):
        return 0


def record_route(model: str, ok: bool, latency_s: float, parse_ok: bool,
                 prompt_tokens: int = 0, completion_tokens: int = 0) -> None:
    try:
        key = str(model)
        st = _ROUTE_STATS.setdefault(key, {
            "calls": 0, "ok": 0, "parse_fail": 0, "latency_s": 0.0,
            "prompt_tokens": 0, "completion_tokens": 0,
        })
        latency_s = float(latency_s or 0.0)
        st["calls"] += 1
        st["ok"] += int(bool(ok))
        st["parse_fail"] += int(not parse_ok)
        st["latency_s"] += latency_s
        st["prompt_tokens"] += _safe_int(prompt_tokens)
        st["completion_tokens"] += _safe_int(completion_tokens)
    except Exception:  # telemetry never raises (Sol#5)
        pass


def _read_tail(path, max_bytes: int = 8 * 1024 * 1024) -> str:
    """F8-012: bounded read of an append-only stream tail — never loads the
    whole (unbounded) file; the first partial line is discarded."""
    try:
        size = path.stat().st_size
    except OSError:
        return ""
    if size <= max_bytes:
        return path.read_text(encoding="utf-8", errors="replace")
    with path.open("rb") as fh:
        fh.seek(size - max_bytes)
        tail = fh.read()
    text = tail.decode("utf-8", errors="replace")
    nl = text.find("\n")
    return text[nl + 1:] if nl != -1 else text


def calibration_snapshot(recent: int = 500) -> dict[str, Any]:
    """L3 (GLM-B4): the feedback loop CONSUMES the stream — per-model call
    health over the last N model_call events (MECE round-4 F4-4: the
    docstring promised a per-route severity mix this aggregation never
    computed — body now matches the promise). Returns {} when empty."""
    try:
        # MECE round-6 (luna F6-002): the stream may hold corrupt bytes (kill
        # mid-append) — telemetry never raises by contract, and this call runs
        # AFTER the cycle in the CLI; a UnicodeDecodeError here crashed the
        # process on the way out.
        # MECE round-8 (sol F8-012): read a BOUNDED tail (the stream is
        # append-only and never truncated) instead of loading it whole.
        chunk = _read_tail(_path(), max_bytes=8 * 1024 * 1024)
        # F11-B006 (round 11, luna DOM-B, reopened F8-011): the BYTE-bounded
        # tail is the bound — slicing [-recent*12:] by LINES discarded
        # qualifying model_call events whenever noise events outnumbered the
        # slack, silently erasing failures from calibration
        lines = chunk.splitlines()
    except OSError:
        return {}
    models: dict[str, dict[str, int]] = {}
    # F8-011: the contract is the last N model-CALL events — slicing the
    # last 3N raw lines erased calibration when reviews outnumbered calls.
    # Walk backward from the tail until exactly N model_call events are seen.
    collected = 0
    order: list[str] = []
    for ln in reversed(lines):
        try:
            ev = json.loads(ln)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(ev, dict):
            continue  # a stray JSON scalar must not break the snapshot (Sol#5)
        if ev.get("kind") == "model_call" and "ok" in ev:
            # F9-001: only OUTCOME events count — pre-validation events (no
            # ok field) must never default to healthy
            order.append(ln)
            collected += 1
            if collected >= recent:
                break
    for ln in reversed(order):
        try:
            ev = json.loads(ln)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(ev, dict):
            continue  # a stray JSON scalar must not break the snapshot (Sol#5)
        if ev.get("kind") == "model_call":
            # F11-B007: ok must be a REAL boolean — the string "false" is
            # truthy and used to count as a success; malformed events are
            # quarantined (neither ok nor fail) instead of corrupting ratios
            _ok = ev.get("ok")
            if not isinstance(_ok, bool):
                continue
            m = models.setdefault(str(ev.get("model", "?")), {"calls": 0, "fails": 0, "tokens": 0})
            m["calls"] += 1
            m["fails"] += int(not _ok)
            # MECE round-2 (M3 DOM-B): provider usage fields can arrive as
            # strings ("unknown") — never let the snapshot crash on them
            m["tokens"] += (_safe_int(ev.get("completion_tokens"))
                            + _safe_int(ev.get("prompt_tokens")))
    if not models:
        return {}
    out = {}
    for m, st in models.items():
        out[m] = f"{st['calls'] - st['fails']}/{st['calls']} ok, {st['tokens']} tok"
    return out
