"""Enumerations of the AgentFSM states + events.

Kept separate from the transition table so tests / tooling / bridges
can import the enums without importing the actions (which depend on
Playwright, LLM, etc.).

Originally derived from bench/fsm_design.md, but Phase 3c flattened
several design-time states (VISIONING, POPUP_LOCKED, REASKING_DONE)
into inline branches within their associated `act_*` functions. The
enum here reflects what the runtime table actually uses; see
AGENT_TRANSITIONS in transitions.py for the live transitions.
"""

from __future__ import annotations

from enum import Enum


class AgentState(Enum):
    """Root AgentFSM states — only those actually handled by the table."""

    IDLE            = "IDLE"            # initial
    SNAPSHOTTING    = "SNAPSHOTTING"    # extract_elements → ctx.snapshot
    THINKING        = "THINKING"        # ask_llm → ctx.resp_text
    DISPATCHING     = "DISPATCHING"     # parse_action → emit PARSED_*
    LOOP_CHECK      = "LOOP_CHECK"      # classify prev_actions → emit LOOP_*
    MM_GUARD_CHECK  = "MM_GUARD_CHECK"  # popup lock vs action tuple
    EXECUTING       = "EXECUTING"       # execute_action + post-exec checks

    # Terminals
    DONE_PASS       = "DONE_PASS"
    DONE_FAIL       = "DONE_FAIL"
    ERROR           = "ERROR"


TERMINAL_STATES: frozenset[AgentState] = frozenset({
    AgentState.DONE_PASS,
    AgentState.DONE_FAIL,
    AgentState.ERROR,
})


class AgentEvent(Enum):
    """Root AgentFSM events. Emitted only by send() (R7).

    Only events actually handled by AGENT_TRANSITIONS live here.
    """

    # Lifecycle
    START               = "START"

    # Snapshot
    SNAPSHOT_READY      = "SNAPSHOT_READY"

    # LLM reply
    LLM_REPLIED         = "LLM_REPLIED"

    # Action classification (after parse_action)
    PARSED_DONE_PASS    = "PARSED_DONE_PASS"
    PARSED_DONE_FAIL    = "PARSED_DONE_FAIL"
    PARSED_LOOK         = "PARSED_LOOK"
    PARSED_TAB          = "PARSED_TAB"
    PARSED_ERROR        = "PARSED_ERROR"
    PARSED_NORMAL       = "PARSED_NORMAL"

    # Loop detection
    HARD_LOOP           = "HARD_LOOP"
    SOFT_LOOP           = "SOFT_LOOP"
    NO_LOOP             = "NO_LOOP"

    # MM popup guard
    MM_BLOCKED          = "MM_BLOCKED"
    MM_NOT_BLOCKED      = "MM_NOT_BLOCKED"

    # Evidence gate
    EVIDENCE_OK         = "EVIDENCE_OK"
    EVIDENCE_MISS       = "EVIDENCE_MISS"
    REASKS_EXHAUSTED    = "REASKS_EXHAUSTED"
