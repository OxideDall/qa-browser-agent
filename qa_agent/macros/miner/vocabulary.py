"""Vocabulary reduction — Trace -> sequence of (verb, role) tokens.

Mining works on tuples, not dicts: the algorithm treats each step as
a discrete vocabulary item and counts occurrences of contiguous
N-grams. The reduction here decides what counts as "the same step":

  * verb is always part of the token (`click` is not `type` is not `goto`)
  * target_role is used when present (collapses `click 5` and
    `click 17` to the same token if both id'd a `button`)
  * for verbs without a snapshot id (goto / wait / press / scroll /
    evaluate) we take a coarse classification of the arg as the
    second tuple element, since the verb alone is too generic

Concrete arg values are NOT in the vocabulary item — that's
parameter-inference territory (see `inference.py`). Two runs that
both `type textbox "OK"` vs `type textbox "BUY"` should mine as the
same vocab item; the inference pass spots that the args differ and
proposes a parameter slot.

Verbs we deliberately drop because they're operator-instrumentation,
not part of any real skill:
  * look — vision re-ask, only present in LLM mode under loop detect
  * screenshot — pure observability
  * tab — multi-tab juggling, hard to express in a stable macro
  * macro — already a macro invocation; mining macros-of-macros is a
            phase 4 concern.
"""

from __future__ import annotations

from dataclasses import dataclass

from .loader import Trace, TraceStep


# Verbs we try to mine. Anything outside this set produces a None vocab
# item and the trace step is skipped from the sequence — the algorithm
# stitches across the gap, treating non-mineable steps as no-ops.
_MINE_VERBS = frozenset({
    "click", "type", "select", "hover", "press",
    "goto", "wait", "scroll", "evaluate",
    "expect_visible", "expect_hidden", "expect_text",
    "expect_url", "expect_count", "expect_eval",
    "wait_for",
})

# Arg classifier for verbs without a snapshot-id target. Returns a
# stable label that the miner can use to discriminate `wait 100` from
# `wait 30000` (two completely different intents) without exploding
# the vocab with one item per ms value.
def _classify_wait(arg: str) -> str:
    try:
        ms = int(arg)
    except ValueError:
        return "wait_unknown"
    if ms < 500:
        return "wait_micro"
    if ms < 3000:
        return "wait_short"
    if ms < 15000:
        return "wait_medium"
    return "wait_long"


def _classify_url(arg: str) -> str:
    """Return the URL host. Path / query collapsed since they're
    almost always the parameter we'd extract via inference."""
    if not arg:
        return "url_empty"
    # Cheap host extraction without urlparse — covers common forms.
    s = arg
    for prefix in ("https://", "http://"):
        if s.startswith(prefix):
            s = s[len(prefix):]
            break
    host = s.split("/", 1)[0].split("?", 1)[0].lower()
    return f"url:{host}" if host else "url_relative"


def _classify_press_key(arg: str) -> str:
    """Stable label for press <key>. `press Enter` and
    `press Escape` are different intents."""
    return f"key:{(arg or '').lower()}"


def _classify_scroll_dir(arg: str) -> str:
    return f"scroll:{(arg or 'down').lower()}"


@dataclass(frozen=True)
class VocabItem:
    """One token in the mining sequence. Hashable, equatable, sortable."""
    verb: str
    classifier: str          # role for click/type/etc., wait_short for wait, etc.
    step_no: int             # back-pointer to original trace step (kept out of equality)

    # Equality is on (verb, classifier) only — step_no is bookkeeping.
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, VocabItem):
            return NotImplemented
        return self.verb == other.verb and self.classifier == other.classifier

    def __hash__(self) -> int:
        return hash((self.verb, self.classifier))

    def __repr__(self) -> str:
        return f"<{self.verb}:{self.classifier}>"

    def key(self) -> tuple[str, str]:
        """Hashable comparison key — useful for dict / set ops where
        you don't want step_no fudging the bucket."""
        return (self.verb, self.classifier)


def _step_to_item(s: TraceStep) -> VocabItem | None:
    """Reduce a single step. None means 'skip — non-mineable verb'."""
    v = s.verb
    if v not in _MINE_VERBS:
        return None
    if v in ("click", "type", "select", "hover"):
        role = s.target_role or "_"
        return VocabItem(v, role, s.step_no)
    if v == "goto":
        return VocabItem(v, _classify_url(s.args[0] if s.args else ""), s.step_no)
    if v == "wait":
        return VocabItem(v, _classify_wait(s.args[0] if s.args else "0"), s.step_no)
    if v == "press":
        return VocabItem(v, _classify_press_key(s.args[0] if s.args else ""), s.step_no)
    if v == "scroll":
        return VocabItem(v, _classify_scroll_dir(s.args[0] if s.args else "down"), s.step_no)
    if v == "evaluate":
        # Arg shape — first identifier-ish chunk. Lets the miner
        # discriminate `evaluate document.title` from
        # `evaluate document.querySelectorAll("...").length`.
        expr = s.args[0] if s.args else ""
        head = expr.split("(")[0].split(".")[-1].strip()[:20]
        return VocabItem(v, f"js:{head or 'expr'}", s.step_no)
    if v in ("expect_visible", "expect_hidden", "wait_for"):
        return VocabItem(v, s.target_role or s.args[0] if s.args else "_", s.step_no)
    if v == "expect_text":
        return VocabItem(v, "text_assert", s.step_no)
    if v == "expect_url":
        return VocabItem(v, "url_assert", s.step_no)
    if v == "expect_count":
        return VocabItem(v, "count_assert", s.step_no)
    if v == "expect_eval":
        return VocabItem(v, "eval_assert", s.step_no)
    return None


def extract_vocab(trace: Trace) -> list[VocabItem]:
    """Reduce a full trace to its mining sequence. Non-mineable verbs
    are dropped (sequence becomes contiguous despite holes in the
    original step numbering)."""
    out: list[VocabItem] = []
    for s in trace.steps:
        item = _step_to_item(s)
        if item is None:
            continue
        out.append(item)
    return out
