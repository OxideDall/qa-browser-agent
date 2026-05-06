"""Live vocabulary translation: AgentCtx → (verb, classifier) tuple.

Mirrors miner.vocabulary._step_to_item but works off the live AgentCtx
fields (action / args / snapshot.elements) rather than a captured
TraceStep dict. All three sides — miner, hand-written-body derivation,
online detector — must produce the same tokens for the Aho-Corasick
automaton's alphabet to align.

The shared classifier helpers live in miner.vocabulary; we import
those here rather than duplicate.
"""

from __future__ import annotations

from typing import Any

from ..miner.vocabulary import (
    _MINE_VERBS,
    _classify_press_key,
    _classify_scroll_dir,
    _classify_url,
    _classify_wait,
)


def _resolve_target_role(args: list[str], snapshot: dict | None) -> str:
    """For verbs that act on a snapshot id, look the role up so we
    classify (click, button) the same as the miner did. Falls back
    to '_' if the id isn't resolvable."""
    if not args or not snapshot:
        return "_"
    try:
        eid = int(args[0])
    except (TypeError, ValueError):
        return "_"
    elements = snapshot.get("elements") or []
    for el in elements:
        if el.get("id") == eid:
            return str(el.get("role") or el.get("tag") or "_")
    return "_"


def vocab_from_agent_ctx(parent_ctx: Any) -> tuple[str, str] | None:
    """Translate the just-parsed agent action into the mining
    vocabulary. Returns None for verbs the miner doesn't track —
    detector skips those without bookkeeping."""
    verb = getattr(parent_ctx, "action", "") or ""
    if verb not in _MINE_VERBS:
        return None
    args = list(getattr(parent_ctx, "args", []) or [])
    snapshot = getattr(parent_ctx, "snapshot", None)

    if verb in ("click", "type", "select", "hover"):
        # The agent stores parsed args as [id, ...]. miner.vocabulary
        # uses target_role from step_record (populated by act_classify);
        # here we recover the same value from the live snapshot.
        return (verb, _resolve_target_role(args, snapshot))
    if verb == "press":
        return (verb, _classify_press_key(args[0] if args else ""))
    if verb == "scroll":
        return (verb, _classify_scroll_dir(args[0] if args else "down"))
    if verb == "goto":
        return (verb, _classify_url(args[0] if args else ""))
    if verb == "wait":
        return (verb, _classify_wait(args[0] if args else "0"))
    if verb == "evaluate":
        expr = args[0] if args else ""
        head = expr.split("(")[0].split(".")[-1].strip()[:20]
        return (verb, f"js:{head or 'expr'}")
    if verb in ("expect_visible", "expect_hidden", "wait_for"):
        # In the live LLM path the LLM doesn't currently emit these
        # verbs (they're tagged-only). Cover for symmetry — derived
        # patterns and tagged-mode captures both reference them.
        return (verb, _resolve_target_role(args, snapshot))
    if verb == "expect_text":
        return (verb, "text_assert")
    if verb == "expect_url":
        return (verb, "url_assert")
    if verb == "expect_count":
        return (verb, "count_assert")
    if verb == "expect_eval":
        return (verb, "eval_assert")
    return None
