"""Bench runner — single-fixture or full-suite execution.

Usage:
    python -m bench.runner <fixture_id>
    python -m bench.runner --all
    python -m bench.runner --category static_ui
    python -m bench.runner --level 1
"""

from __future__ import annotations

import argparse
import contextlib
import sys
import time
import traceback
from pathlib import Path
from typing import Iterator

# Make qa_agent importable when bench is run from project root.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from qa_agent.agent import run_task  # noqa: E402
from qa_agent.config import METAMASK_EXT  # noqa: E402

from . import asserts as decl_assert  # noqa: E402
from .loader import Fixture, discover_fixtures, load_fixture  # noqa: E402
from .recorder import Recorder  # noqa: E402
from .server import serve  # noqa: E402

# Dedicated browser profile for web3 fixtures — has MM with BENCH_SEED.
BENCH_PROFILE = Path.home() / ".config" / "qa_agent" / "bench_profile"


@contextlib.contextmanager
def _maybe_serve(fixture: Fixture) -> Iterator[str | None]:
    """Yield a base URL if the fixture has a `site/` dir, else None."""
    if fixture.site_dir is None:
        yield None
        return
    with serve(fixture.site_dir) as srv:
        yield srv.base_url


def _resolve_url(fixture: Fixture, base_url: str | None) -> str | None:
    """Resolve fixture URL: replace `{base}` placeholder with the served URL."""
    url = fixture.url
    if not url:
        return base_url  # default to base URL if no explicit url
    if base_url and "{base}" in url:
        return url.replace("{base}", base_url.rstrip("/"))
    return url


def run_one(fixture_id: str, *, headless: bool | None = None,
            verbose: bool = True, skip_if_underfunded: bool = True) -> dict:
    """Run a single fixture end-to-end. Returns a summary dict.

    If the fixture declares a web3 `[network]` with `required_balance_eth > 0`
    and the bench wallet is underfunded on that chain, the run is SKIPPED
    (marked with `skipped=True`) unless `skip_if_underfunded=False`.
    """
    fixture = load_fixture(fixture_id)
    rec = Recorder(fixture_id)
    rec.write({
        "t": "start",
        "fixture_id": fixture_id,
        "category": fixture.category,
        "level": fixture.level,
        "title": fixture.title,
    })

    # Web3 funding pre-check.
    if (skip_if_underfunded and fixture.network is not None
            and fixture.network.required_balance_eth > 0):
        try:
            from .web3_assert import native_balance_eth, NAMES
            bal = native_balance_eth(fixture.network.chain_id)
            need = fixture.network.required_balance_eth
            if bal < need:
                cname = NAMES.get(fixture.network.chain_id,
                                  str(fixture.network.chain_id))
                skip_msg = (
                    f"underfunded on {cname}: have {bal:.4f} ETH, "
                    f"need {need:.4f}"
                )
                rec.write({"t": "skip", "reason": skip_msg})
                rec.close()
                print(f"[bench] {fixture_id}: SKIP — {skip_msg}")
                return {
                    "fixture_id": fixture_id,
                    "category": fixture.category,
                    "level": fixture.level,
                    "agent_status": "SKIP",
                    "agent_description": skip_msg,
                    "assert_ok": None,
                    "assert_msg": skip_msg,
                    "assert_details": [],
                    "error": None,
                    "log_path": str(rec.path),
                    "skipped": True,
                }
        except Exception as e:
            # Balance RPC hiccup — don't block the run, just note it.
            rec.write({"t": "note",
                       "msg": f"pre-flight balance check failed: {e}"})

    overall_ok = False
    first_fail = "did not run"
    assert_details: list[dict] = []
    error: str | None = None
    status = "ERROR"
    description = ""

    try:
        with _maybe_serve(fixture) as base_url:
            url = _resolve_url(fixture, base_url)

            captured: dict = {}

            def _before_close(page, context):
                # on_finish has already populated rec.result with the agent's
                # status — use it for asserts that need to know PASS vs FAIL.
                agent_status = (rec.result or {}).get("status", "ERROR")
                if fixture.declarative_assert is not None:
                    ok, msg, details = decl_assert.evaluate(
                        fixture.declarative_assert, page, context,
                        agent_status=agent_status,
                    )
                    captured["assert"] = (ok, msg, details)

            # Resolve extensions: "metamask" -> real path from config.
            ext_paths: list[str] = []
            for name in fixture.extensions:
                if name in ("metamask", "mm"):
                    ext_paths.append(str(METAMASK_EXT))
                else:
                    ext_paths.append(name)

            # Web3 fixtures run in the dedicated bench_profile with pre-seeded
            # MM. Non-web3 fixtures leave profile as default (fresh each run).
            profile = BENCH_PROFILE if ext_paths else None

            # Retry loop (flake-resilience). Default retries=1 (no retry);
            # live-net fixtures can bump via config.toml [budget].retries.
            retries = max(1, fixture.budget.retries)
            for attempt in range(1, retries + 1):
                if retries > 1:
                    rec.write({"t": "attempt", "n": attempt, "of": retries})
                    if attempt > 1:
                        captured.pop("assert", None)   # forget stale verdict
                        print(f"[bench] {fixture_id}: retry "
                              f"{attempt}/{retries} (last: {first_fail})")
                        time.sleep(min(15.0, 3.0 * (attempt - 1)))

                t0 = time.time()
                try:
                    status, description, _steps = run_task(
                        task=fixture.task,
                        url=url,
                        headless=fixture.headless if headless is None else headless,
                        verbose=verbose,
                        max_steps=fixture.budget.max_steps,
                        extensions=ext_paths or None,
                        init_script=fixture.init_script_src,
                        on_step=rec.on_step,
                        on_finish=rec.on_finish,
                        before_close=_before_close,
                        profile_dir=profile,
                    )
                except Exception as e:
                    error = f"{type(e).__name__}: {e}"
                    rec.write({"t": "error", "stage": "run_task",
                               "attempt": attempt, "msg": error,
                               "trace": traceback.format_exc()})

                wall = time.time() - t0

                # Programmatic assert (assert.py) runs against the recorded log
                if fixture.programmatic_assert is not None:
                    try:
                        log = {
                            "fixture_id": fixture_id,
                            "status": status,
                            "description": description,
                            "steps": rec.steps,
                            "wall_seconds": wall,
                            "result": rec.result,
                        }
                        ok, msg = fixture.programmatic_assert(log)
                        overall_ok, first_fail = ok, msg
                        rec.write_assert(ok, msg)
                    except Exception as e:
                        overall_ok = False
                        first_fail = (
                            f"assert.py crashed: {type(e).__name__}: {e}"
                        )
                        rec.write_assert(
                            False, first_fail,
                            {"trace": traceback.format_exc()},
                        )
                elif "assert" in captured:
                    ok, msg, details = captured["assert"]
                    overall_ok = ok
                    first_fail = msg
                    assert_details = details
                    rec.write_assert(ok, msg, {"checks": details})
                else:
                    # No live-page assert ran (e.g. agent crashed before close).
                    overall_ok = False
                    first_fail = "no assert evaluated (agent likely crashed)"
                    rec.write_assert(False, first_fail)

                if overall_ok:
                    break                          # don't retry after PASS
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
        rec.write({"t": "error", "stage": "outer", "msg": error,
                   "trace": traceback.format_exc()})
    finally:
        rec.close()

    summary = {
        "fixture_id": fixture_id,
        "category": fixture.category,
        "level": fixture.level,
        "agent_status": status,
        "agent_description": description,
        "assert_ok": overall_ok,
        "assert_msg": first_fail,
        "assert_details": assert_details,
        "error": error,
        "log_path": str(rec.path),
    }

    print()
    flag = "PASS" if overall_ok else ("FAIL" if status != "ERROR" else "ERROR")
    print(f"[bench] {fixture_id}: {flag} — {first_fail}")
    return summary


