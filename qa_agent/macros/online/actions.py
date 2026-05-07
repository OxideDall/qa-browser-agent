"""MacroFSM action functions.

Per fsm.guide.md §R3: side effects live here. State changes don't —
the dispatcher does that based on the action's return / raise.

Three actions, one per live event:

  act_start         — STARTED in IDLE: announce + go to SCANNING
  act_on_action     — ACTION_SEEN in SCANNING: feed Aho-Corasick,
                      handle matches, inject suggestion / auto-invoke
  act_disable       — DISABLE in any state: terminate detection

Inject-back contract:

  * Suggest mode (default):
      append a one-liner to parent_ctx.pending_diag so the next
      act_think prepends it to the user message ("looks like macro
      `name`, use `macro <name> ...`").
  * Auto-invoke mode:
      stash a synthetic action in parent_ctx.macro_auto_action;
      AgentFSM.act_classify reads & consumes it on the next turn,
      bypassing the LLM call entirely.

Both modes record the trigger in ctx.log for the run summary.
"""

from __future__ import annotations

import json
import time

from .ctx import MacroCtx
from .states import MacroEvent


def _has_pending_auto(ctx: MacroCtx) -> bool:
    """True if parent already has a queued auto-invocation we haven't
    consumed yet — don't pile up a second one on top."""
    return bool(getattr(ctx.parent_ctx, "macro_auto_action", None))


def _macro_already_succeeded(ctx: MacroCtx, name: str) -> bool:
    """True if this macro already fired-and-succeeded in this run.
    A second auto-invocation would be redundant (page didn't change
    after first), or actively harmful (next firing on a different
    page with stale params). Run-lifetime lock; no expiry."""
    fired = getattr(ctx.parent_ctx, "macro_succeeded_names", None)
    return bool(fired) and name in fired


def _params_from_examples(macro, parent_ctx=None) -> dict:
    """Pick a sample param dict from meta.examples, ideally matching
    the current page's URL template — multi-site macros otherwise
    use the wrong credentials.

    Two example-shape conventions tolerated:
      * New: `{"url_template": "...", "params": {...}}` — anchored.
      * Old: `{"key": "value", ...}` — flat dict, treat as
        url-anchorless. Falls back to first non-empty.

    Returns empty dict if no usable example found; caller may decide
    to skip auto-invoke.
    """
    examples = list(macro.meta.get("examples") or [])
    if not examples:
        return {}

    # Determine current page url_template (if parent_ctx supplied).
    cur_template = ""
    if parent_ctx is not None:
        snapshot = getattr(parent_ctx, "snapshot", None)
        if isinstance(snapshot, dict):
            sig = snapshot.get("signature")
            if isinstance(sig, dict):
                cur_template = sig.get("url_template", "") or ""

    # Phase 1: prefer anchored example whose url_template matches.
    for ex in examples:
        if not isinstance(ex, dict):
            continue
        if "params" in ex and "url_template" in ex:
            if cur_template and ex.get("url_template") == cur_template:
                return dict(ex.get("params") or {})

    # Phase 2: any anchored example (no template match — first wins).
    for ex in examples:
        if isinstance(ex, dict) and "params" in ex:
            return dict(ex.get("params") or {})

    # Phase 3: legacy flat-dict examples.
    for ex in examples:
        if isinstance(ex, dict) and ex:
            return dict(ex)
    return {}


def _format_macro_call(name: str, params: dict) -> str:
    """Tagged-DSL call shape: `macro <name> k=v k=v ...`."""
    parts = [f"macro {name}"]
    for k, v in params.items():
        # Quote values with spaces; otherwise emit raw.
        sv = str(v)
        if " " in sv or "\"" in sv:
            sv = '"' + sv.replace('"', '\\"') + '"'
        parts.append(f"{k}={sv}")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

