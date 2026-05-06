"""Real-world macro pipeline benchmark.

Runs every fixture in `bench/fixtures/macro_real/` N times to
accumulate captures, mines macros from the captures (LLM curator
on by default), live-validates each, installs the survivors, then
re-runs every fixture once with macros installed to measure online
detection coverage. Aggregates everything into a Markdown report.

Phases:

  warmup       — N runs/fixture, no macros installed. Source data
                 for mining + baseline metrics for confidence/aware.
  mine         — programmatic miner over the warmup captures only
                 (env-scoped to a bench-local dir).
  live_validate — replay each emitted candidate against a real browser;
                  drop the ones that fail.
  detect       — 1 run/fixture with the surviving macros installed.
                 Measure macro_detection counters per run.
  report       — emit Markdown summary into --report.

CLI:

  python -m bench.macros_bench [--repeat N] [--report PATH]
                               [--captures-dir DIR] [--macros-out DIR]
                               [--skip warmup,mine,validate,detect]

Output report covers:
  * confidence vs assert_ok correlation per fixture
  * uncertainty_reasons distribution
  * mining yield: candidates / kept / dropped (with reasons)
  * detection coverage: n_matches per post-install run
  * token deltas warmup vs post-install
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import tempfile
import time
import shutil
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# We import bench.runner.runner lazily inside main() — env vars
# (QA_CAPTURES_DIR / QA_MACROS_DIR) need to be set BEFORE qa_agent
# imports so the captures path resolution sees them.


# ---------------------------------------------------------------------------
# Per-run record + aggregations
# ---------------------------------------------------------------------------

@dataclass
class RunRecord:
    fixture_id: str
    iteration: int
    phase: str                          # "warmup" | "post_install"
    assert_ok: bool
    agent_status: str
    confidence: float | None
    signals: dict[str, int]
    tokens_in: int
    tokens_out: int
    elapsed_s: float
    n_steps: int
    n_macro_matches: int
    n_macro_suggestions: int
    n_macro_auto: int
    n_macros_loaded: int
    capture_path: str
    error: str | None = None


@dataclass
class MineRecord:
    name: str
    support: int
    length: int
    n_params: int
    path: str


@dataclass
class ValidateRecord:
    name: str
    passed: bool
    score: float
    failed_step: int | None
    failed_message: str
    elapsed_s: float


@dataclass
class BenchOutput:
    fixture_ids: list[str] = field(default_factory=list)
    warmup: list[RunRecord] = field(default_factory=list)
    post_install: list[RunRecord] = field(default_factory=list)
    mining: list[MineRecord] = field(default_factory=list)
    validation: list[ValidateRecord] = field(default_factory=list)
    captures_dir: str = ""
    macros_out: str = ""
    started_at: float = 0.0
    finished_at: float = 0.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_result(log_path: Path) -> dict:
    """Pull the {t:result} record from a Recorder JSONL."""
    if not log_path.is_file():
        return {}
    last_result: dict = {}
    try:
        with log_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("t") == "result":
                    last_result = rec
    except OSError:
        pass
    return last_result


def _make_run_record(
    fixture_id: str, iteration: int, phase: str,
    bench_summary: dict,
) -> RunRecord:
    log_path = bench_summary.get("log_path", "")
    result = _read_result(Path(log_path)) if log_path else {}
    macro = result.get("macro_detection") or {}
    return RunRecord(
        fixture_id=fixture_id,
        iteration=iteration,
        phase=phase,
        assert_ok=bool(bench_summary.get("assert_ok")),
        agent_status=str(bench_summary.get("agent_status") or "ERROR"),
        confidence=result.get("confidence"),
        signals=dict(result.get("signals") or {}),
        tokens_in=int(result.get("total_in") or 0),
        tokens_out=int(result.get("total_out") or 0),
        elapsed_s=float(result.get("wall_seconds") or 0.0),
        n_steps=int(result.get("steps_used") or 0),
        n_macro_matches=int(macro.get("n_matches") or 0),
        n_macro_suggestions=int(macro.get("n_suggestions") or 0),
        n_macro_auto=int(macro.get("n_auto_invocations") or 0),
        n_macros_loaded=int(macro.get("n_macros_loaded") or 0),
        capture_path=log_path,
        error=bench_summary.get("error"),
    )


def _phase_runs(
    fixture_ids: list[str], n: int, phase: str,
    macros_root: Path | None,
    captures_dir: Path,
) -> list[RunRecord]:
    """Run each fixture `n` times, return per-run records."""
    # Scope env vars BEFORE importing qa_agent so capture paths resolve right.
    os.environ["QA_CAPTURES_DIR"] = str(captures_dir)
    if macros_root is not None:
        os.environ["QA_MACROS_DIR"] = str(macros_root)
    elif "QA_MACROS_DIR" in os.environ:
        del os.environ["QA_MACROS_DIR"]

    # qa_agent reads env vars at runtime (CAPTURES_DIR / MACROS_DIR
    # are function-resolved per-call, not module-level constants), so
    # plain import is enough — no reload juggling.
    import bench.runner.runner as bench_runner

    out: list[RunRecord] = []
    for fid in fixture_ids:
        for i in range(n):
            sys.stderr.write(
                f"\n[bench] {phase} {fid} iter {i + 1}/{n}\n"
            )
            sys.stderr.flush()
            try:
                summary = bench_runner.run_one(fid, headless=True, verbose=False)
            except Exception as e:
                summary = {
                    "fixture_id": fid,
                    "agent_status": "ERROR",
                    "assert_ok": False,
                    "log_path": "",
                    "error": f"{type(e).__name__}: {e}",
                }
                traceback.print_exc()
            out.append(_make_run_record(fid, i, phase, summary))
    return out


def _phase_mine(
    captures_dir: Path,
    macros_out: Path,
    use_llm: bool = True,
    min_support: int = 2,
    min_len: int = 3,
    max_len: int = 12,
) -> list[MineRecord]:
    """Run the miner programmatically over the bench captures."""
    from qa_agent.macros.miner import (
        load_captures, extract_vocab, mine_ngrams, infer_params,
        curate, validate, emit,
    )
    from qa_agent.macros.miner.mining import filter_redundant

    traces = load_captures(captures_dir)
    seqs = [extract_vocab(t) for t in traces]
    nonempty = [(t, s) for t, s in zip(traces, seqs) if s]
    if not nonempty:
        return []
    traces = [t for t, _ in nonempty]
    seqs = [s for _, s in nonempty]

    raw = mine_ngrams(seqs, min_support=min_support, min_n=min_len, max_n=max_len)
    closed = filter_redundant(raw)

    out: list[MineRecord] = []
    for ng in closed[:30]:
        slots = infer_params(ng, seqs, traces)
        cur = curate(ng, slots, traces, use_llm=use_llm)
        if cur is None or not cur.keep:
            continue
        v = validate(cur, seqs, traces, ng.occurrences)
        if not v.passed:
            continue
        path = emit(cur, ng.occurrences, traces, seqs, macros_out)
        out.append(MineRecord(
            name=cur.name,
            support=ng.support,
            length=ng.length,
            n_params=len(cur.param_names),
            path=str(path),
        ))
    return out


def _phase_live_validate(macros_out: Path) -> list[ValidateRecord]:
    """Replay every emitted macro live; drop the ones that fail."""
    from qa_agent.macros import list_macros, load_macro, live_validate
    out: list[ValidateRecord] = []
    for entry in list_macros(root=macros_out):
        if "error" in entry:
            continue
        name = entry["name"]
        t0 = time.time()
        try:
            macro = load_macro(name, root=macros_out)
            r = live_validate(macro, headless=True)
        except Exception as e:
            elapsed = time.time() - t0
            out.append(ValidateRecord(
                name=name, passed=False, score=0.0,
                failed_step=None,
                failed_message=f"{type(e).__name__}: {e}",
                elapsed_s=elapsed,
            ))
            try:
                shutil.rmtree(macros_out / name)
            except OSError:
                pass
            continue
        elapsed = time.time() - t0
        out.append(ValidateRecord(
            name=name, passed=r.passed, score=r.score,
            failed_step=r.failed_step,
            failed_message=r.failed_message,
            elapsed_s=elapsed,
        ))
        if not r.passed:
            try:
                shutil.rmtree(macros_out / name)
            except OSError:
                pass
    return out


# ---------------------------------------------------------------------------
# Aggregations + report
# ---------------------------------------------------------------------------

def _agg_tokens(records: list[RunRecord]) -> tuple[int, int]:
    return (
        sum(r.tokens_in for r in records),
        sum(r.tokens_out for r in records),
    )


def _agg_pass_rate(records: list[RunRecord]) -> float:
    if not records:
        return 0.0
    return sum(1 for r in records if r.assert_ok) / len(records)


def _agg_confidence_split(
    records: list[RunRecord],
) -> tuple[list[float], list[float]]:
    """Return (confidences for PASS runs, confidences for FAIL runs)."""
    pas = [r.confidence for r in records
           if r.assert_ok and r.confidence is not None]
    fal = [r.confidence for r in records
           if not r.assert_ok and r.confidence is not None]
    return [float(c) for c in pas], [float(c) for c in fal]


def _safe_mean(values: list[float]) -> float:
    return statistics.mean(values) if values else 0.0


def _md_table(rows: list[dict], cols: list[tuple[str, str]]) -> str:
    """Tiny Markdown table renderer. cols: [(header, key), ...]."""
    if not rows:
        return "_(no rows)_\n"
    head = "| " + " | ".join(h for h, _ in cols) + " |"
    sep = "|" + "|".join(["---"] * len(cols)) + "|"
    body_lines = []
    for r in rows:
        cells = []
        for _, key in cols:
            v = r.get(key, "")
            if isinstance(v, float):
                cells.append(f"{v:.3f}")
            else:
                cells.append(str(v))
        body_lines.append("| " + " | ".join(cells) + " |")
    return "\n".join([head, sep] + body_lines) + "\n"


def _write_report(out_path: Path, b: BenchOutput) -> None:
    lines: list[str] = []
    lines.append(f"# Macros pipeline real-world benchmark — {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(b.started_at))}Z")
    lines.append("")
    lines.append(f"- Fixtures: {len(b.fixture_ids)} (`{', '.join(b.fixture_ids)}`)")
    lines.append(f"- Warmup runs: {len(b.warmup)} ({len(b.warmup) // max(1, len(b.fixture_ids))} per fixture)")
    lines.append(f"- Post-install runs: {len(b.post_install)}")
    lines.append(f"- Mining yield: {len(b.mining)} candidates emitted")
    lines.append(f"- Live-validate verdict: {sum(1 for v in b.validation if v.passed)} kept / {sum(1 for v in b.validation if not v.passed)} dropped")
    lines.append(f"- Wallclock: {b.finished_at - b.started_at:.1f}s")
    lines.append(f"- Captures dir: `{b.captures_dir}`")
    lines.append(f"- Macros out: `{b.macros_out}`")
    lines.append("")

    # --- Per-fixture summary ---
    lines.append("## Per-fixture summary (warmup phase)")
    lines.append("")
    rows = []
    for fid in b.fixture_ids:
        runs = [r for r in b.warmup if r.fixture_id == fid]
        if not runs:
            continue
        pass_runs = [r for r in runs if r.assert_ok]
        fail_runs = [r for r in runs if not r.assert_ok]
        confs_pass, confs_fail = _agg_confidence_split(runs)
        rows.append({
            "fixture": fid,
            "runs": len(runs),
            "pass_rate": _agg_pass_rate(runs),
            "mean_steps": _safe_mean([r.n_steps for r in runs]),
            "mean_elapsed_s": _safe_mean([r.elapsed_s for r in runs]),
            "mean_tok_in": int(_safe_mean([r.tokens_in for r in runs])),
            "mean_tok_out": int(_safe_mean([r.tokens_out for r in runs])),
            "mean_conf_pass": _safe_mean(confs_pass),
            "mean_conf_fail": _safe_mean(confs_fail),
        })
    lines.append(_md_table(rows, [
        ("fixture", "fixture"),
        ("runs", "runs"),
        ("pass_rate", "pass_rate"),
        ("steps̄", "mean_steps"),
        ("wall̄ (s)", "mean_elapsed_s"),
        ("tok_in̄", "mean_tok_in"),
        ("tok_out̄", "mean_tok_out"),
        ("conf̄ on PASS", "mean_conf_pass"),
        ("conf̄ on FAIL", "mean_conf_fail"),
    ]))
    lines.append("")

    # --- Confidence aware-ness ---
    lines.append("## Confidence ↔ assert_ok correlation")
    lines.append("")
    confs_pass_all, confs_fail_all = _agg_confidence_split(b.warmup)
    if confs_pass_all or confs_fail_all:
        lines.append(
            f"- mean confidence on assert_ok=True : "
            f"**{_safe_mean(confs_pass_all):.3f}** "
            f"(n={len(confs_pass_all)})"
        )
        lines.append(
            f"- mean confidence on assert_ok=False: "
            f"**{_safe_mean(confs_fail_all):.3f}** "
            f"(n={len(confs_fail_all)})"
        )
        if confs_pass_all and confs_fail_all:
            delta = _safe_mean(confs_pass_all) - _safe_mean(confs_fail_all)
            lines.append(
                f"- delta (PASS−FAIL): **{delta:+.3f}** — "
                "positive ⇒ confidence does discriminate"
            )
    else:
        lines.append("_(no confidence data — all runs errored?)_")
    lines.append("")

    # --- Uncertainty signals ---
    lines.append("## Aggregate uncertainty signals (warmup)")
    lines.append("")
    sig_keys = ["done_reasks", "hallucinated_ids", "soft_loops",
                "vision_repeats", "parse_errors", "flicker"]
    totals = {k: sum(r.signals.get(k, 0) for r in b.warmup) for k in sig_keys}
    lines.append("| signal | total occurrences |")
    lines.append("|---|---|")
    for k in sig_keys:
        lines.append(f"| {k} | {totals[k]} |")
    lines.append("")

    # --- Mining yield ---
    lines.append("## Mining yield (LLM curator on)")
    lines.append("")
    if b.mining:
        lines.append(_md_table([{
            "name": m.name,
            "support": m.support,
            "length": m.length,
            "params": m.n_params,
        } for m in b.mining], [
            ("name", "name"),
            ("support", "support"),
            ("length", "length"),
            ("params", "params"),
        ]))
    else:
        lines.append("_(no candidates emitted)_\n")
    lines.append("")

    # --- Live validation ---
    lines.append("## Live-validate verdicts")
    lines.append("")
    if b.validation:
        lines.append(_md_table([{
            "name": v.name,
            "passed": "✓" if v.passed else "✗",
            "score": v.score,
            "failed_step": v.failed_step or "-",
            "elapsed_s": v.elapsed_s,
            "failure": (v.failed_message[:80] if v.failed_message else "-"),
        } for v in b.validation], [
            ("name", "name"),
            ("passed", "passed"),
            ("score", "score"),
            ("failed step", "failed_step"),
            ("elapsed (s)", "elapsed_s"),
            ("failure", "failure"),
        ]))
    else:
        lines.append("_(no validation rows)_\n")
    lines.append("")

    # --- Detection coverage ---
    lines.append("## Detection coverage (post-install runs)")
    lines.append("")
    if b.post_install:
        rows = []
        for r in b.post_install:
            rows.append({
                "fixture": r.fixture_id,
                "loaded": r.n_macros_loaded,
                "matches": r.n_macro_matches,
                "suggestions": r.n_macro_suggestions,
                "auto_invokes": r.n_macro_auto,
                "assert_ok": "✓" if r.assert_ok else "✗",
                "tok_in": r.tokens_in,
                "tok_out": r.tokens_out,
            })
        lines.append(_md_table(rows, [
            ("fixture", "fixture"),
            ("loaded", "loaded"),
            ("matches", "matches"),
            ("suggestions", "suggestions"),
            ("auto_invokes", "auto_invokes"),
            ("assert_ok", "assert_ok"),
            ("tok_in", "tok_in"),
            ("tok_out", "tok_out"),
        ]))
    else:
        lines.append("_(no post-install data)_\n")
    lines.append("")

    # --- Token deltas ---
    lines.append("## Token deltas — warmup vs post-install")
    lines.append("")
    rows = []
    for fid in b.fixture_ids:
        warm = [r for r in b.warmup if r.fixture_id == fid]
        post = [r for r in b.post_install if r.fixture_id == fid]
        warm_in = int(_safe_mean([r.tokens_in for r in warm])) if warm else 0
        post_in = int(_safe_mean([r.tokens_in for r in post])) if post else 0
        rows.append({
            "fixture": fid,
            "warmup_in̄": warm_in,
            "post_in̄": post_in,
            "delta": post_in - warm_in,
            "delta_%": (
                f"{(post_in - warm_in) * 100 / warm_in:+.1f}%"
                if warm_in else "-"
            ),
        })
    lines.append(_md_table(rows, [
        ("fixture", "fixture"),
        ("warmup tok_in̄", "warmup_in̄"),
        ("post-install tok_in̄", "post_in̄"),
        ("delta", "delta"),
        ("delta %", "delta_%"),
    ]))
    lines.append("")

    # --- Raw JSONL appendix ---
    lines.append("## Raw appendix")
    lines.append("")
    lines.append(f"- Per-run JSONL captures live under `{b.captures_dir}`")
    lines.append(f"- Emitted macros under `{b.macros_out}`")
    lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="bench.macros_bench",
        description=(
            "Real-world macro pipeline benchmark. Runs every "
            "macro_real fixture N times, mines macros, validates, "
            "re-runs with installed macros, writes a Markdown report."
        ),
    )
    ap.add_argument("--repeat", type=int, default=3,
                    help="Warmup runs per fixture (default: 3)")
    ap.add_argument("--captures-dir",
                    help="Bench-local captures dir (default: temp)")
    ap.add_argument("--macros-out",
                    help="Bench-local macros dir (default: temp)")
    ap.add_argument("--report", default="bench/macros_bench_report.md",
                    help="Where to write the Markdown report")
    ap.add_argument("--no-llm-curate", action="store_true",
                    help="Skip LLM curation (use auto-name + keep all)")
    ap.add_argument("--skip", default="",
                    help="Comma-separated phases to skip: "
                         "warmup,mine,validate,detect")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    skip = {s.strip() for s in args.skip.split(",") if s.strip()}

    # Discover fixtures BEFORE setting env vars (env doesn't affect fixture loader).
    from bench.runner.loader import discover_fixtures
    fixture_ids = sorted(discover_fixtures(category="macro_real"))
    if not fixture_ids:
        print("[bench] no fixtures under macro_real/ — aborting", file=sys.stderr)
        return 2
    print(f"[bench] fixtures: {fixture_ids}", file=sys.stderr)

    captures_dir = (
        Path(args.captures_dir).expanduser()
        if args.captures_dir else
        Path(tempfile.mkdtemp(prefix="qa_macros_bench_caps_"))
    )
    macros_out = (
        Path(args.macros_out).expanduser()
        if args.macros_out else
        Path(tempfile.mkdtemp(prefix="qa_macros_bench_out_"))
    )
    captures_dir.mkdir(parents=True, exist_ok=True)
    macros_out.mkdir(parents=True, exist_ok=True)

    out = BenchOutput(
        fixture_ids=fixture_ids,
        captures_dir=str(captures_dir),
        macros_out=str(macros_out),
        started_at=time.time(),
    )

    if "warmup" not in skip:
        out.warmup = _phase_runs(
            fixture_ids, args.repeat, "warmup",
            macros_root=None, captures_dir=captures_dir,
        )

    if "mine" not in skip:
        out.mining = _phase_mine(
            captures_dir, macros_out,
            use_llm=not args.no_llm_curate,
        )

    if "validate" not in skip:
        out.validation = _phase_live_validate(macros_out)

    if "detect" not in skip:
        out.post_install = _phase_runs(
            fixture_ids, 1, "post_install",
            macros_root=macros_out, captures_dir=captures_dir,
        )

    out.finished_at = time.time()

    report_path = Path(args.report).expanduser().resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    _write_report(report_path, out)

    print(file=sys.stderr)
    print(f"[bench] report → {report_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