def run_many(fixture_ids: list[str], *, headless: bool | None = None,
             verbose: bool = False, fail_fast: bool = False) -> list[dict]:
    summaries = []
    for fid in fixture_ids:
        s = run_one(fid, headless=headless, verbose=verbose)
        summaries.append(s)
        # SKIP fixtures (e.g. underfunded web3) don't count as a fail.
        is_fail = (s.get("assert_ok") is False) and not s.get("skipped")
        if fail_fast and is_fail:
            print()
            print(f"[bench] --fail-fast: stopping after {fid} FAIL "
                  f"({len(summaries)}/{len(fixture_ids)} attempted)")
            break
    pass_count = sum(1 for s in summaries if s.get("assert_ok"))
    print()
    print(f"[bench] {pass_count}/{len(summaries)} fixtures PASS")
    return summaries


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="bench.runner")
    ap.add_argument("fixture_id", nargs="?",
                    help="run a single fixture by id")
    ap.add_argument("--all", action="store_true",
                    help="run every fixture")
    ap.add_argument("--category", help="only this category (e.g. static_ui)")
    ap.add_argument("--level", type=int, help="only this level (1..8)")
    ap.add_argument("--headed", action="store_true",
                    help="show browser (overrides fixture headless setting)")
    ap.add_argument("--fail-fast", action="store_true",
                    help="stop after the first fixture FAIL (skips don't "
                         "count). Useful for CI and bisection.")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    headless = False if args.headed else None

    if args.fixture_id:
        s = run_one(args.fixture_id, headless=headless, verbose=args.verbose)
        return 0 if s["assert_ok"] else 1

    if args.all or args.category or args.level is not None:
        ids = discover_fixtures(category=args.category, level=args.level)
        if not ids:
            print("[bench] no fixtures match the filters", file=sys.stderr)
            return 2
        summaries = run_many(
            ids, headless=headless, verbose=args.verbose,
            fail_fast=args.fail_fast,
        )
        return 0 if all(s["assert_ok"] for s in summaries) else 1

    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
