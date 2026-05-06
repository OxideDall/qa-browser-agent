"""MacroFSM transition table.

Per fsm.guide.md §R4 / R6: the table is the source of truth for "what
happens on (state, event)", and only live rows get listed. Three live
rows total for this FSM:

  IDLE      ─STARTED→      [act_start, SCANNING]
  SCANNING  ─ACTION_SEEN→  [act_on_action, SCANNING]
  SCANNING  ─DISABLE→      [act_disable, DISABLED]

Missing cells (e.g. ACTION_SEEN in IDLE — bridge fires before STARTED)
are intentional no-ops: the dispatcher just returns. DISABLED is a
terminal sink (R6) — its row stays empty so any post-disable bridge
events drop on the floor.
"""

from __future__ import annotations

from typing import Any

from .actions import act_disable, act_on_action, act_start
from .states import MacroEvent, MacroState


Entry = Any


MACRO_TRANSITIONS: dict[MacroState, dict[MacroEvent, Entry]] = {
    MacroState.IDLE: {
        MacroEvent.STARTED: (act_start, MacroState.SCANNING, MacroState.DISABLED),
    },
    MacroState.SCANNING: {
        MacroEvent.ACTION_SEEN: (act_on_action, MacroState.SCANNING, MacroState.SCANNING),
        MacroEvent.DISABLE: (act_disable, MacroState.DISABLED, MacroState.DISABLED),
    },
    MacroState.DISABLED: {},
}
