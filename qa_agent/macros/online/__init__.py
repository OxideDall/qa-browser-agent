"""Online macro detection — child FSM that watches the live agent
action stream and surfaces / auto-invokes installed macros when a
prefix match meets all preconditions.

Public API:
  * `MacroManager(parent_fsm, parent_ctx)`   — orchestrates load,
    spawn, bridge wiring. One per AgentFSM instance.
  * `MacroState`, `MacroEvent`               — FSM enums (see states.py)

Per fsm.guide.md §5: spawned from a parent action; bridge listens on
parent transitions and pushes a single ACTION_SEEN event per parsed
agent action; child has its own queue and ticks independently.
"""

from __future__ import annotations

from .aho import AhoCorasick, AhoMatch
from .ctx import MacroCtx
from .manager import MacroManager
from .states import MacroEvent, MacroState

__all__ = [
    "AhoCorasick",
    "AhoMatch",
    "MacroCtx",
    "MacroEvent",
    "MacroState",
    "MacroManager",
]
