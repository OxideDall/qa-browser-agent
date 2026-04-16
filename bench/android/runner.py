"""Android bench runner — parallel to bench.runner for on-device fixtures.

Fixture layout:

  bench/android/fixtures/<id>/
    config.toml              # [fixture] id/category/level/title
                             # [android] package / serial (optional)
                             # [budget] max_steps / max_tokens / max_wall_seconds
    task.txt                 # natural-language task for the agent
    assert.py                # def check(run_log) -> (ok, msg)    — OR
    assert.json              # {"checks": [{"type": "...", ...}]}

Only a subset of browser-side assert types is meaningful on Android —
`agent_status`, `hierarchy_contains`, `current_package`, `regex_in_description`.
The before_close hook receives (device, None) instead of (page, context).

Usage:
  python -m bench.android.runner <fixture_id>
  python -m bench.android.runner --all
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import time
import tomllib
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from qa_agent.agent import run_android_task  # noqa: E402

FIXTURES_ROOT = Path(__file__).resolve().parent / "fixtures"


# ---------------------------------------------------------------------------
# Loader — minimal fixture model.
# ---------------------------------------------------------------------------

@dataclass
class Budget:
    max_steps: int = 30
    max_tokens: int = 60_000
    max_wall_seconds: float = 240.0
    retries: int = 1


@dataclass
class AndroidSpec:
    package: str | None = None
    serial: str | None = None


@dataclass
class Fixture:
    fixture_id: str
    category: str
    level: int
    title: str
    task: str
    android: AndroidSpec
    budget: Budget
    declarative_assert: dict | None
    programmatic_assert: Callable[[dict], tuple[bool, str]] | None
    fixture_dir: Path


def _load_assert_py(path: Path) -> Callable[[dict], tuple[bool, str]]:
    spec = importlib.util.spec_from_file_location(
        f"_android_assert_{path.parent.name}", path,
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load assert module from {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    check = getattr(mod, "check", None)
    if not callable(check):
        raise AttributeError(f"{path} must define check(run_log) -> (ok, msg)")
    return check


def load_fixture(fixture_id: str) -> Fixture:
    fix_dir = FIXTURES_ROOT / fixture_id
    if not fix_dir.is_dir():
        raise FileNotFoundError(f"android fixture '{fixture_id}' not found under {FIXTURES_ROOT}")

    with (fix_dir / "config.toml").open("rb") as f:
        cfg = tomllib.load(f)
    fcfg = cfg.get("fixture", {})
    acfg = cfg.get("android", {})
    bcfg = cfg.get("budget", {})

    task = (fix_dir / "task.txt").read_text().strip()

    declarative = None
    programmatic = None
    if (fix_dir / "assert.py").exists():
        programmatic = _load_assert_py(fix_dir / "assert.py")
    elif (fix_dir / "assert.json").exists():
        declarative = json.loads((fix_dir / "assert.json").read_text())
    else:
        raise FileNotFoundError(f"{fix_dir} needs either assert.py or assert.json")

    return Fixture(
        fixture_id=fcfg.get("id", fixture_id),
        category=fcfg.get("category", "android"),
        level=int(fcfg.get("level", 1)),
        title=fcfg.get("title", fixture_id),
        task=task,
        android=AndroidSpec(
            package=acfg.get("package"),
            serial=acfg.get("serial"),
        ),
        budget=Budget(
            max_steps=int(bcfg.get("max_steps", 30)),
            max_tokens=int(bcfg.get("max_tokens", 60_000)),
            max_wall_seconds=float(bcfg.get("max_wall_seconds", 240.0)),
            retries=int(bcfg.get("retries", 1)),
        ),
        declarative_assert=declarative,
        programmatic_assert=programmatic,
        fixture_dir=fix_dir,
    )


def discover_fixtures() -> list[str]:
    if not FIXTURES_ROOT.exists():
        return []
    out = []
    for d in sorted(FIXTURES_ROOT.iterdir()):
        if d.is_dir() and (d / "config.toml").exists():
            out.append(d.name)
    return out


# ---------------------------------------------------------------------------
# Recorder — writes a JSONL trace next to browser bench, under
# bench/android/runs/<fixture-id>_<ts>.jsonl so we don't collide.
# ---------------------------------------------------------------------------

RUNS_DIR = Path(__file__).resolve().parent / "runs"


class Recorder:
    def __init__(self, fixture_id: str):
        RUNS_DIR.mkdir(parents=True, exist_ok=True)
        ts = int(time.time())
        self.path = RUNS_DIR / f"{fixture_id}_{ts}.jsonl"
        self._fh = self.path.open("w")
        self.steps: list[dict] = []
        self.result: dict | None = None

    def write(self, rec: dict) -> None:
        self._fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self._fh.flush()

    def on_step(self, step: dict) -> None:
        self.steps.append(step)
        self.write({"t": "step", **step})

    def on_finish(self, summary: dict) -> None:
        self.result = summary
        self.write(summary)

    def write_assert(self, ok: bool, msg: str, extra: dict | None = None) -> None:
        rec = {"t": "assert", "ok": ok, "msg": msg}
        if extra:
            rec.update(extra)
        self.write(rec)

    def close(self) -> None:
        try:
            self._fh.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Asserts — declarative for Android (subset of browser's asserts).
# ---------------------------------------------------------------------------

def _eval_check(check: dict, device: Any, agent_status: str,
                description: str) -> tuple[bool, str]:
    t = check.get("type")
    try:
        if t == "agent_status":
            expected = check["expected"]
            ok = agent_status == expected
            return ok, f"agent_status got={agent_status!r} expected={expected!r}"

        if t == "hierarchy_contains":
            needle = check["value"]
            xml = device.dump_hierarchy(compressed=True, pretty=False)
            ok = needle in xml
            return ok, f"hierarchy_contains {needle!r} — {'found' if ok else 'missing'}"

        if t == "current_package":
            expected = check["expected"]
            cur = (device.app_current() or {}).get("package", "")
            ok = cur == expected
            return ok, f"current_package got={cur!r} expected={expected!r}"

        if t == "regex_in_description":
            pat = check["pattern"]
            flags = re.IGNORECASE if check.get("ignore_case") else 0
            ok = bool(re.search(pat, description, flags))
            return ok, f"regex {pat!r} on description — {'match' if ok else 'no match'}"

        return False, f"unknown android check type: {t!r}"
    except Exception as e:
        return False, f"check {t!r} crashed: {type(e).__name__}: {e}"


def evaluate_declarative(spec: dict, device: Any, agent_status: str,
                         description: str) -> tuple[bool, str, list[dict]]:
    checks = spec.get("checks", [])
    if not checks:
        return False, "no checks defined", []
    details: list[dict] = []
    overall_ok = True
    first_fail = ""
    for c in checks:
        ok, msg = _eval_check(c, device, agent_status, description)
        details.append({"check": c, "ok": ok, "msg": msg})
        if not ok and overall_ok:
            overall_ok = False
            first_fail = msg
    return overall_ok, first_fail or "all checks passed", details


# ---------------------------------------------------------------------------
# Runner entry.
# ---------------------------------------------------------------------------

def run_one(fixture_id: str, *, verbose: bool = True) -> dict:
    fixture = load_fixture(fixture_id)
    rec = Recorder(fixture_id)
    rec.write({
        "t": "start",
        "fixture_id": fixture_id,
        "category": fixture.category,
        "level": fixture.level,
        "title": fixture.title,
        "package": fixture.android.package,
        "serial": fixture.android.serial,
    })

    overall_ok = False
    first_fail = "did not run"
    assert_details: list[dict] = []
    error: str | None = None
    status = "ERROR"
    description = ""

    captured: dict = {}

    def _before_close(device, _unused):
        # rec.result was populated by on_finish just before this hook ran;
        # the outer `description` variable is still "" until
        # run_android_task returns.
        agent_status = (rec.result or {}).get("status", "ERROR")
        live_desc = (rec.result or {}).get("description", "")
        if fixture.declarative_assert is not None:
            ok, msg, details = evaluate_declarative(
                fixture.declarative_assert, device, agent_status, live_desc,
            )
            captured["assert"] = (ok, msg, details)

    retries = max(1, fixture.budget.retries)
    for attempt in range(1, retries + 1):
        if retries > 1:
            rec.write({"t": "attempt", "n": attempt, "of": retries})
            if attempt > 1:
                captured.pop("assert", None)
                print(f"[android] {fixture_id}: retry {attempt}/{retries} (last: {first_fail})")
                time.sleep(min(10.0, 3.0 * (attempt - 1)))

        t0 = time.time()
        try:
            status, description, _steps = run_android_task(
                task=fixture.task,
                package=fixture.android.package,
                serial=fixture.android.serial,
                verbose=verbose,
                max_steps=fixture.budget.max_steps,
                on_step=rec.on_step,
                on_finish=rec.on_finish,
                before_close=_before_close,
            )
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
            rec.write({"t": "error", "stage": "run_android_task",
                       "attempt": attempt, "msg": error,
                       "trace": traceback.format_exc()})

        wall = time.time() - t0

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
                first_fail = f"assert.py crashed: {type(e).__name__}: {e}"
                rec.write_assert(False, first_fail, {"trace": traceback.format_exc()})
        elif "assert" in captured:
            ok, msg, details = captured["assert"]
            overall_ok = ok
            first_fail = msg
            assert_details = details
            rec.write_assert(ok, msg, {"checks": details})
        else:
            overall_ok = False
            first_fail = "no assert evaluated (agent likely crashed before before_close)"
            rec.write_assert(False, first_fail)

        if overall_ok:
            break

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
    flag = "PASS" if overall_ok else ("FAIL" if status != "ERROR" else "ERROR")
    print()
    print(f"[android] {fixture_id}: {flag} — {first_fail}")
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="bench.android.runner")
    ap.add_argument("fixture_id", nargs="?")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    if args.fixture_id:
        s = run_one(args.fixture_id, verbose=args.verbose)
        return 0 if s["assert_ok"] else 1

    if args.all:
        ids = discover_fixtures()
        if not ids:
            print("[android] no fixtures found", file=sys.stderr)
            return 2
        summaries = [run_one(fid, verbose=args.verbose) for fid in ids]
        passed = sum(1 for s in summaries if s["assert_ok"])
        print()
        print(f"[android] {passed}/{len(summaries)} fixtures PASS")
        return 0 if passed == len(summaries) else 1

    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
