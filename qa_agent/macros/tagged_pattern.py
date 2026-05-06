"""Derive a (verb, classifier) pattern list from a tagged-DSL body.

Mined macros write their pattern into meta.json directly. Hand-written
macros don't go through the miner, so we recover the pattern by
parsing the tagged body the same way the runtime parser does, then
translating each Step into the same vocabulary classifier the miner
uses (vocabulary.py). Same vocab on both sides → online detector
matches against the same alphabet the miner produced.

We deliberately keep this small and local: it's the *one* place where
hand-written macros and the online detector meet. If the miner's
classifier logic in vocabulary.py changes, this file follows.
"""

from __future__ import annotations

from .miner.vocabulary import (
    _MINE_VERBS,
    _classify_press_key,
    _classify_scroll_dir,
    _classify_url,
    _classify_wait,
)
from ..tagged import (
    _ROLES,
    Step,
    TaggedParseError,
    parse_tagged,
)


def _classify_step(step: Step) -> tuple[str, str] | None:
    """Tagged-DSL Step -> (verb, classifier). Mirrors
    miner.vocabulary._step_to_item but works off Step rather than
    TraceStep. Returns None for verbs not in _MINE_VERBS.
    """
    v = step.verb
    if v not in _MINE_VERBS:
        return None
    args = step.args

    # Selector-bearing verbs: classifier = role
    if v in ("click", "hover"):
        # Tagged form: `click <role>` (often followed by an accessible name).
        if args and args[0] in _ROLES:
            return (v, args[0])
        return (v, args[0] if args else "_")
    if v == "type":
        # `type <role> "text"` — role is args[0]
        if args and args[0] in _ROLES:
            return (v, args[0])
        return (v, args[0] if args else "_")
    if v == "select":
        if args and args[0] in _ROLES:
            return (v, args[0])
        return (v, args[0] if args else "_")
    if v == "press":
        return (v, _classify_press_key(args[0] if args else ""))
    if v == "scroll":
        return (v, _classify_scroll_dir(args[0] if args else "down"))
    if v == "goto":
        return (v, _classify_url(args[0] if args else ""))
    if v == "wait":
        return (v, _classify_wait(args[0] if args else "0"))
    if v == "evaluate":
        expr = args[0] if args else ""
        head = expr.split("(")[0].split(".")[-1].strip()[:20]
        return (v, f"js:{head or 'expr'}")
    if v in ("expect_visible", "expect_hidden", "wait_for"):
        # Tagged: `expect_visible <role> [timeout]` — role at args[0].
        if args:
            return (v, args[0])
        return (v, "_")
    if v == "expect_text":
        return (v, "text_assert")
    if v == "expect_url":
        return (v, "url_assert")
    if v == "expect_count":
        return (v, "count_assert")
    if v == "expect_eval":
        return (v, "eval_assert")
    return None


def derive_pattern_from_body(body: str) -> list[tuple[str, str]]:
    """Parse a tagged body and reduce each step to its (verb,
    classifier) tuple. Steps the miner-vocabulary doesn't mine
    (look / screenshot / tab / macro) are dropped.

    Raises TaggedParseError if the body has malformed steps — that's
    a programmer error in the macro, not silent. Callers can catch
    if they want best-effort behaviour.
    """
    steps = parse_tagged(body)
    out: list[tuple[str, str]] = []
    for s in steps:
        item = _classify_step(s)
        if item is not None:
            out.append(item)
    return out


__all__ = ["derive_pattern_from_body", "TaggedParseError"]
