"""MacroManager — wires AgentFSM together with a child MacroFSM.

Lifecycle (one per `run_task` invocation):

  __init__:
    * Decide if detection is enabled at all (env / explicit override).
    * Load installed macros, build Aho-Corasick automaton.
    * Construct child MacroFSM, plumb send_event / parent_ctx.
    * Register the bridge listener on the parent AgentFSM.
    * Send STARTED to move the child IDLE → SCANNING.

  finalise():
    * Detach bridge (no-op if already gone).
    * Send DISABLE if still SCANNING.
    * Return run-level metrics for the on_finish summary.

Per fsm.guide.md §R5 the child runs in its own queue — we don't await
its events, the bridge just keeps shoving them in. Detection is
fire-and-forget unless the kill switch is hit.

Environment:

  QA_DISABLE_MACRO_DETECT=1  — never instantiate the detector
  QA_AUTO_MACRO=1            — invoke matched macros automatically;
                               default is suggestion-only (LLM decides)
"""

from __future__ import annotations

import os
from typing import Any

from ...runtime.fsm import FSM
from ..library import Macro, list_macros, load_macro, MACROS_DIR
from .aho import AhoCorasick
from .bridge import make_macro_bridge
from .ctx import MacroCtx
from .states import MacroEvent, MacroState
from .transitions import MACRO_TRANSITIONS


class MacroManager:
    """Owns the child FSM + bridge for one agent run.

    `disabled` flag short-circuits everything when env / load-time
    decisions said "skip detection on this run". The manager still
    instantiates so callers can query `.summary()` uniformly.
    """

    def __init__(
        self,
        parent_fsm: FSM,
        parent_ctx: Any,
        *,
        macros_root: Any = None,
        mode: str | None = None,
        disabled: bool | None = None,
    ) -> None:
        # Resolve flags from env unless explicit override.
        env_disabled = os.environ.get("QA_DISABLE_MACRO_DETECT") == "1"
        env_auto = os.environ.get("QA_AUTO_MACRO") == "1"
        self.disabled = bool(disabled) if disabled is not None else env_disabled
        resolved_mode = mode if mode is not None else (
            "auto" if env_auto else "suggest"
        )

        self.parent_fsm = parent_fsm
        self.parent_ctx = parent_ctx
        self._unsub: Any = None
        self._fsm: FSM | None = None
        self._ctx: MacroCtx | None = None
        self._n_loaded = 0

        if self.disabled:
            return

        root = macros_root if macros_root is not None else MACROS_DIR()
        macros = self._load_macros(root)
        self._n_loaded = len(macros)
        if not macros:
            # No installed macros → nothing to detect. Stay disabled
            # silently (still expose summary() for symmetry).
            self.disabled = True
            return

        automaton = AhoCorasick()
        for m in macros.values():
            if m.pattern:
                automaton.add(m.name, [tuple(t) for t in m.pattern])
        if automaton.n_patterns == 0:
            self.disabled = True
            return
        automaton.build()

        ctx = MacroCtx(
            automaton=automaton,
            macros=macros,
            mode=resolved_mode,
            parent_ctx=parent_ctx,
        )
        fsm = FSM("MacroFSM", MacroState.IDLE, MACRO_TRANSITIONS, ctx)
        ctx.send_event = fsm.send  # R5: action emits via ctx.send_event

        # Register bridge BEFORE STARTED so we don't miss the first
        # action of the run (parent's first LLM_REPLIED could fire
        # immediately after our STARTED on the same tick).
        self._unsub = parent_fsm.on_transition(
            make_macro_bridge(fsm.send, ctx, parent_ctx),
        )

        self._fsm = fsm
        self._ctx = ctx

        fsm.send(MacroEvent.STARTED)

        # Pre-feed the implicit start-up goto. run_task does
        # `page.goto(start_url)` directly (outside the FSM) before the
        # first LLM call, so the bridge can't observe it. Without this
        # synthetic event, macros whose pattern starts with `goto`
        # never trigger on the auto-navigated URL.
        start_url = getattr(parent_ctx, "url", None)
        if start_url:
            from ..miner.vocabulary import _classify_url
            ctx.pending_event_data = ("goto", _classify_url(start_url))
            fsm.send(MacroEvent.ACTION_SEEN)

    @staticmethod
    def _load_macros(root) -> dict[str, Macro]:
        """Load every installed macro under `root`, keyed by name.
        Skips entries with errors — list_macros surfaces them so the
        operator can see, but the manager mustn't fail-open."""
        out: dict[str, Macro] = {}
        for entry in list_macros(root=root):
            name = entry.get("name")
            if not name or "error" in entry:
                continue
            try:
                m = load_macro(name, root=root)
            except Exception:
                continue
            out[m.name] = m
        return out

    def finalise(self) -> None:
        """Detach the bridge listener and disable the child. Safe to
        call multiple times — second-onwards is a no-op."""
        if self._unsub is not None:
            try:
                self._unsub()
            except Exception:
                pass
            self._unsub = None
        if self._fsm is not None and self._fsm.state is MacroState.SCANNING:
            try:
                self._fsm.send(MacroEvent.DISABLE)
            except Exception:
                pass

    def summary(self) -> dict:
        """Run-level metrics for the on_finish summary."""
        if self.disabled or self._ctx is None:
            return {
                "enabled": False,
                "n_macros_loaded": self._n_loaded,
                "n_actions_seen": 0,
                "n_matches": 0,
                "n_suggestions": 0,
                "n_auto_invocations": 0,
            }
        return {
            "enabled": True,
            "mode": self._ctx.mode,
            "n_macros_loaded": self._n_loaded,
            "n_actions_seen": self._ctx.n_actions_seen,
            "n_matches": self._ctx.n_matches,
            "n_suggestions": self._ctx.n_suggestions,
            "n_auto_invocations": self._ctx.n_auto_invocations,
            "log": list(self._ctx.log[:50]),
        }