def act_start(ctx: MacroCtx) -> None:
    """STARTED in IDLE → SCANNING. No-op apart from the implicit
    state transition (handled by the table) — the bridge will start
    pushing ACTION_SEEN events from the next agent turn onward."""
    return None


def act_on_action(ctx: MacroCtx) -> None:
    """ACTION_SEEN: consume one (verb, classifier) tuple, advance the
    Aho-Corasick automaton, react to any matches.

    Per R3 we don't read FSM state — actions only run when the table
    routes here, so SCANNING is implied. Matches are filtered by:

      1. Cooldown — same macro recently triggered? skip.
      2. Precondition — macro's url_template / struct_hash match
         the current page signature? if mismatch, skip.

    Survivors trigger inject-back via parent_ctx.pending_diag (suggest)
    or parent_ctx.macro_auto_action (auto).
    """
    tok = ctx.pending_event_data
    ctx.pending_event_data = None
    if tok is None:
        return

    ctx.n_actions_seen += 1
    ctx.buffer.append(tok)
    if len(ctx.buffer) > ctx.buffer_max:
        ctx.buffer.pop(0)

    new_state, matches = ctx.automaton.step(ctx.aho_state, tok, ctx.pos)
    ctx.aho_state = new_state
    ctx.pos += 1
    if not matches:
        return

    ctx.n_matches += len(matches)
    parent_ctx = ctx.parent_ctx
    parent_step = int(getattr(parent_ctx, "step", 0) or 0)

    for match in matches:
        macro = ctx.macros.get(match.macro_name)
        if macro is None:
            continue

        # Run-lifetime success lock takes precedence over cooldown.
        if _macro_already_succeeded(ctx, match.macro_name):
            continue

        # Cooldown: skip if same macro fired within `cooldown_steps`.
        last = ctx.last_triggered.get(match.macro_name, -10**9)
        if parent_step - last < ctx.cooldown_steps:
            continue

        # Precondition: page signature must satisfy macro's
        # url_templates (if declared). struct_hash matching is by-list
        # rather than exact since meta.preconditions doesn't currently
        # store struct_hashes — open extension point.
        if not _precondition_ok(macro, parent_ctx):
            ctx.log.append({
                "ts": time.time(),
                "step": parent_step,
                "macro": match.macro_name,
                "event": "match_precondition_miss",
            })
            continue

        # Cooldown bookkeeping BEFORE the inject — a no-op inject
        # (already pending auto) shouldn't re-arm a future inject
        # immediately afterwards.
        ctx.last_triggered[match.macro_name] = parent_step

        if ctx.mode == "auto":
            if _has_pending_auto(ctx):
                continue
            params = _params_from_examples(macro, parent_ctx)
            if not params and any(p.required for p in macro.params):
                # Auto-invoke can't synthesise required params without
                # examples — fall back to a suggestion this turn.
                _inject_suggestion(ctx, macro, match)
                continue
            call = _format_macro_call(macro.name, params)
            parent_ctx.macro_auto_action = call
            ctx.n_auto_invocations += 1
            ctx.log.append({
                "ts": time.time(),
                "step": parent_step,
                "macro": match.macro_name,
                "event": "auto_invoke",
                "call": call,
            })
        else:
            _inject_suggestion(ctx, macro, match)


