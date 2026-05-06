"""Frequent contiguous N-gram mining.

We use contiguous (subarray, not subsequence) N-grams instead of full
PrefixSpan because:

  * regression-test action traces are short and structured — gaps
    between actions are usually wait/look/screenshot which we
    deliberately drop in the vocabulary pass; a "skill" is a
    contiguous chunk of the remaining sequence.
  * contiguous patterns compile directly into a tagged-DSL block;
    PrefixSpan-style gap-allowing patterns would need a separate
    representation.
  * implementation is ~30 lines, no dependencies, easy to audit.

If we ever need gap-allowing mining (cross-page workflows whose
intermediate steps vary), drop in PrefixSpan later — the rest of
the pipeline doesn't care about the source algorithm.

Algorithm:

  for each sequence
    for each window length n in [min_n, max_n]
      for each starting position i
        ngram = tuple(seq[i : i+n])
        record (ngram, sequence_id, starting_position)
  return all ngrams seen in >= min_support distinct sequences

`min_support` is on **distinct sequences**, not occurrences — five
copies of the same skill in one run shouldn't make it look like a
five-run pattern. That's how PrefixSpan / BIDE define support too.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from .vocabulary import VocabItem


@dataclass
class NGramOccurrence:
    """One observation of a candidate N-gram in a specific trace."""
    seq_id: int                # index into the input sequences list
    start_idx: int             # position in that sequence


@dataclass
class NGram:
    """A candidate frequent N-gram + its observations."""
    pattern: tuple[VocabItem, ...]
    occurrences: list[NGramOccurrence] = field(default_factory=list)

    @property
    def support(self) -> int:
        """Number of distinct sequences containing the pattern."""
        return len({o.seq_id for o in self.occurrences})

    @property
    def length(self) -> int:
        return len(self.pattern)

    @property
    def total_occurrences(self) -> int:
        return len(self.occurrences)

    def key(self) -> tuple[tuple[str, str], ...]:
        """Hashable comparison key — compares verb+classifier per item,
        ignoring per-item step_no."""
        return tuple(item.key() for item in self.pattern)


def mine_ngrams(
    sequences: list[list[VocabItem]],
    *,
    min_support: int = 3,
    min_n: int = 2,
    max_n: int = 8,
) -> list[NGram]:
    """Mine frequent contiguous N-grams across `sequences`.

    Returns a list of NGram objects, sorted by (descending support,
    descending length) — caller usually wants the highest-support
    longest patterns first.
    """
    if min_support < 2:
        raise ValueError("min_support must be ≥ 2 (single-run is not a pattern)")
    if min_n < 1:
        raise ValueError("min_n must be ≥ 1")
    if max_n < min_n:
        raise ValueError("max_n must be ≥ min_n")

    # Bucket: ngram_key -> NGram (we mutate occurrences as we walk).
    buckets: dict[tuple[tuple[str, str], ...], NGram] = {}

    for sid, seq in enumerate(sequences):
        if not seq:
            continue
        L = len(seq)
        for n in range(min_n, min(max_n, L) + 1):
            for i in range(L - n + 1):
                window = tuple(seq[i:i + n])
                key = tuple(item.key() for item in window)
                bucket = buckets.get(key)
                if bucket is None:
                    bucket = NGram(pattern=window)
                    buckets[key] = bucket
                bucket.occurrences.append(NGramOccurrence(sid, i))

    out = [ng for ng in buckets.values() if ng.support >= min_support]
    out.sort(key=lambda ng: (ng.support, ng.length), reverse=True)
    return out


def filter_redundant(ngrams: list[NGram]) -> list[NGram]:
    """Drop N-grams that are strict prefix / suffix of a longer N-gram
    with the **same support** — that longer one already captures
    everything.

    A 3-gram with support 5 is redundant if its 4-gram extension
    appears in all 5 of those runs. The longer one is more specific
    and equally frequent, so the shorter one adds no information.

    Mirrors the "closed pattern" idea from BIDE without the full BIDE
    algorithm — sufficient for our scale.
    """
    by_support: dict[int, list[NGram]] = defaultdict(list)
    for ng in ngrams:
        by_support[ng.support].append(ng)

    keep: list[NGram] = []
    for support, group in by_support.items():
        # group is all N-grams sharing this exact support. Sort by
        # length descending so longer patterns dominate.
        group_sorted = sorted(group, key=lambda ng: ng.length, reverse=True)
        # Mark patterns that are contained in another same-support one.
        to_drop: set[int] = set()
        keys = [g.key() for g in group_sorted]
        for short_idx in range(len(group_sorted)):
            short_key = keys[short_idx]
            for long_idx in range(short_idx):
                long_key = keys[long_idx]
                if len(short_key) >= len(long_key):
                    continue
                if _is_contiguous_subseq(short_key, long_key):
                    to_drop.add(short_idx)
                    break
        keep.extend(g for i, g in enumerate(group_sorted) if i not in to_drop)
    keep.sort(key=lambda ng: (ng.support, ng.length), reverse=True)
    return keep


def _is_contiguous_subseq(short: tuple, long: tuple) -> bool:
    if not short or len(short) > len(long):
        return False
    n = len(short)
    for i in range(len(long) - n + 1):
        if long[i:i + n] == short:
            return True
    return False
