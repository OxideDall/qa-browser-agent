"""Dry-run validation against captured traces.

The miner emits a candidate macro (tagged DSL with parameter slots).
Before promoting it to the user's macro library we want a sanity
check: does this macro, with the param values observed during
mining, actually match the trace it was mined from? If we replayed
it on each source run, would each step's verb + role line up with
what really happened?

We do NOT replay against a live browser here — that's expensive and
runs into "the marketplace catalog rotated" flakes. Validation here
is **trace-vs-macro structural equivalence**:

  for each occurrence of the candidate in the source captures:
    align macro steps with the trace's steps starting at the
    occurrence's start_idx
    score = (# steps where verb+role match) / (# steps in macro)
  overall_score = mean of per-occurrence scores

A candidate with overall_score < 0.95 is suspicious — most likely
the inference pass parameterised something that's actually variable
in unexpected ways, or different runs took genuinely different
paths and the miner over-clustered. Drop those.

This is a *structural* check, not a behavioural one. A real-page
dry-run validator (Phase 1.5) is a separate, optional pass — gated
on having a live browser and acceptance of the cost.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .curator import CuratedMacro
from .loader import Trace
from .vocabulary import VocabItem


@dataclass
class ValidationResult:
    """Outcome of structural validation against source captures."""
    score: float                        # 0.0 — 1.0
    n_occurrences: int
    matched_steps: int
    total_steps: int
    misaligned: list[str] = field(default_factory=list)
    passed: bool = False                # ≥ MIN_SCORE


MIN_SCORE = 0.95


def validate(
    curated: CuratedMacro,
    sequences: list[list[VocabItem]],
    traces: list[Trace],
    occurrences: list,                  # list[NGramOccurrence] from mining
) -> ValidationResult:
    """Score the curated candidate against the same sequences it was
    mined from. Use the occurrences list directly so we know exactly
    where in each trace it appeared."""
    n = len(curated.pattern)
    if n == 0 or not occurrences:
        return ValidationResult(score=0.0, n_occurrences=0,
                                matched_steps=0, total_steps=0, passed=False)

    matched_total = 0
    total_total = 0
    misaligned: list[str] = []
    expected = curated.pattern
    for occ in occurrences:
        seq = sequences[occ.seq_id]
        if occ.start_idx + n > len(seq):
            misaligned.append(
                f"run {occ.seq_id} start {occ.start_idx}: pattern would "
                f"overflow sequence of length {len(seq)}"
            )
            total_total += n
            continue
        for j in range(n):
            actual = seq[occ.start_idx + j]
            if actual.key() == expected[j].key():
                matched_total += 1
            else:
                misaligned.append(
                    f"run {occ.seq_id} step {occ.start_idx + j}: "
                    f"expected {expected[j].key()}, got {actual.key()}"
                )
            total_total += 1

    score = matched_total / total_total if total_total else 0.0
    return ValidationResult(
        score=round(score, 4),
        n_occurrences=len(occurrences),
        matched_steps=matched_total,
        total_steps=total_total,
        misaligned=misaligned[:20],
        passed=score >= MIN_SCORE,
    )
