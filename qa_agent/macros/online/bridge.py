"""Bridge: AgentFSM transitions → MacroFSM ACTION_SEEN events.

Per fsm.guide.md §R2 / §5.1: a bridge is a thin proxy that translates
parent state changes into a single child event per relevant trigger.
No business-logic if-trees — only "is this the trigger transition?"
guards and a single `child.send(...)`.

Trigger here: parent transitioned `THINKING → DISPATCHING` on event
`LLM_REPLIED`. That's the moment after `act_classify` ran and
populated `parent_ctx.action` / `.args` / `.snapshot` — the agent's
parsed action is settled and observable.

Vocabulary mapping is delegated to `vocab_from_agent_ctx` in
qa_agent.macros.online.vocab — same classifier logic the miner uses
in its vocabulary.py and the body-derivation in tagged_pattern.py
uses, so all three see the same alphabet.
"""

from __future__ import annotations

from typing import Any, Callable

from ...runtime.states import AgentEvent, AgentState
from .ctx import MacroCtx
from .states import MacroEvent
from .vocab import vocab_from_agent_ctx


def make_macro_bridge(
    macro_send: Callable[[MacroEvent], Any],
    macro_ctx: MacroCtx,
    parent_ctx: Any,
) -> Callable[[Any, Any, Any], None]:
    """Return a listener compatible with FSM.on_transition.

    Two parent triggers, one event each (R2 — single send per source):

    1. SNAPSHOTTING → THINKING on event SNAPSHOT_READY
       Page just got a fresh snapshot, LLM is about to think.
       Fires `PAGE_READY` so the detector can pre-empt the LLM
       with a precondition-matched macro before `act_think` runs.
       Cheaper than action-driven matching: replaces full chunks
       of LLM turns instead of confirming after the fact.

    2. THINKING → DISPATCHING on event LLM_REPLIED
       LLM emitted an action; act_classify ran. Fires `ACTION_SEEN`
       so the action-stream Aho-Corasick can advance and detect
       co-occurring patterns mid-run. Useful for suggesting macros
       to the agent for the *rest* of the current run.
    """
    def _listener(from_state: Any, to_state: Any, event: Any) -> None:
        # Page-driven pre-emption — fires just before `act_think`.
        if (event is AgentEvent.SNAPSHOT_READY
                and to_state is AgentState.THINKING):
            macro_send(MacroEvent.PAGE_READY)
            return

        # Action-stream detection — fires just after `act_classify`.
        if (event is AgentEvent.LLM_REPLIED
                and to_state is AgentState.DISPATCHING):
            tok = vocab_from_agent_ctx(parent_ctx)
            if tok is None:
                return
            macro_ctx.pending_event_data = tok
            macro_send(MacroEvent.ACTION_SEEN)
            return

    return _listener
