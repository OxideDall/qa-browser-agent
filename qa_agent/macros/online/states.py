"""MacroFSM enums.

Tiny state machine on purpose — the bulk of the work happens in
side-effect-only actions. Three states, three events:

  IDLE       — initial, before STARTED arrives
  SCANNING   — main mode, listening on bridge events
  DISABLED   — kill-switched (QA_DISABLE_MACRO_DETECT=1 was seen at
               start, OR a runtime DISABLE event arrived); no-op'd
               for the rest of the run

Per fsm.guide.md §0 the lower bound for FSM-worthy is 3 states / 3
events — we hit that exactly. The justification for keeping it FSM-
shaped rather than a hand-rolled if-tree:
  * extensibility (suggest vs auto-invoke modes can grow into
    AWAITING_DECISION later if the policy expands)
  * R5 nesting model (parent FSM bridges via a child state; even
    minimal child needs a state to bridge to)
  * audit-friendly (`MacroState.SCANNING` shows up cleanly in step
    records vs. an undocumented boolean flag)
"""

from __future__ import annotations

from enum import Enum


class MacroState(Enum):
    IDLE = "IDLE"
    SCANNING = "SCANNING"
    DISABLED = "DISABLED"


class MacroEvent(Enum):
    STARTED = "STARTED"
    ACTION_SEEN = "ACTION_SEEN"
    PAGE_READY = "PAGE_READY"
    DISABLE = "DISABLE"
