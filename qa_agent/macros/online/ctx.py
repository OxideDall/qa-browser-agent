"""MacroFSM context.

Per fsm.guide.md §R9: ctx is data, not state flags. State lives in
the FSM's `state` field; ctx holds the automaton, the rolling action
buffer, the per-macro cooldown table, and the parent reference for
inject-back (suggestion or auto-invoke).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .aho import AhoCorasick


# Window size for the rolling action buffer. Patterns longer than this
# can't be matched (longest macro should fit). Adjust at MacroManager
# init if needed; default covers most realistic skill lengths.
DEFAULT_BUFFER_LEN = 16

# Per-macro cooldown — minimum number of agent steps between
# consecutive triggers of the *same* macro. Prevents the same
# suggestion from firing every turn while the agent ignores it.
DEFAULT_COOLDOWN_STEPS = 4


@dataclass
class MacroCtx:
    """Lives on the MacroFSM. Mutated by actions; read by listener
    proxies. Not shared with the parent's AgentCtx — bridge passes
    data through dedicated ctx fields rather than aliasing."""

    automaton: AhoCorasick
    aho_state: int = 0                 # current Aho-Corasick state
    pos: int = 0                       # input position counter
    buffer: list[tuple[str, str]] = field(default_factory=list)
    buffer_max: int = DEFAULT_BUFFER_LEN
    cooldown_steps: int = DEFAULT_COOLDOWN_STEPS

    # Last-trigger step number per macro_name. Used for cooldown.
    last_triggered: dict[str, int] = field(default_factory=dict)

    # Macros lookup, populated by MacroManager from library.list_macros.
    # Keyed by macro_name -> Macro object.
    macros: dict[str, Any] = field(default_factory=dict)

    # Mode: "suggest" (inject user-msg into LLM) or "auto" (forcibly
    # swap the next agent action for a macro invocation).
    mode: str = "suggest"

    # Parent reference for inject-back. AgentCtx.pending_diag is the
    # documented channel for "next user message includes this blurb".
    # We don't keep the parent FSM — bridge does that.
    parent_ctx: Any = None

    # Run-level metrics, surfaced into the final summary.
    n_actions_seen: int = 0
    n_matches: int = 0
    n_suggestions: int = 0
    n_auto_invocations: int = 0
    log: list[dict] = field(default_factory=list)

    # FSM plumbing, populated by manager.
    send_event: Any = None             # Callable[[MacroEvent], None]
    pending_event_data: Any = None     # data carried through ACTION_SEEN
