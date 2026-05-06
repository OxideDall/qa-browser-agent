"""Capture file management — listing, stats, garbage collection.

Captures accumulate at `~/.config/qa_agent/captures/{browser,tagged}/`
under Phase 0. This subpackage is the operational hygiene layer:

  * `list_captures_meta(captures_dir, screenshots_dir)` -> list[CaptureMeta]
  * `compute_stats(captures_dir, screenshots_dir)` -> CaptureStats
  * `gc_old_captures(...)` -> (deleted_paths, bytes_freed)

CLI mirrors the API: `python -m qa_agent.macros.captures stats|list|gc`.

The cleanup also walks the per-run screenshots dirs (same run_id stamp
as the capture file) so Phase 0's storage symmetry is preserved.
"""

from __future__ import annotations

from .api import (
    CaptureMeta,
    CaptureStats,
    compute_stats,
    gc_old_captures,
    list_captures_meta,
)

__all__ = [
    "CaptureMeta",
    "CaptureStats",
    "compute_stats",
    "gc_old_captures",
    "list_captures_meta",
]