def act_page_ready(ctx: MacroCtx) -> None:
    """PAGE_READY: parent's snapshot is fresh and the LLM is about to
    think. Scan installed macros' preconditions against the current
    page signature; the first macro whose URL template matches is a
    pre-emption candidate.

    Pre-emption fires BEFORE the LLM call, so an auto-invoke replaces
    a full chunk of LLM turns (login takes 3-4 turns; matching macro
    cuts those entirely). Suggest mode injects a hint into the next
    user message via parent_ctx.pending_diag.

    Cooldown is shared with action-driven detection — same macro
    can't fire twice within `cooldown_steps` regardless of which
    bridge originated the trigger.
    """
    parent_ctx = ctx.parent_ctx
    parent_step = int(getattr(parent_ctx, "step", 0) or 0)

    # Already a queued auto-invoke? Don't pile a second on top —
    # let the agent consume the first.
    if _has_pending_auto(ctx):
        return

    # Find first eligible macro: success-lock + precondition + cooldown clean.
    for macro in ctx.macros.values():
        if _macro_already_succeeded(ctx, macro.name):
            continue
        if not _precondition_ok(macro, parent_ctx):
            continue
        last = ctx.last_triggered.get(macro.name, -10**9)
        if parent_step - last < ctx.cooldown_steps:
            continue
        ctx.last_triggered[macro.name] = parent_step
        ctx.n_matches += 1

        if ctx.mode == "auto":
            params = _params_from_examples(macro, parent_ctx)
            if not params and any(p.required for p in macro.params):
                _inject_suggestion(ctx, macro, _PageMatch(macro.name, len(macro.pattern)))
                return
            call = _format_macro_call(macro.name, params)
            parent_ctx.macro_auto_action = call
            ctx.n_auto_invocations += 1
            ctx.log.append({
                "ts": time.time(),
                "step": parent_step,
                "macro": macro.name,
                "event": "page_auto_invoke",
                "call": call,
            })
        else:
            _inject_suggestion(ctx, macro, _PageMatch(macro.name, len(macro.pattern)))
        return  # one pre-emption per page is enough


class _PageMatch:
    """Adapter so `_inject_suggestion` (which expects an Aho-Corasick
    match object) accepts a page-driven trigger uniformly."""
    def __init__(self, macro_name: str, pattern_len: int):
        self.macro_name = macro_name
        self.pattern_len = pattern_len


def act_disable(ctx: MacroCtx) -> None:
    """DISABLE: kill switch. State table sends us to DISABLED;
    further events arriving won't be matched in the empty table row."""
    ctx.log.append({
        "ts": time.time(),
        "step": int(getattr(ctx.parent_ctx, "step", 0) or 0),
        "event": "disabled",
    })


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _precondition_ok(macro, parent_ctx) -> bool:
    """Check if the agent's current page signature satisfies the
    macro's declared URL templates. Empty url_templates → match
    anything (hand-written macros without preconditions)."""
    templates = list(macro.preconditions.get("url_templates") or [])
    if not templates:
        return True

    snapshot = getattr(parent_ctx, "snapshot", None) or {}
    sig = snapshot.get("signature") if isinstance(snapshot, dict) else None
    if not sig:
        # No signature recorded yet — be conservative, skip the
        # match rather than false-positive on an unknown page.
        return False
    cur = sig.get("url_template", "")
    return cur in templates


def _inject_suggestion(ctx: MacroCtx, macro, match) -> None:
    """Stash a one-line suggestion on parent_ctx.pending_diag.
    Format mirrors the existing `[DIAG since last action]` channel
    so it doesn't break message-alternation rules in act_think."""
    parent = ctx.parent_ctx
    params_hint = ""
    examples = list(macro.meta.get("examples") or [])
    if examples and isinstance(examples[0], dict):
        params_hint = " " + " ".join(
            f"{k}={v}" for k, v in list(examples[0].items())[:3]
        )
    blurb = (
        f"[MACRO HINT] sub-trace matched installed macro "
        f"`{macro.name}` (len {match.pattern_len}). "
        f"To invoke: `macro {macro.name}{params_hint}`. "
        f"({macro.description[:80]})"
    )
    existing = getattr(parent, "pending_diag", "") or ""
    if blurb in existing:
        return
    parent.pending_diag = (existing + "\n" + blurb).strip() if existing else blurb
    ctx.n_suggestions += 1
    ctx.log.append({
        "ts": time.time(),
        "step": int(getattr(parent, "step", 0) or 0),
        "macro": macro.name,
        "event": "suggestion",
        "blurb": blurb[:200],
    })
