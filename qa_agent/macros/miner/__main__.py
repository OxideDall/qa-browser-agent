"""CLI entry: `python -m qa_agent.macros.miner [...]`.

Pipeline:

  1. Load capture JSONLs from --captures-dir.
  2. Reduce each trace to a vocab sequence.
  3. Mine frequent contiguous N-grams (--min-support, --min-len, --max-len).
  4. Filter redundant patterns (closed-pattern style).
  5. For each surviving candidate:
       a. Infer parameter slots vs. concrete args.
       b. Curate (LLM unless --no-curate): name, description, gate.
       c. Validate structural alignment vs. source captures.
       d. Emit tagged DSL + meta.json under --macros-out.
  6. Print summary table.

`--dry-run` skips step 5d (no files written).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .curator import curate
from .emit import emit
from .inference import infer_params
from .loader import load_captures
from .mining import filter_redundant, mine_ngrams
from .validate import validate
from .vocabulary import extract_vocab
from ..library import MACROS_DIR


CAPTURES_DEFAULT = Path.home() / ".config" / "qa_agent" / "captures"


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="qa_agent.macros.miner",
        description=(
            "Offline miner: turn captured agent traces into reusable "
            "tagged-DSL macros. Reads ~/.config/qa_agent/captures/, "
            "writes ~/.config/qa_agent/macros/."
        ),
    )
    ap.add_argument(
        "--captures-dir",
        default=str(CAPTURES_DEFAULT),
        help=f"Where to read traces (default: {CAPTURES_DEFAULT})",
    )
    ap.add_argument(
        "--macros-out",
        default=None,
        help="Where to write mined macros (default: $QA_MACROS_DIR or "
             "~/.config/qa_agent/macros/)",
    )
    ap.add_argument(
        "--min-support", type=int, default=3,
        help="Minimum distinct runs a pattern must appear in (default: 3)",
    )
    ap.add_argument(
        "--min-len", type=int, default=2,
        help="Minimum N-gram length (default: 2)",
    )
    ap.add_argument(
        "--max-len", type=int, default=8,
        help="Maximum N-gram length (default: 8)",
    )
    ap.add_argument(
        "--no-curate", action="store_true",
        help="Skip LLM curation; auto-name and keep every candidate.",
    )
    ap.add_argument(
        "--no-validate", action="store_true",
        help="Skip structural validation against source captures.",
    )
    ap.add_argument(
        "--include-failed", action="store_true",
        help="Mine from FAIL/ERROR runs too (default: PASS only).",
    )
    ap.add_argument(
        "--include-tagged", action="store_true",
        help="Mine from tagged-mode captures too (default: LLM-mode only — "
             "mining tagged scripts is circular).",
    )
    ap.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be emitted; don't write files.",
    )
    ap.add_argument(
        "--max-emit", type=int, default=20,
        help="Cap on how many macros to emit per run (default: 20).",
    )
    ap.add_argument(
        "-v", "--verbose", action="store_true",
        help="Print per-stage details.",
    )
    return ap


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    captures_dir = Path(args.captures_dir).expanduser()
    out_root = (
        Path(args.macros_out).expanduser()
        if args.macros_out else MACROS_DIR()
    )

    print(f"[miner] captures_dir = {captures_dir}", file=sys.stderr)
    print(f"[miner] macros_out   = {out_root}", file=sys.stderr)

    traces = load_captures(
        captures_dir,
        include_failed=args.include_failed,
        include_tagged=args.include_tagged,
    )
    print(f"[miner] loaded {len(traces)} traces", file=sys.stderr)
    if not traces:
        print(f"[miner] no eligible traces in {captures_dir}", file=sys.stderr)
        return 0

    sequences = [extract_vocab(t) for t in traces]
    nonempty = [(t, s) for t, s in zip(traces, sequences) if s]
    if not nonempty:
        print("[miner] no traces had any mineable steps", file=sys.stderr)
        return 0
    traces, sequences = zip(*nonempty)
    traces = list(traces)
    sequences = list(sequences)

    if args.verbose:
        print(f"[miner] vocab sizes: "
              f"{[len(s) for s in sequences[:10]]}{'...' if len(sequences) > 10 else ''}",
              file=sys.stderr)

    raw_ngrams = mine_ngrams(
        sequences,
        min_support=max(2, args.min_support),
        min_n=args.min_len,
        max_n=args.max_len,
    )
    print(f"[miner] mined {len(raw_ngrams)} N-grams ≥ "
          f"support {args.min_support}", file=sys.stderr)

    closed = filter_redundant(raw_ngrams)
    print(f"[miner] {len(closed)} closed patterns after redundancy filter",
          file=sys.stderr)

    emitted: list[dict] = []
    skipped: list[dict] = []

    for ngram in closed:
        if len(emitted) >= args.max_emit:
            skipped.append({
                "name": "<cap>", "reason": f"--max-emit cap of {args.max_emit}",
            })
            break

        slots = infer_params(ngram, sequences, traces)

        curated = curate(
            ngram, slots, traces, use_llm=not args.no_curate,
        )
        if curated is None:
            skipped.append({
                "pattern_len": ngram.length, "support": ngram.support,
                "reason": "curator rejected",
            })
            continue
        if not curated.keep:
            skipped.append({
                "name": curated.name, "support": ngram.support,
                "reason": "curator gated keep=false",
            })
            continue

        if not args.no_validate:
            v = validate(curated, sequences, traces, ngram.occurrences)
            if not v.passed:
                skipped.append({
                    "name": curated.name, "support": ngram.support,
                    "reason": f"validation score {v.score:.2f} < 0.95",
                    "misaligned": v.misaligned[:3],
                })
                continue

        if args.dry_run:
            emitted.append({
                "name": curated.name, "support": ngram.support,
                "length": ngram.length, "params": list(curated.param_names.values()),
                "dry_run": True,
            })
            continue

        # Re-attach step_no metadata to pattern items so emit can look up
        # the original TraceStep for each step.
        # mine_ngrams preserved the original VocabItem objects (including
        # step_no), so this is already in place — no rebuild needed.
        path = emit(curated, ngram.occurrences, traces, out_root)
        emitted.append({
            "name": curated.name, "support": ngram.support,
            "length": ngram.length, "params": list(curated.param_names.values()),
            "path": str(path),
        })

    print()
    print(f"[miner] emitted {len(emitted)} macro(s):")
    for row in emitted:
        params = ", ".join(row.get("params") or [])
        tag = " [DRY-RUN]" if row.get("dry_run") else ""
        print(
            f"  {row['name']:<40}  len={row['length']}  "
            f"support={row['support']}  params=[{params}]{tag}"
        )
    if skipped and args.verbose:
        print()
        print(f"[miner] skipped {len(skipped)} candidate(s):")
        for row in skipped:
            print(f"  {row.get('name', '<unnamed>')}: {row['reason']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
