"""Trace segmentation by page-navigation boundaries.

Mining works best on contiguous within-page action subsequences.
A trace that spans page navigations (login flow → post-login first
action) easily produces an N-gram that crosses the boundary; the
miner can't tell the boundary exists unless we split it for them.
The online detector's precondition gate rejects fires from such
patterns at runtime — they're effectively dead macros.

Splitting at `url_template` change (Phase 0 page-signature primitive)
gives clean within-page segments with one URL template each. Each
emitted segment-N-gram has unambiguous preconditions and can be
auto-invoked when the live page matches.

Algorithm — single pass, no lookahead:

  segments = []
  cur_segment = []
  cur_url_template = None
  for step in trace.steps:
      url_t = step.pre_signature.url_template if available
      if cur_url_template is not None
         and url_t is not None
         and url_t != cur_url_template:
          if cur_segment: emit cur_segment
          cur_segment = []
      cur_segment.append(step)
      if url_t: cur_url_template = url_t
  if cur_segment: emit cur_segment

Steps with no signature (older captures, or capture-write hiccups)
inherit the prior segment's URL — they don't trigger a boundary.
Segments shorter than `min_segment_len` (default 1, no filter) are
kept by default; the caller can drop them if mining is producing
too much noise from one-step segments.

Sub-traces inherit their parent's `run_id` with a `__seg<N>` suffix
so dedup keys (mining support counts) treat them as distinct
sequences. `final_status` and `confidence` carry through unchanged
— a segment from a PASS run is still PASS-derived.
"""

from __future__ import annotations

from .loader import Trace, TraceStep


def segment_trace(
    trace: Trace,
    *,
    min_segment_len: int = 1,
) -> list[Trace]:
    """Split one full trace into per-URL-template sub-traces.

    `min_segment_len` (default 1) drops any segment with fewer steps;
    raise to filter out one-step segments that bloat candidate count.
    """
    if not trace.steps:
        return []

    segments: list[list[TraceStep]] = []
    current: list[TraceStep] = []
    current_url_template: str | None = None

    for step in trace.steps:
        url_t: str | None = None
        sig = step.pre_signature
        if sig and isinstance(sig, dict):
            t = sig.get("url_template")
            if isinstance(t, str) and t:
                url_t = t

        is_boundary = (
            current_url_template is not None
            and url_t is not None
            and url_t != current_url_template
        )
        if is_boundary and current:
            segments.append(current)
            current = []
        current.append(step)
        if url_t:
            current_url_template = url_t

    if current:
        segments.append(current)

    if min_segment_len > 1:
        segments = [s for s in segments if len(s) >= min_segment_len]

    if not segments:
        return []

    out: list[Trace] = []
    for i, seg_steps in enumerate(segments):
        out.append(Trace(
            run_id=f"{trace.run_id}__seg{i}",
            mode=trace.mode,
            task=trace.task,
            final_status=trace.final_status,
            confidence=trace.confidence,
            steps=list(seg_steps),
            path=trace.path,
        ))
    return out


def segment_traces(
    traces: list[Trace],
    *,
    min_segment_len: int = 1,
) -> list[Trace]:
    """Apply `segment_trace` to a list. Convenience for callers that
    work with bulk trace lists."""
    out: list[Trace] = []
    for t in traces:
        out.extend(segment_trace(t, min_segment_len=min_segment_len))
    return out
