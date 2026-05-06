"""Pure-function API for capture-file management.

CLI in `__main__.py` is a thin wrapper around these — same calls,
different surface. Separated so other code (bench tooling, future
auto-rotation hook) can reuse without subprocess'ing the CLI.

run_id symmetry: every capture JSONL carries a `run_id` in its first
record (Phase 0 contract); the per-run screenshots dir is named the
same as the JSONL stem. We use that stem to find and delete the
screenshots dir alongside the capture during GC.
"""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CaptureMeta:
    """One capture file + its associated screenshots dir."""
    run_id: str
    mode: str                          # "llm" | "tagged"
    path: Path
    screenshots_dir: Path | None
    mtime: float
    size_bytes: int                    # capture JSONL only
    screenshots_bytes: int             # 0 if dir missing
    final_status: str | None           # PASS | FAIL | ERROR | None (malformed)
    n_steps: int

    @property
    def total_bytes(self) -> int:
        return self.size_bytes + self.screenshots_bytes


@dataclass
class CaptureStats:
    """Aggregate inventory."""
    count: int = 0
    by_mode: dict[str, int] = field(default_factory=dict)
    by_status: dict[str, int] = field(default_factory=dict)
    capture_bytes: int = 0
    screenshots_bytes: int = 0
    oldest_mtime: float | None = None
    newest_mtime: float | None = None

    @property
    def total_bytes(self) -> int:
        return self.capture_bytes + self.screenshots_bytes


# ---------------------------------------------------------------------------
# Inspection helpers
# ---------------------------------------------------------------------------

def _dir_size(path: Path) -> int:
    """Recursive byte count. Returns 0 on missing / unreadable."""
    if not path.is_dir():
        return 0
    total = 0
    try:
        for child in path.rglob("*"):
            try:
                if child.is_file():
                    total += child.stat().st_size
            except OSError:
                continue
    except OSError:
        return 0
    return total


def _peek_capture(path: Path) -> tuple[str, str | None, int]:
    """Read just the start + result records to extract (mode,
    final_status, n_steps) without loading the whole file."""
    mode = "llm"
    final_status: str | None = None
    n_steps = 0
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
                    mode = str(rec.get("mode", "llm"))
                elif t == "step":
                    n_steps += 1
                elif t == "result":
                    final_status = str(rec.get("status", "")) or None
    except OSError:
        pass
    return mode, final_status, n_steps


def _resolve_screenshots(
    capture_path: Path, screenshots_root: Path,
) -> Path | None:
    """The screenshots dir shares the JSONL stem (run_id). Returns the
    path even if the dir doesn't exist on disk — caller decides."""
    candidate = screenshots_root / capture_path.stem
    return candidate if candidate.is_dir() else None


def list_captures_meta(
    captures_dir: Path,
    screenshots_root: Path,
) -> list[CaptureMeta]:
    """Walk captures_dir, return one CaptureMeta per JSONL. Sorted
    oldest-first by mtime — convenient for GC."""
    if not captures_dir.is_dir():
        return []
    out: list[CaptureMeta] = []
    for jsonl in captures_dir.rglob("*.jsonl"):
        if not jsonl.is_file():
            continue
        try:
            stat = jsonl.stat()
        except OSError:
            continue
        mode, final_status, n_steps = _peek_capture(jsonl)
        sd = _resolve_screenshots(jsonl, screenshots_root)
        out.append(CaptureMeta(
            run_id=jsonl.stem,
            mode=mode,
            path=jsonl,
            screenshots_dir=sd,
            mtime=stat.st_mtime,
            size_bytes=stat.st_size,
            screenshots_bytes=_dir_size(sd) if sd else 0,
            final_status=final_status,
            n_steps=n_steps,
        ))
    out.sort(key=lambda m: m.mtime)
    return out


def compute_stats(
    captures_dir: Path,
    screenshots_root: Path,
) -> CaptureStats:
    """Aggregate. Single pass over `list_captures_meta`."""
    metas = list_captures_meta(captures_dir, screenshots_root)
    if not metas:
        return CaptureStats()
    by_mode: dict[str, int] = {}
    by_status: dict[str, int] = {}
    cap_bytes = 0
    shot_bytes = 0
    for m in metas:
        by_mode[m.mode] = by_mode.get(m.mode, 0) + 1
        key = m.final_status or "<no result>"
        by_status[key] = by_status.get(key, 0) + 1
        cap_bytes += m.size_bytes
        shot_bytes += m.screenshots_bytes
    return CaptureStats(
        count=len(metas),
        by_mode=by_mode,
        by_status=by_status,
        capture_bytes=cap_bytes,
        screenshots_bytes=shot_bytes,
        oldest_mtime=metas[0].mtime,
        newest_mtime=metas[-1].mtime,
    )


# ---------------------------------------------------------------------------
# Garbage collection
# ---------------------------------------------------------------------------

def gc_old_captures(
    captures_dir: Path,
    screenshots_root: Path,
    *,
    older_than_days: float,
    keep_failed: bool = False,
    apply: bool = False,
) -> tuple[list[CaptureMeta], int]:
    """Identify (and optionally delete) captures older than the cutoff.

    `older_than_days`: cutoff measured from now. Files with mtime
    older than (now - days*86400) are eligible.

    `keep_failed`: if True, FAIL/ERROR captures are exempt — sometimes
    you want to keep those around for debugging long after the
    successful runs have been pruned.

    `apply`: False (default) walks and reports without touching disk —
    dry-run. True actually deletes the JSONL + matching screenshots
    dir for each eligible capture.

    Returns (eligible_metas, total_bytes_freed_or_planned).
    """
    if older_than_days < 0:
        raise ValueError(f"older_than_days must be ≥ 0, got {older_than_days}")
    cutoff = time.time() - older_than_days * 86400.0

    metas = list_captures_meta(captures_dir, screenshots_root)
    eligible: list[CaptureMeta] = []
    for m in metas:
        if m.mtime > cutoff:
            continue
        if keep_failed and m.final_status in ("FAIL", "ERROR"):
            continue
        eligible.append(m)

    bytes_total = sum(m.total_bytes for m in eligible)
    if not apply:
        return eligible, bytes_total

    for m in eligible:
        try:
            m.path.unlink()
        except OSError:
            pass
        if m.screenshots_dir is not None and m.screenshots_dir.is_dir():
            try:
                shutil.rmtree(m.screenshots_dir)
            except OSError:
                pass
    return eligible, bytes_total
