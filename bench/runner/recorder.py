"""JSONL recorder for bench runs. Each record is one JSON line."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RESULTS_ROOT = Path(__file__).resolve().parents[1] / "results"


class Recorder:
    """Writes run events to a per-run JSONL file. Thread-safe per instance."""

    def __init__(self, fixture_id: str, runs_root: Path | None = None):
        self.fixture_id = fixture_id
        root = runs_root if runs_root is not None else RESULTS_ROOT / "runs"
        root.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.path = root / f"{fixture_id}__{ts}.jsonl"
        self._fh = self.path.open("w")
        self._t0 = time.time()
        # Aggregate per-run counters reachable via `summary()`.
        self.steps: list[dict] = []
        self.result: dict[str, Any] | None = None
        self.assert_ok: bool | None = None
        self.assert_msg: str | None = None

    def write(self, record: dict) -> None:
        record = {**record, "ts_rel_ms": int((time.time() - self._t0) * 1000)}
        self._fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._fh.flush()

    def on_step(self, record: dict) -> None:
        self.steps.append(record)
        self.write(record)

    def on_finish(self, record: dict) -> None:
        self.result = record
        self.write(record)

    def write_assert(self, ok: bool, msg: str, details: dict | None = None) -> None:
        self.assert_ok = ok
        self.assert_msg = msg
        self.write({
            "t": "assert", "ok": ok, "msg": msg,
            "details": details or {},
        })

    def close(self) -> None:
        if not self._fh.closed:
            self._fh.close()

    def summary(self) -> dict:
        return {
            "fixture_id": self.fixture_id,
            "log_path": str(self.path),
            "steps_recorded": len(self.steps),
            "result": self.result,
            "assert_ok": self.assert_ok,
            "assert_msg": self.assert_msg,
        }
