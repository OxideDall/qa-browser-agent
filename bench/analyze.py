"""Aggregate bench/results/runs/*.jsonl into a results table.

Usage:
    python -m bench.analyze                       # latest run per fixture
    python -m bench.analyze --all-runs            # every run
    python -m bench.analyze --category static_ui
    python -m bench.analyze --json                # machine-readable dump
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

RESULTS_RUNS = Path(__file__).resolve().parent / "results" / "runs"


def parse_run(path: Path) -> dict[str, Any]:
    """Read one JSONL file → flat run summary dict."""
    out: dict[str, Any] = {
        "log_path": str(path),
        "fixture_id": None,
        "category": None,
        "level": None,
        "title": None,
        "agent_status": None,
        "agent_description": None,
        "assert_ok": None,
        "assert_msg": None,
        "steps_used": 0,
        "wall_seconds": 0.0,
        "total_in": 0,
        "total_out": 0,
        "loop_hits_soft": 0,
        "loop_hits_hard": 0,
        "blocks_mm": 0,
        "done_reasks": 0,
        "vision_steps": 0,
        "step_latency_ms": [],
    }
    with path.open() as f:
        for line in f:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            t = rec.get("t")
            if t == "start":
                out["fixture_id"] = rec.get("fixture_id")
                out["category"] = rec.get("category")
                out["level"] = rec.get("level")
                out["title"] = rec.get("title")
            elif t == "step":
                out["steps_used"] = rec.get("step", out["steps_used"])
                lh = rec.get("loop_hit")
                if lh == "soft":
                    out["loop_hits_soft"] += 1
                elif lh == "hard":
                    out["loop_hits_hard"] += 1
                if rec.get("blocked") == "mm_popup":
                    out["blocks_mm"] += 1
                if rec.get("done_reasked"):
                    out["done_reasks"] += 1
                if rec.get("vision"):
                    out["vision_steps"] += 1
                if rec.get("latency_ms") is not None:
                    out["step_latency_ms"].append(rec["latency_ms"])
            elif t == "result":
                out["agent_status"] = rec.get("status")
                out["agent_description"] = rec.get("description")
                out["wall_seconds"] = rec.get("wall_seconds", 0.0)
                out["total_in"] = rec.get("total_in", 0)
                out["total_out"] = rec.get("total_out", 0)
            elif t == "assert":
                out["assert_ok"] = rec.get("ok")
                out["assert_msg"] = rec.get("msg")
    return out


def collect_runs(category: str | None = None,
                 level: int | None = None,
                 latest_only: bool = True) -> list[dict[str, Any]]:
    if not RESULTS_RUNS.exists():
        return []
    paths = sorted(RESULTS_RUNS.glob("*.jsonl"))
    runs = [parse_run(p) for p in paths]
    runs = [r for r in runs if r["fixture_id"]]
    if category:
        runs = [r for r in runs if r["category"] == category]
    if level is not None:
        runs = [r for r in runs if r["level"] == level]
    if latest_only:
        latest: dict[str, dict[str, Any]] = {}
        for r in runs:
            fid = r["fixture_id"]
            prev = latest.get(fid)
            if prev is None or r["log_path"] > prev["log_path"]:
                latest[fid] = r
        runs = list(latest.values())
    runs.sort(key=lambda r: (r["category"] or "", r["level"] or 0, r["fixture_id"] or ""))
    return runs


def _flag(run: dict) -> str:
    if run["assert_ok"] is True:
        return "PASS"
    if run["agent_status"] == "ERROR" or run["agent_status"] is None:
        return "ERR "
    return "FAIL"


def _p(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round(pct / 100 * (len(s) - 1)))))
    return float(s[k])


def print_table(runs: list[dict[str, Any]]) -> None:
    if not runs:
        print("(no runs)")
        return
    # Per-fixture rows
    cols = ("flag", "fixture_id", "L", "steps", "tok_in", "tok_out",
            "wall_s", "vision", "soft", "hard", "reask", "p50ms", "p95ms",
            "assert_msg")
    header = (
        f"{'':4} {'fixture':<28} {'L':>1} {'st':>3} {'in':>6} {'out':>4} "
        f"{'sec':>5} {'vis':>3} {'sft':>3} {'hrd':>3} {'rsk':>3} "
        f"{'p50':>4} {'p95':>5}  msg"
    )
    print(header)
    print("-" * (len(header) + 20))
    for r in runs:
        lat = r["step_latency_ms"]
        msg = r["assert_msg"] or ""
        print(
            f"{_flag(r):<4} "
            f"{r['fixture_id'][:28]:<28} "
            f"{r['level']:>1} "
            f"{r['steps_used']:>3} "
            f"{r['total_in']:>6} "
            f"{r['total_out']:>4} "
            f"{r['wall_seconds']:>5.1f} "
            f"{r['vision_steps']:>3} "
            f"{r['loop_hits_soft']:>3} "
            f"{r['loop_hits_hard']:>3} "
            f"{r['done_reasks']:>3} "
            f"{int(_p(lat, 50)):>4} "
            f"{int(_p(lat, 95)):>5}  "
            f"{msg[:60]}"
        )

    # Aggregate by category
    print()
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for r in runs:
        by_cat[r["category"] or "?"].append(r)
    print(f"{'category':<22} {'pass':>4}/{'tot':>3}  "
          f"{'avg_st':>6}  {'avg_tok':>7}  {'p50_tok':>7}  {'p95_tok':>7}  "
          f"{'avg_s':>5}  {'p95_s':>5}")
    print("-" * 84)
    for cat, rs in sorted(by_cat.items()):
        passing = sum(1 for r in rs if r["assert_ok"])
        avg_steps = statistics.mean(r["steps_used"] for r in rs)
        toks = [r["total_in"] + r["total_out"] for r in rs]
        avg_tok = statistics.mean(toks)
        p50_tok = _p(toks, 50)
        p95_tok = _p(toks, 95)
        walls = [r["wall_seconds"] for r in rs]
        avg_wall = statistics.mean(walls)
        p95_wall = _p(walls, 95)
        print(f"{cat:<22} {passing:>4}/{len(rs):>3}  "
              f"{avg_steps:>6.1f}  {avg_tok:>7.0f}  {p50_tok:>7.0f}  "
              f"{p95_tok:>7.0f}  {avg_wall:>5.1f}  {p95_wall:>5.1f}")

    # Cost-per-PASS (pure bench economics — only counts successful runs)
    pass_runs = [r for r in runs if r["assert_ok"]]
    if pass_runs:
        pass_toks = [r["total_in"] + r["total_out"] for r in pass_runs]
        total_pass_tokens = sum(pass_toks)
        print()
        print(f"COST — {len(pass_runs)} PASS runs total {total_pass_tokens:,} "
              f"tokens (avg {total_pass_tokens/len(pass_runs):.0f} per PASS, "
              f"p50 {_p(pass_toks, 50):.0f}, p95 {_p(pass_toks, 95):.0f}, "
              f"max {max(pass_toks):.0f})")

    # Overall
    pas = sum(1 for r in runs if r["assert_ok"])
    print()
    print(f"OVERALL: {pas}/{len(runs)} fixtures PASS  "
          f"({100 * pas / max(1, len(runs)):.1f}%)")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="bench.analyze")
    ap.add_argument("--category")
    ap.add_argument("--level", type=int)
    ap.add_argument("--all-runs", action="store_true",
                    help="include every run, not just latest per fixture")
    ap.add_argument("--json", action="store_true",
                    help="emit JSON instead of a human table")
    args = ap.parse_args(argv)

    runs = collect_runs(category=args.category, level=args.level,
                        latest_only=not args.all_runs)
    if args.json:
        # Don't dump huge latency arrays unless requested specifically.
        out = []
        for r in runs:
            r2 = {**r}
            r2["step_latency_p50_ms"] = int(_p(r["step_latency_ms"], 50))
            r2["step_latency_p95_ms"] = int(_p(r["step_latency_ms"], 95))
            r2.pop("step_latency_ms", None)
            out.append(r2)
        json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0

    print_table(runs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
