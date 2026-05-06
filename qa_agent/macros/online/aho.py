"""Aho-Corasick multi-pattern automaton on tuple keys.

Standard Aho 1975 algorithm: trie + failure links + output links.
We build once at MacroManager startup over the (verb, classifier)
patterns of every installed macro, then stream each agent action
through `step(token)` to get the list of matches ending at the
current position (if any).

Compared to pyahocorasick: we work over arbitrary hashable tokens
(specifically: 2-tuples of strings), no string-encoding gymnastics.
~150 LoC, no deps.

API:
    aho = AhoCorasick()
    aho.add("marketplace_search", [("click", "button"), ("type", "textbox"), ...])
    aho.add("login_basic", [("type", "textbox"), ("type", "textbox"), ("press", "key:enter")])
    aho.build()

    state = aho.start_state()
    for tok in agent_actions:
        state, matches = aho.step(state, tok)
        for m in matches:
            print(m.macro_name, m.pattern_len)

    # Or stateless one-shot:
    matches = aho.find_all(token_sequence)
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass


# A token is `(verb, classifier)` — both strings, both required to be
# non-None. This is what `derive_pattern_from_body` and the miner's
# vocabulary produce.
Token = tuple[str, str]


@dataclass(frozen=True)
class AhoMatch:
    """One pattern hit ending at a given input position."""
    macro_name: str
    pattern_len: int
    end_pos: int                       # 0-based; pos of the last input token


class AhoCorasick:
    """Multi-pattern matcher over tuple-keyed sequences.

    Two-phase: `add` to register patterns, `build` to finalise (compute
    failure + output links). Calling `step` before `build` raises
    RuntimeError — guarantees the automaton is consistent.
    """

    def __init__(self) -> None:
        # Children of node i, keyed by Token. Index 0 is the root.
        self._children: list[dict[Token, int]] = [{}]
        # If node ends a pattern, store (macro_name, pattern_len);
        # else None.
        self._terminal: list[tuple[str, int] | None] = [None]
        # Failure links — node → fallback node when child miss.
        self._fail: list[int] = [0]
        # Output links — chain of terminal nodes reachable via failure
        # (collects nested matches: e.g. if "abc" and "bc" are both
        # patterns, hitting "abc" end-node also outputs "bc").
        self._output: list[list[tuple[str, int]]] = [[]]
        self._built = False
        self._n_patterns = 0

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def add(self, macro_name: str, pattern: list[Token]) -> None:
        """Register a pattern. Must be called before `build`."""
        if self._built:
            raise RuntimeError("cannot add patterns after build()")
        if not pattern:
            raise ValueError(f"macro {macro_name!r}: empty pattern")
        for tok in pattern:
            if not isinstance(tok, tuple) or len(tok) != 2:
                raise ValueError(
                    f"macro {macro_name!r}: pattern token must be a "
                    f"2-tuple (verb, classifier), got {tok!r}"
                )

        node = 0
        for tok in pattern:
            nxt = self._children[node].get(tok)
            if nxt is None:
                nxt = len(self._children)
                self._children.append({})
                self._terminal.append(None)
                self._fail.append(0)
                self._output.append([])
                self._children[node][tok] = nxt
            node = nxt

        # Multiple macros mapping to same final node = collision (same
        # vocab pattern from two macros). Last-write-wins is wrong;
        # store the longer-named one alphabetically for determinism.
        # In practice the curator gives unique names.
        existing = self._terminal[node]
        if existing is not None:
            if macro_name <= existing[0]:
                # earlier alphabetically — keep the existing
                self._n_patterns += 1
                return
        self._terminal[node] = (macro_name, len(pattern))
        self._n_patterns += 1

    def build(self) -> None:
        """Finalise: compute failure + output links via BFS over the trie."""
        if self._built:
            return
        # Root's children fall back to root.
        queue: deque[int] = deque()
        for child in self._children[0].values():
            self._fail[child] = 0
            queue.append(child)

        while queue:
            u = queue.popleft()
            # Output link chain at u: itself if terminal, plus the
            # output chain of fail[u].
            chain: list[tuple[str, int]] = []
            t = self._terminal[u]
            if t is not None:
                chain.append(t)
            chain.extend(self._output[self._fail[u]])
            self._output[u] = chain

            for tok, v in self._children[u].items():
                # failure of v = follow fail of u looking for tok.
                f = self._fail[u]
                while f != 0 and tok not in self._children[f]:
                    f = self._fail[f]
                fb = self._children[f].get(tok, 0)
                if fb == v:
                    fb = 0  # don't loop back to self
                self._fail[v] = fb
                queue.append(v)

        self._built = True

    # ------------------------------------------------------------------
    # Match
    # ------------------------------------------------------------------

    def start_state(self) -> int:
        """Return the initial automaton state. Use this for streaming
        through `step`. Caller threads the returned state forward."""
        if not self._built:
            raise RuntimeError("call build() before matching")
        return 0

    def step(self, state: int, tok: Token, pos: int) -> tuple[int, list[AhoMatch]]:
        """Advance from `state` on input `tok` at input position `pos`.
        Returns (new_state, matches_ending_here)."""
        if not self._built:
            raise RuntimeError("call build() before matching")
        # Follow failure links until tok is a child or we're at root.
        s = state
        while s != 0 and tok not in self._children[s]:
            s = self._fail[s]
        s = self._children[s].get(tok, 0)
        matches = [
            AhoMatch(macro_name=name, pattern_len=plen, end_pos=pos)
            for name, plen in self._output[s]
        ]
        return s, matches

    def find_all(self, tokens: list[Token]) -> list[AhoMatch]:
        """One-shot matching over a complete sequence."""
        if not self._built:
            raise RuntimeError("call build() before matching")
        out: list[AhoMatch] = []
        s = 0
        for i, tok in enumerate(tokens):
            s, matches = self.step(s, tok, i)
            out.extend(matches)
        return out

    @property
    def n_patterns(self) -> int:
        return self._n_patterns

    @property
    def n_nodes(self) -> int:
        return len(self._children)
