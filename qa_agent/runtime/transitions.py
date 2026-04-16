"""AGENT_TRANSITIONS — the root FSM's transition table.

Shape: dict[AgentState, dict[AgentEvent, Entry]]. Entries are either:

  (action, ok_state, err_state)    -- Form B, the usual case
  (action, next_state)             -- Form A, rarely used
  next_state                        -- Form C, terminals / onEnter-style

Per fsm.guide.md §R6: only live rows live in the table. Missing cells
are intentional no-ops — events arriving in states that don't handle
them are dropped silently.

Every action is in qa_agent.runtime.fsm_actions. All actions on the
happy path emit their follow-up event via ctx.send_event; actions
leading into a terminal state don't need to emit — the state row is
empty and the dispatcher naturally stops.
"""

from __future__ import annotations

from typing import Any

from .fsm_actions import (
    act_append_blocked_nudge, act_classify, act_emit_done_fail_direct,
    act_emit_done_forced_fail, act_emit_done_pass, act_emit_hard_fail,
    act_evidence_gate, act_exec, act_loop_check, act_mm_guard,
    act_new_step, act_nudge_invalid, act_reask_done, act_switch_tab,
    act_think, act_vision_forced, act_vision_look,
)
from .states import AgentEvent as E, AgentState as S


# Shorthand alias.
Entry = Any


AGENT_TRANSITIONS: dict[S, dict[E, Entry]] = {
    # ---- IDLE ------------------------------------------------------------
    S.IDLE: {
        E.START: (act_new_step, S.SNAPSHOTTING, S.ERROR),
    },

    # ---- SNAPSHOTTING: ready to ask the LLM ------------------------------
    # Most of the reask / skip / nudge actions set ok_state=SNAPSHOTTING
    # and emit START, so SNAPSHOTTING needs a START handler that runs
    # act_new_step (budget check + step++ + fresh snapshot).
    S.SNAPSHOTTING: {
        E.START: (act_new_step, S.SNAPSHOTTING, S.ERROR),
        E.SNAPSHOT_READY: (act_think, S.THINKING, S.ERROR),
    },

    # ---- THINKING: LLM just replied, classify the action -----------------
    S.THINKING: {
        E.LLM_REPLIED: (act_classify, S.DISPATCHING, S.ERROR),
    },

    # ---- DISPATCHING: fork by action kind --------------------------------
    S.DISPATCHING: {
        # done PASS → evidence gate → self (stays in DISPATCHING) → fork.
        E.PARSED_DONE_PASS: (act_evidence_gate, S.DISPATCHING, S.ERROR),
        E.EVIDENCE_OK:      (act_emit_done_pass, S.DONE_PASS, S.DONE_PASS),
        E.EVIDENCE_MISS:    (act_reask_done, S.SNAPSHOTTING, S.ERROR),
        E.REASKS_EXHAUSTED: (act_emit_done_forced_fail, S.DONE_FAIL, S.DONE_FAIL),

        # done FAIL — agent aborted, always accepted.
        E.PARSED_DONE_FAIL: (act_emit_done_fail_direct, S.DONE_FAIL, S.DONE_FAIL),

        # look → vision re-dispatch → back to DISPATCHING via PARSED_*.
        E.PARSED_LOOK: (act_vision_look, S.DISPATCHING, S.ERROR),

        # tab → switch focus + next step.
        E.PARSED_TAB: (act_switch_tab, S.SNAPSHOTTING, S.ERROR),

        # parse error → nudge + next step.
        E.PARSED_ERROR: (act_nudge_invalid, S.SNAPSHOTTING, S.ERROR),

        # normal action → loop check first.
        E.PARSED_NORMAL: (act_loop_check, S.LOOP_CHECK, S.ERROR),
    },

    # ---- LOOP_CHECK: classify repetition ---------------------------------
    S.LOOP_CHECK: {
        E.HARD_LOOP: (act_emit_hard_fail, S.DONE_FAIL, S.DONE_FAIL),
        E.SOFT_LOOP: (act_vision_forced, S.DISPATCHING, S.ERROR),
        E.NO_LOOP:   (act_mm_guard, S.MM_GUARD_CHECK, S.ERROR),
    },

    # ---- MM_GUARD_CHECK: escape-guard vs popup ---------------------------
    S.MM_GUARD_CHECK: {
        E.MM_BLOCKED:     (act_append_blocked_nudge, S.SNAPSHOTTING, S.ERROR),
        E.MM_NOT_BLOCKED: (act_exec, S.EXECUTING, S.ERROR),
    },

    # ---- EXECUTING: after execute_action ---------------------------------
    S.EXECUTING: {
        E.START: (act_new_step, S.SNAPSHOTTING, S.ERROR),
    },

    # Terminals are R6 Form-C destinations: empty rows.
    S.DONE_PASS: {},
    S.DONE_FAIL: {},
    S.ERROR:     {},
}
