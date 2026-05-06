"""Offline macro miner.

Reads accumulated capture JSONLs (Phase 0 substrate), mines frequent
contiguous N-grams of (verb, target_role) tuples, infers parameter
slots by comparing concrete args at the same position across
occurrences, optionally asks an LLM to label and gate candidates,
dry-run-validates against captures, then emits tagged-DSL macros
into the user's macros directory.

Public API:
  * `load_captures(captures_dir)`            -> list[Trace]
  * `extract_vocab(trace)`                   -> list[VocabItem]
  * `mine_ngrams(sequences, min_support, ...)` -> dict[ngram, set[run_id]]
  * `infer_params(ngram, occurrences)`       -> list[ParamCandidate]
  * `curate(candidate, occurrences)`         -> CuratedMacro | None
  * `validate(candidate, captures)`          -> ValidationResult
  * `emit(curated, output_root)`             -> Path

Concrete pipeline implementation lives in `__main__` so the parts can
be reused / re-ordered (e.g. running with --no-curate for a sanity
pass before paying LLM tokens).
"""

from __future__ import annotations

from .curator import CuratedMacro, curate
from .emit import emit
from .inference import ParamCandidate, infer_params
from .loader import Trace, TraceStep, load_captures
from .mining import NGram, mine_ngrams
from .validate import ValidationResult, validate
from .vocabulary import VocabItem, extract_vocab

__all__ = [
    "Trace", "TraceStep",
    "VocabItem",
    "NGram",
    "ParamCandidate",
    "CuratedMacro",
    "ValidationResult",
    "load_captures",
    "extract_vocab",
    "mine_ngrams",
    "infer_params",
    "curate",
    "validate",
    "emit",
]
