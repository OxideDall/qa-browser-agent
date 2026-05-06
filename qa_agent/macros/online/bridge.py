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
    """Return a listener compatible with FSM.on_transition. Closes
    over the MacroFSM's send + ctx so it can stash the vocab token
    on the child ctx before triggering ACTION_SEEN."""
    def _listener(from_state: Any, to_state: Any, event: Any) -> None:
        # Single-purpose proxy: only react to act_classify completion.
        if event is not AgentEvent.LLM_REPLIED:
            return
        if to_state is not AgentState.DISPATCHING:
            return
        tok = vocab_from_agent_ctx(parent_ctx)
        if tok is None:
            # Non-mineable verb (look / screenshot / done / tab / macro
            # / parse-error / unknown). Skip without telling the FSM —
            # we're a proxy, not a state-keeping actor.
            return
        # Stash the vocab token where the action will pick it up,
        # then fire the single event. Per R2: data-not-decisions.
        macro_ctx.pending_event_data = tok
        macro_send(MacroEvent.ACTION_SEEN)

    return _listener
