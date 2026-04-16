"""Generic FSM dispatcher — the language-agnostic core from ~/fsm.guide.md §3.

Python port. Sync (qa_agent doesn't need async; the browser side is already
blocked per step). Rules, reproduced here verbatim:

  R1. Dispatcher: NO if/else/switch/case by state or event. Only table
      lookup + try/catch + action call.
  R2. Proxies (on_<Event>): one line, one send(event). See runtime/ctx.py.
  R3. Actions: only place for side effects. Return → okState. Throw → errState.
  R4. Entry forms:
        Form A:  (action, next_state)
        Form B:  (action, ok_state, err_state)
        Form C:  bare next_state (allowed only to terminal / onEnter /
                 guaranteed-external-event states per R6).
  R5. Nested FSMs spawn in actions; bridge child.state → parent.event via
      onTransition listener.
  R6. Dead-branch rule: only live rows in the table. Empty cell = no-op.
  R7. Transitions only via send(event). Never mutate state directly.
  R8. State/Event — enum, never strings.
  R9. Ctx holds data, not state flags.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Callable, Generic, TypeVar

S = TypeVar("S", bound=Enum)
E = TypeVar("E", bound=Enum)
C = TypeVar("C")

#: An action is a pure function (well, pure-ish — it can mutate ctx).
#: Return normally → FSM goes to okState. Raise → FSM goes to errState.
Action = Callable[[Any], None]

#: (from_state, to_state, event) — bridges and observers.
Listener = Callable[[Any, Any, Any], None]

# Entry type has three shapes. We use Python tuples; length discriminates.
#   len == 2 → Form A (action, next_state)
#   len == 3 → Form B (action, ok_state, err_state)
#   bare S  → Form C (next_state only, R6-restricted)


class FSM(Generic[S, E, C]):
    """Table-driven finite-state machine.

    The table is a dict[S, dict[E, Entry]]. Missing rows are no-op
    (see guide §R6: empty cells are a feature).
    """

    def __init__(
        self,
        name: str,
        initial: S,
        table: dict[S, dict[E, Any]],
        ctx: C,
    ):
        self.name = name
        self.state: S = initial
        self.table = table
        self.ctx = ctx
        self._listeners: list[Listener] = []
        # Re-entry protection (fsm.guide.md anti-pattern "recursive
        # synchronous send"): when an action calls ctx.send_event(next),
        # we must not re-enter the dispatcher. Instead we enqueue and
        # drain after the current action returns. This is the sync-Python
        # equivalent of the guide's queueMicrotask recommendation.
        self._queue: list[E] = []
        self._draining: bool = False

    def on_transition(self, cb: Listener) -> Callable[[], None]:
        """Register a transition listener. Returns an unsubscribe callable."""
        self._listeners.append(cb)

        def _unsub() -> None:
            if cb in self._listeners:
                self._listeners.remove(cb)

        return _unsub

    def send(self, event: E) -> S:
        """Enqueue an event and drain the queue. Re-entrant: a nested
        send() from inside an action just appends to the queue.
        """
        self._queue.append(event)
        if self._draining:
            return self.state                 # defer — outer send is draining
        self._draining = True
        try:
            while self._queue:
                e = self._queue.pop(0)
                self._send_one(e)
        finally:
            self._draining = False
        return self.state

    def _send_one(self, event: E) -> None:
        """Process exactly one event. Pure table lookup + action call."""
        row = self.table.get(self.state)
        if row is None:
            return                            # R6 no-op
        entry = row.get(event)
        if entry is None:
            return                            # R6 no-op

        from_state = self.state
        if isinstance(entry, tuple):
            to = self._apply_action(entry)    # Form A or B
        else:
            self.state = entry                # Form C
            to = entry

        if from_state is not to:
            for cb in list(self._listeners):
                try:
                    cb(from_state, to, event)
                except Exception:
                    pass                      # listeners never crash the FSM

    def _apply_action(self, entry: tuple) -> S:
        """Run the action-bearing entry. 2-tuple uses ok_state for both paths."""
        if len(entry) == 2:
            action, ok_state = entry
            err_state = ok_state
        elif len(entry) == 3:
            action, ok_state, err_state = entry
        else:
            raise ValueError(
                f"bad transition entry shape {len(entry)} in {self.name}: {entry!r}"
            )
        try:
            action(self.ctx)
            self.state = ok_state
        except Exception:
            self.state = err_state
        return self.state


def make_bridge(
    parent_send: Callable[[Any], Any],
    table: dict,
) -> Listener:
    """Child→Parent bridge. See guide §5.1.

    `table` is a Partial<Record<ChildState, ParentEvent>>. On every child
    transition we look up the new state; if there's an entry, emit the
    corresponding parent event. No business-logic if-branches — just lookup.
    """
    def _bridge(_from_state: Any, to_state: Any, _event: Any) -> None:
        pe = table.get(to_state)
        if pe is None:
            return                            # R6 no-op
        parent_send(pe)

    return _bridge
