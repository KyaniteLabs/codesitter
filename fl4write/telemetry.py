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
    try:
        return int(v or 0)  # "unknown"/None/floats never raise (Sol#5)
    except (TypeError, ValueError):
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


def calibration_snapshot(recent: int = 500) -> dict[str, Any]:
    """L3 (GLM-B4): the feedback loop CONSUMES the stream — per-model parse
    health and per-route severity mix over the last N review events, computed
    from telemetry instead of asserted. Returns {} when the stream is empty."""
    try:
        lines = _path().read_text(encoding="utf-8").strip().splitlines()[-recent * 3:]
    except OSError:
        return {}
    models: dict[str, dict[str, int]] = {}
    for ln in lines:
        try:
            ev = json.loads(ln)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(ev, dict):
            continue  # a stray JSON scalar must not break the snapshot (Sol#5)
        if ev.get("kind") == "model_call":
            m = models.setdefault(str(ev.get("model", "?")), {"calls": 0, "fails": 0, "tokens": 0})
            m["calls"] += 1
            m["fails"] += int(not ev.get("ok", True))
            m["tokens"] += int(ev.get("completion_tokens") or 0) + int(ev.get("prompt_tokens") or 0)
    if not models:
        return {}
    out = {}
    for m, st in models.items():
        out[m] = f"{st['calls'] - st['fails']}/{st['calls']} ok, {st['tokens']} tok"
    return out
