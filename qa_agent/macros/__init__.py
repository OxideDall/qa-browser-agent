"""Macro library — learned (or hand-written) reusable skills compiled
to tagged DSL.

A macro is a directory under `~/.config/qa_agent/macros/<name>/` with:

  * `macro.tagged.txt` — body in tagged-DSL with `${param}` placeholders
  * `meta.json` — schema (name, version, description, params,
                  preconditions, support_count, success_rate,
                  learned_from_runs)

Two execution paths:

  * Standalone via CLI / MCP: `python -m qa_agent --macro <name>
    --param query="..."` → spins up a browser, navigates to the
    macro's URL precondition, replays via `run_tagged_task`.
  * Inline from the tagged DSL: `macro <name> param=value` verb
    inside another tagged steps file → resolves the macro, substitutes
    params, dispatches each compiled step through `execute_step` on
    the existing page (no new browser).

Public API:
  * `load_macro(name, root=None)`        — Macro dataclass
  * `list_macros(root=None)`             — list[dict] for browsing
  * `compile_macro(macro, params)`       — substituted tagged body
  * `MACROS_DIR`                         — default user storage path
  * `MacroNotFound`, `MacroParamError`   — typed exceptions
"""

from __future__ import annotations

from .compile import compile_macro
from .library import (
    MACROS_DIR,
    Macro,
    MacroNotFound,
    MacroParamError,
    ParamSpec,
    list_macros,
    load_macro,
)

__all__ = [
    "MACROS_DIR",
    "Macro",
    "MacroNotFound",
    "MacroParamError",
    "ParamSpec",
    "compile_macro",
    "list_macros",
    "load_macro",
]
