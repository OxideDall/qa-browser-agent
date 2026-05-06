"""Fixture loader: reads a fixture directory into a structured Fixture object."""

from __future__ import annotations

import importlib.util
import json
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

FIXTURES_ROOT = Path(__file__).resolve().parents[1] / "fixtures"


@dataclass
class Budget:
    max_steps: int = 30
    max_tokens: int = 20_000
    max_wall_seconds: float = 120.0
    # Number of attempts before declaring FAIL. 1 = no retry.
    # Live-net fixtures (WB / DDG / Wikipedia) that flake on UI rotation
    # should bump this to 2 or 3 in their config.toml [budget] section.
    retries: int = 1


@dataclass
class NetworkSpec:
    chain_id: int | None = None
    rpc: str = "default"
    required_balance_eth: float = 0.0


@dataclass
class Fixture:
    fixture_id: str
    category: str
    level: int
    title: str
    task: str
    url: str | None
    headless: bool
    extensions: list[str]
    init_script_src: str | None
    site_dir: Path | None
    budget: Budget
    network: NetworkSpec | None
    declarative_assert: dict[str, Any] | None
    programmatic_assert: Callable[[dict], tuple[bool, str]] | None
    fixture_dir: Path
    # If set, runner uses qa_agent.run_tagged_task instead of the
    # natural-language run_task. Sourced from `task.tagged.txt` (if
    # present) or [run].tagged in config.toml. Mutually exclusive
    # with the natural-language `task` for the run path — the LLM-only
    # `task` field still gets populated for logging / discoverability.
    tagged_steps: str | None = None
    # Fixture-local macros directory. If `<fixture>/macros/` exists,
    # the runner sets QA_MACROS_DIR to it for the duration of the run
    # — both the tagged DSL `macro` verb and the online MacroFSM
    # detector see only this fixture's macros, sandboxed from the
    # operator's user-level installation.
    macros_dir: Path | None = None


def _load_assert_py(path: Path) -> Callable[[dict], tuple[bool, str]]:
    """Import assert.py and return its check(run_log) -> (ok, msg) function."""
    spec = importlib.util.spec_from_file_location(
        f"_bench_assert_{path.parent.name}", path
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load assert module from {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    check = getattr(mod, "check", None)
    if not callable(check):
        raise AttributeError(f"{path} must define a callable `check(run_log)`")
    return check


def load_fixture(fixture_id: str) -> Fixture:
    """Resolve `<category>_<level>_<rest>` -> fixtures/<category>/<id>/."""
    matches = list(FIXTURES_ROOT.glob(f"*/{fixture_id}"))
    if not matches:
        raise FileNotFoundError(
            f"fixture '{fixture_id}' not found under {FIXTURES_ROOT}"
        )
    if len(matches) > 1:
        raise RuntimeError(
            f"fixture id '{fixture_id}' is ambiguous: {matches}"
        )
    fixture_dir = matches[0]

    cfg_path = fixture_dir / "config.toml"
    if not cfg_path.exists():
        raise FileNotFoundError(f"missing config.toml in {fixture_dir}")
    with cfg_path.open("rb") as f:
        cfg = tomllib.load(f)

    fcfg = cfg.get("fixture", {})
    rcfg = cfg.get("run", {})
    bcfg = cfg.get("budget", {})
    ncfg = cfg.get("network", None)

    # Tagged-DSL fixture detection. Either `task.tagged.txt` lives next
    # to (or instead of) task.txt, or [run].tagged points at a path
    # relative to the fixture dir. task.txt is still required for
    # logging / human-readable summaries.
    tagged_steps: str | None = None
    tagged_default = fixture_dir / "task.tagged.txt"
    tagged_cfg = rcfg.get("tagged")
    if tagged_cfg:
        tagged_path = fixture_dir / tagged_cfg
        if not tagged_path.exists():
            raise FileNotFoundError(
                f"[run].tagged points at {tagged_path}, not found"
            )
        tagged_steps = tagged_path.read_text()
    elif tagged_default.exists():
        tagged_steps = tagged_default.read_text()

    task_path = fixture_dir / "task.txt"
    if not task_path.exists() and tagged_steps is None:
        raise FileNotFoundError(
            f"{fixture_dir}: needs task.txt or task.tagged.txt"
        )
    task = task_path.read_text().strip() if task_path.exists() else (
        f"tagged: {tagged_steps[:80].strip()}"
    )

    init_src: str | None = None
    init_name = rcfg.get("init_script")
    if init_name:
        init_path = fixture_dir / init_name
        if not init_path.exists():
            raise FileNotFoundError(f"init_script {init_path} not found")
        init_src = init_path.read_text()

    site_dir = fixture_dir / "site"
    if not site_dir.is_dir():
        site_dir = None

    macros_dir = fixture_dir / "macros"
    if not macros_dir.is_dir():
        macros_dir = None

    declarative: dict[str, Any] | None = None
    programmatic: Callable[[dict], tuple[bool, str]] | None = None
    if (fixture_dir / "assert.py").exists():
        programmatic = _load_assert_py(fixture_dir / "assert.py")
    elif (fixture_dir / "assert.json").exists():
        declarative = json.loads((fixture_dir / "assert.json").read_text())
    else:
        raise FileNotFoundError(
            f"{fixture_dir} needs either assert.py or assert.json"
        )

    network: NetworkSpec | None = None
    if ncfg is not None:
        network = NetworkSpec(
            chain_id=ncfg.get("chain_id"),
            rpc=ncfg.get("rpc", "default"),
            required_balance_eth=float(ncfg.get("required_balance_eth", 0.0)),
        )

    return Fixture(
        fixture_id=fcfg.get("id", fixture_id),
        category=fcfg.get("category", fixture_dir.parent.name),
        level=int(fcfg.get("level", 1)),
        title=fcfg.get("title", fixture_id),
        task=task,
        url=rcfg.get("url"),
        headless=bool(rcfg.get("headless", True)),
        extensions=list(rcfg.get("extensions", [])),
        init_script_src=init_src,
        site_dir=site_dir,
        budget=Budget(
            max_steps=int(bcfg.get("max_steps", rcfg.get("max_steps", 30))),
            max_tokens=int(bcfg.get("max_tokens", 20_000)),
            max_wall_seconds=float(bcfg.get("max_wall_seconds", 120.0)),
            retries=int(bcfg.get("retries", 1)),
        ),
        network=network,
        declarative_assert=declarative,
        programmatic_assert=programmatic,
        fixture_dir=fixture_dir,
        tagged_steps=tagged_steps,
        macros_dir=macros_dir,
    )


def discover_fixtures(
    category: str | None = None, level: int | None = None
) -> list[str]:
    """List all fixture IDs, optionally filtered by category and/or level."""
    out: list[str] = []
    for cat_dir in sorted(FIXTURES_ROOT.iterdir()):
        if not cat_dir.is_dir():
            continue
        if category and cat_dir.name != category:
            continue
        for fix_dir in sorted(cat_dir.iterdir()):
            if not fix_dir.is_dir():
                continue
            if not (fix_dir / "config.toml").exists():
                continue
            if level is not None:
                with (fix_dir / "config.toml").open("rb") as f:
                    cfg = tomllib.load(f)
                if int(cfg.get("fixture", {}).get("level", 0)) != level:
                    continue
            out.append(fix_dir.name)
    return out
