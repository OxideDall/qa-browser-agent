"""Load capture JSONL files into structured Trace objects.

A capture JSONL has shape (one record per line):

    {"t": "start", "mode": "llm"|"tagged", "run_id": ..., ...}
    {"t": "step",  "step": N, "action"|"verb": ..., "args": [...],
                   "result": ..., "page_url": ...,
                   "pre_signature": {url_template, struct_hash, content_hash, ...},
                   "target_role": ..., ...}
    {"t": "result", "status": "PASS"|"FAIL"|"ERROR", ...}

Loader handles both LLM-path and tagged-path formats — they have
slightly different step keys (`action` vs `verb`, etc.) — and
normalises into a uniform `TraceStep` dataclass so the rest of the
miner doesn't care which mode produced the trace.

Captures with `result.status != "PASS"` are dropped: a macro mined
from failing runs is a macro that doesn't work. `--include-failed`
on the CLI overrides that for debugging.

Captures from `tagged` mode are also dropped by default — replaying
existing tagged scripts as macros is circular. `--include-tagged`
overrides.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator


@dataclass
class TraceStep:
    """One normalised step record from a capture file."""
    step_no: int
    verb: str                          # the action verb ("click"/"type"/...)
    args: list[str]
    target_role: str | None
    target_name: str | None            # accessible name of click/type target (if recorded)
    page_url: str | None
    pre_signature: dict | None
    result: str | None
    status: str | None                 # PASS/FAIL/ERROR for tagged steps
    raw: dict                          # original record for debugging


@dataclass
class Trace:
    """Full per-run trace: header + steps + final."""
    run_id: str
    mode: str                          # "llm" | "tagged"
    task: str
    final_status: str                  # PASS / FAIL / ERROR
    confidence: float | None
    steps: list[TraceStep] = field(default_factory=list)
    path: Path | None = None


def _normalise_step(rec: dict) -> TraceStep:
    """Coerce one step record into TraceStep, tolerating both modes."""
    verb = rec.get("action") or rec.get("verb") or ""
    args = list(rec.get("args") or [])
    return TraceStep(
        step_no=int(rec.get("step", 0)),
        verb=str(verb),
        args=[str(a) for a in args],
        target_role=rec.get("target_role"),
        target_name=rec.get("target_name"),
        page_url=rec.get("page_url"),
        pre_signature=rec.get("pre_signature"),
        result=rec.get("result"),
        status=rec.get("status"),
        raw=rec,
    )


def _load_one(path: Path) -> Trace | None:
    """Parse one JSONL file. Returns None if the file is malformed
    enough that we can't make sense of it (no start, no result)."""
    start: dict | None = None
    result: dict | None = None
    steps: list[TraceStep] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                t = rec.get("t")
                if t == "start":
                    start = rec
                elif t == "step":
                    steps.append(_normalise_step(rec))
                elif t == "result":
                    result = rec
    except OSError:
        return None
    if start is None or result is None:
        return None
    return Trace(
        run_id=str(start.get("run_id") or path.stem),
        mode=str(start.get("mode", "llm")),
        task=str(start.get("task", "")),
        final_status=str(result.get("status", "ERROR")),
        confidence=(
            float(result["confidence"])
            if result.get("confidence") is not None else None
        ),
        steps=steps,
        path=path,
    )


def iter_capture_files(captures_dir: Path) -> Iterator[Path]:
    """Yield all .jsonl files under captures_dir, recursively. Sorted
    by mtime (oldest first) — gives stable miner output run-to-run."""
    if not captures_dir.is_dir():
        return iter([])
    files = [p for p in captures_dir.rglob("*.jsonl") if p.is_file()]
    files.sort(key=lambda p: p.stat().st_mtime)
    return iter(files)


def load_captures(
    captures_dir: Path,
    *,
    include_failed: bool = False,
    include_tagged: bool = False,
    split_by_page: bool = True,
    min_segment_len: int = 2,
) -> list[Trace]:
    """Load + filter capture traces.

    Default behaviour:
    - drops failed runs (a macro mined from FAIL is a macro that fails)
    - drops tagged-mode runs (replaying existing tagged scripts is
      circular)
    - splits each remaining trace into per-URL-template sub-traces
      so mining produces within-page N-grams that the runtime
      precondition gate can actually fire on. Set
      `split_by_page=False` to mine whole-trace sequences instead
      (legacy behaviour; produces cross-page malformed candidates
      that the precondition gate rejects at runtime).
    - drops sub-traces shorter than `min_segment_len` (default 2)
      since 1-step segments only produce trivial 1-grams.

    Either of `include_failed` / `include_tagged` opts the
    corresponding category back in.
    """
    out: list[Trace] = []
    for path in iter_capture_files(captures_dir):
        trace = _load_one(path)
        if trace is None:
            continue
        if not include_failed and trace.final_status != "PASS":
            continue
        if not include_tagged and trace.mode == "tagged":
            continue
        out.append(trace)

    if split_by_page:
        # Lazy import: boundaries imports back from this module's
        # TraceStep type, the lazy form keeps cycles avoidable.
        from .boundaries import segment_traces
        out = segment_traces(out, min_segment_len=min_segment_len)
    return out
