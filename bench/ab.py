"""A/B prompt harness.

Run the bench suite under two SYSTEM_PROMPT variants and diff the results.

Usage:
    python -m bench.ab promptA.txt promptB.txt
    python -m bench.ab promptA.txt promptB.txt --category static_ui
    python -m bench.ab promptA.txt promptB.txt --fixtures static_l1_confirm,static_l2_register
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import qa_agent.agent as agent_mod  # noqa: E402

from bench.runner.loader import discover_fixtures  # noqa: E402
from bench.runner.runner import run_one  # noqa: E402


def _resolve_fixtures(category: str | None, level: int | None,
                      fixtures: str | None) -> list[str]:
    if fixtures:
        return [f.strip() for f in fixtures.split(",") if f.strip()]
    return discover_fixtures(category=category, level=level)


def _patched_run(prompt_path: Path, fixture_id: str,
                 headless: bool | None, verbose: bool) -> dict:
    saved = agent_mod.SYSTEM_PROMPT
    try:
        agent_mod.SYSTEM_PROMPT = prompt_path.read_text()
        return run_one(fixture_id, headless=headless, verbose=verbose)
    finally:
        agent_mod.SYSTEM_PROMPT = saved


def diff(a: dict, b: dict) -> str:
    """One-line diff label for a fixture: A vs B."""
    if a["assert_ok"] == b["assert_ok"]:
        # Same outcome — show metric drift if substantial.
        return "="
    if a["assert_ok"] and not b["assert_ok"]:
        return "REGRESSION (A pass, B fail)"
    return "IMPROVEMENT (A fail, B pass)"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="bench.ab")
    ap.add_argument("prompt_a", help="path to prompt A text file")
    ap.add_argument("prompt_b", help="path to prompt B text file")
    ap.add_argument("--category")
    ap.add_argument("--level", type=int)
    ap.add_argument("--fixtures",
                    help="comma-separated fixture ids (overrides filters)")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    headless = False if args.headed else None

    pa = Path(args.prompt_a)
    pb = Path(args.prompt_b)
    if not pa.exists() or not pb.exists():
        print(f"prompt files must exist: {pa} {pb}", file=sys.stderr)
        return 2

    ids = _resolve_fixtures(args.category, args.level, args.fixtures)
    if not ids:
        print("no fixtures match", file=sys.stderr)
        return 2

    print(f"\n[ab] A = {pa.name}   B = {pb.name}   fixtures = {len(ids)}")
    print(f"[ab] running {len(ids)} fixtures × 2 variants = {len(ids)*2} runs")

    results: list[tuple[str, dict, dict]] = []
    for fid in ids:
        print(f"\n[ab] {fid} — variant A")
        a = _patched_run(pa, fid, headless, args.verbose)
        print(f"[ab] {fid} — variant B")
        b = _patched_run(pb, fid, headless, args.verbose)
        results.append((fid, a, b))

    print("\n" + "=" * 90)
    print(f"{'fixture':<28}  {'A':>6} {'B':>6} {'Δsteps':>7} {'Δtokens':>9}  diff")
    print("-" * 90)
    a_pass = b_pass = 0
    regr = improv = 0
    for fid, a, b in results:
        if a["assert_ok"]:
            a_pass += 1
        if b["assert_ok"]:
            b_pass += 1
        d = diff(a, b)
        if d.startswith("REGRESSION"):
            regr += 1
        elif d.startswith("IMPROVEMENT"):
            improv += 1
        a_steps_b_steps = (
            _read_steps(a["log_path"]),
            _read_steps(b["log_path"]),
        )
        a_tok = _read_tokens(a["log_path"])
        b_tok = _read_tokens(b["log_path"])
        d_steps = a_steps_b_steps[1] - a_steps_b_steps[0]
        d_tok = b_tok - a_tok
        a_flag = "PASS" if a["assert_ok"] else "FAIL"
        b_flag = "PASS" if b["assert_ok"] else "FAIL"
        print(f"{fid[:28]:<28}  {a_flag:>6} {b_flag:>6} "
              f"{d_steps:>+7} {d_tok:>+9}  {d}")

    print("-" * 90)
    print(f"A: {a_pass}/{len(results)} PASS    B: {b_pass}/{len(results)} PASS")
    print(f"Regressions (A→B): {regr}    Improvements (A→B): {improv}")
    return 0 if regr == 0 and b_pass >= a_pass else 1


def _read_steps(log_path: str) -> int:
    import json
    try:
        for line in reversed(Path(log_path).read_text().splitlines()):
            rec = json.loads(line)
            if rec.get("t") == "result":
                return int(rec.get("steps_used", 0))
    except Exception:
        pass
    return 0


def _read_tokens(log_path: str) -> int:
    import json
    try:
        for line in reversed(Path(log_path).read_text().splitlines()):
            rec = json.loads(line)
            if rec.get("t") == "result":
                return int(rec.get("total_in", 0)) + int(rec.get("total_out", 0))
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
