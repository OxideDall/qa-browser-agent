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


def _params_from_examples(macro) -> dict:
    """First example from meta.examples (mined macros have these).
    Empty dict if none — caller may decide to skip auto-invoke."""
    examples = list(macro.meta.get("examples") or [])
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
            params = _params_from_examples(macro)
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
