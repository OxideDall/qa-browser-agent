"""Action functions for the AgentFSM (phase 3b of bench/fsm_design.md).

Each function takes `ctx: AgentCtx` (and possibly a few loop-local kwargs),
mutates ctx in place, returns either `None` or a small dict of transient
loop-local values that the caller needs. Raises only on genuine errors.

For phase 3b these are called from the existing `run_task` for-loop —
not yet wired to an FSM dispatcher. Phase 3c will build the transition
table that invokes exactly these functions via
`(action, ok_state, err_state)` entries.
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Any

from ..actions import parse_action
from ..extract import extract_elements
from ..llm import ask_llm
from ..vision import capture_annotated_screenshot
from .ctx import on_done_reask
from .evidence import has_evidence
from .loop_detect import is_oscillating
from .mm_popup import has_mm_action


# ---------------------------------------------------------------------------
# Flicker detection
# ---------------------------------------------------------------------------

# Two add/remove records on the *same* node fingerprint within this many
# milliseconds of each other count as one flicker event. 500ms matches the
# user's spec ("repeated add/remove of the same DOM node in <500ms").
FLICKER_WINDOW_MS = 500
# A single offender has to flap at least this many times before it's
# reported — once-off layout shifts (e.g. a tooltip appearing then closing)
# are not "flicker", they're normal interaction. Genuine flicker tends to
# bounce 4+ times.
FLICKER_MIN_FLAPS = 4


def detect_flicker(page: Any) -> list[dict]:
    """Drain `window.__qa_mutations` from the page and return a list of
    flicker events that occurred since the last drain.

    Each event has shape `{"node": "<fingerprint>", "parent": "...",
    "flaps": int, "first_ms": float, "last_ms": float}`. Callers append
    these to `ctx.flicker_log`; `_emit_step` slices that log per-step.

    Browser-only — call sites must guard `ctx.driver_kind == "browser"`.
    """
    try:
        records = page.evaluate(
            "() => (window.__qa_mutations && window.__qa_mutations.drain()) || []"
        )
    except Exception:
        return []
    if not records:
        return []

    # Group by node fingerprint, count how many add+remove flaps each one
    # experienced and over what window. A "flap" requires an add followed
    # by a remove (or vice versa) within FLICKER_WINDOW_MS. We don't need
    # exact pair matching — counting transitions per node is enough.
    by_node: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        n = r.get("node") or ""
        if not n:
            continue
        by_node[n].append(r)

    out: list[dict] = []
    now = time.time()
    for node, evs in by_node.items():
        if len(evs) < FLICKER_MIN_FLAPS:
            continue
        evs.sort(key=lambda e: e.get("t") or 0.0)
        # Count alternating kind transitions inside a sliding window.
        flaps = 0
        first_t = evs[0].get("t") or 0.0
        last_t = evs[-1].get("t") or 0.0
        if last_t - first_t > FLICKER_WINDOW_MS * (len(evs) // 2 + 1):
            # Spread far too wide — not a single burst. Skip.
            continue
        prev_kind = None
        for e in evs:
            kind = e.get("kind")
            if prev_kind and kind != prev_kind:
                flaps += 1
            prev_kind = kind
        if flaps < FLICKER_MIN_FLAPS:
            continue
        out.append({
            "ts": now,
            "node": node[:200],
            "parent": (evs[0].get("parent") or "")[:120],
            "flaps": flaps,
            "first_ms": first_t,
            "last_ms": last_t,
            "duration_ms": last_t - first_t,
        })
    return out


# -----------------------------------------------------------------------
# Action: snapshot_page — build the DSL snapshot of the currently focused
# page. Corresponds to FSM state AgentState.SNAPSHOTTING.
# -----------------------------------------------------------------------

def snapshot_page(ctx: Any) -> dict:
    """Refresh page state + extract interactive elements. Mutates:
      - ctx.page (may swap if it was closed, or if an MM popup was released)
      - ctx.mm_popup_active (cleared if the popup closed or emptied)

    Returns a loop-local dict the caller consumes for the next ask_llm call:
      {"elements": list, "elements_text": str, "is_fallback": bool,
       "step_image": str|None}
    """
    # Android driver: skip every browser/MM-specific branch and delegate
    # to the uiautomator2 adapter. There is no tab/popup reconciliation on
    # a phone — the device has a single foreground UI at a time.
    if getattr(ctx, "driver_kind", "browser") == "android":
        from ..android import snapshot_android
        return snapshot_android(ctx)

    # 1) Recover if the current page was closed (extension popup scenarios).
    if ctx.page.is_closed():
        pages = ctx.context.pages
        ctx.page = pages[-1] if pages else ctx.context.new_page()
        ctx.page.bring_to_front()

    # 2) Sync mm_popup_active: release the lock if the popup closed or
    #    stopped presenting an actionable body.
    if ctx.mm_popup_active is not None:
        released = False
        try:
            if ctx.mm_popup_active.is_closed():
                released = True
            else:
                body = ctx.mm_popup_active.inner_text("body", timeout=1500)
                if not has_mm_action(body):
                    released = True
                    try:
                        ctx.mm_popup_active.close()
                    except Exception:
                        pass
        except Exception:
            released = True
        if released:
            ctx.mm_popup_active = None
            for pg in ctx.context.pages:
                if not pg.is_closed() and "chrome-extension://" not in pg.url:
                    ctx.page = pg
                    pg.bring_to_front()
                    break

    # 3) Close stale empty extension notification pages. Threshold <3 avoids
    #    closing actual MM dashboards (which have body like "owner" = 5 chars).
    for pg in list(ctx.context.pages):
        if (pg is not ctx.page and not pg.is_closed()
                and "chrome-extension://" in pg.url):
            try:
                body = pg.inner_text("body", timeout=1000).strip()
                if len(body) < 3:
                    pg.close()
            except Exception:
                pass

    # 4) Extract interactive elements + snapshot DSL.
    elements, elements_text, is_fallback = extract_elements(ctx.page)
    if not elements:
        elements_text += "\n(No interactive elements found)"

    # 5) On the LavaMoat fallback path, auto-attach a screenshot because the
    #    HTML parser misses layout cues.
    step_image: str | None = None
    if is_fallback:
        try:
            step_image = capture_annotated_screenshot(
                ctx.page, skip_bboxes=True
            )
        except Exception:
            pass

    # 6) Multi-tab header — helps the agent pick the right tab with `tab N`.
    if len(ctx.context.pages) > 1:
        tab_lines = [f"Open tabs ({len(ctx.context.pages)}):"]
        for i, pg in enumerate(ctx.context.pages):
            marker = " *" if pg is ctx.page else ""
            tab_lines.append(f"  tab {i}: {pg.url[:80]}{marker}")
        elements_text = "\n".join(tab_lines) + "\n" + elements_text

    return {
        "elements": elements,
        "elements_text": elements_text,
        "is_fallback": is_fallback,
        "step_image": step_image,
    }


# -----------------------------------------------------------------------
# Action: evidence_verdict — classify a parsed `done` action. Maps to
# FSM events EVIDENCE_OK / EVIDENCE_MISS / REASKS_EXHAUSTED (design doc).
# -----------------------------------------------------------------------

def evidence_verdict(ctx: Any, status: str, description: str) -> str:
    """Return one of: "accept" | "pass_fail" | "reask" | "forced_fail".

    Mutates ctx.done_reasks on "reask" / "forced_fail" paths.

      "accept"       — done PASS with concrete evidence. Agent done.
      "pass_fail"    — done FAIL. Always accepted (emergency abort).
      "reask"        — done PASS rejected, ctx.done_reasks incremented.
                       Agent should try again with better evidence.
      "forced_fail"  — done PASS rejected ≥2 times. Force FAIL to avoid
                       burning steps arguing.
    """
    if status != "PASS":
        return "pass_fail"
    if has_evidence(description):
        return "accept"
    on_done_reask(ctx)
    if ctx.done_reasks >= 2:
        return "forced_fail"
    return "reask"


# -----------------------------------------------------------------------
# Action: loop_check — classify repetition in ctx.prev_actions. Maps to
# FSM events HARD_LOOP / SOFT_LOOP / NO_LOOP.
# -----------------------------------------------------------------------

def loop_check(ctx: Any, action: str) -> str:
    """Return one of: "hard" | "soft" | "none".

      "hard"  — 6 identical actions in a row OR ABABAB oscillation in
                the last 6. Caller should force FAIL.
      "soft"  — 3 identical in a row OR ABAB in last 4, and current
                action is not "done". Caller should force a vision
                re-dispatch on the agent's next response.
      "none"  — no loop, or current action is "done" (terminal, no
                need to vision).
    """
    prev = ctx.prev_actions

    # Hard loop: 6 same OR 6-cycle ABABAB.
    is_identical_hard = (len(prev) >= 6 and len(set(prev[-6:])) == 1)
    is_osc_hard = is_oscillating(prev, window=6)
    if is_identical_hard or is_osc_hard:
        return "hard"

    # Soft loop: 3 same OR 4-cycle ABAB. Only actionable when the
    # current action isn't already `done` (no point re-visioning a done).
    if action == "done":
        return "none"
    is_identical_soft = (len(prev) >= 3 and len(set(prev[-3:])) == 1)
    is_osc_soft = is_oscillating(prev, window=4)
    if is_identical_soft or is_osc_soft:
        return "soft"
    return "none"


# -----------------------------------------------------------------------
# Action: vision_retry — take an annotated screenshot, ask the LLM for
# one more action. Used by both the `look` DSL action and the soft-loop
# auto-vision path. Called inline by act_vision_look / act_vision_forced
# in fsm_actions.py (Phase 3c flattened this from its own FSM state).
# -----------------------------------------------------------------------

_VISION_PROMPT_LOOK = (
    "Here is a screenshot + fresh page snapshot.\n"
    "IMPORTANT: Use ONLY element IDs from the snapshot below.\n\n"
    "{elements_text}\n\n"
    "Respond with exactly ONE action line."
)
_VISION_PROMPT_LOOP = (
    "LOOP DETECTED. Here is a screenshot + fresh page snapshot.\n"
    "IMPORTANT: Use ONLY element IDs from the snapshot below.\n\n"
    "{elements_text}\n\n"
    "Respond with exactly ONE action line. Try a DIFFERENT action or done FAIL."
)


def vision_retry(
    ctx: Any,
    messages: list,
    system_prompt: str,
    step_record: dict,
    elements_text: str,
    *,
    is_fallback: bool = False,
    reason: str = "look",
) -> tuple[str, list[str], str]:
    """Annotated-screenshot vision re-dispatch.

    Captures a screenshot, appends a prompt + the fresh elements_text to
    `messages`, calls ask_llm with the image, parses the reply. Returns
    (action, args, raw_resp_text).

    Side effects on ctx and step_record:
      - ctx.total_in / ctx.total_out += token counts
      - step_record["in_tokens"] / ["out_tokens"] += token counts
      - step_record["action"] / ["args"] set to the parsed action

    `reason="look"` uses the neutral prompt.
    `reason="loop"` uses the anti-repetition prompt.

    Raises on screenshot / LLM failure — callers handle.
    """
    if getattr(ctx, "driver_kind", "browser") == "android":
        from ..android import capture_annotated_screenshot_android
        img_b64 = capture_annotated_screenshot_android(
            ctx.android_device, ctx.snapshot["elements"],
        )
    else:
        img_b64 = capture_annotated_screenshot(ctx.page, skip_bboxes=is_fallback)
    template = _VISION_PROMPT_LOOP if reason == "loop" else _VISION_PROMPT_LOOK
    messages.append({
        "role": "user",
        "content": template.format(elements_text=elements_text),
    })
    resp_text, in_tok, out_tok = ask_llm(
        ctx.access_token, messages, system_prompt, image_b64=img_b64
    )
    ctx.total_in += in_tok
    ctx.total_out += out_tok
    step_record["in_tokens"] += in_tok
    step_record["out_tokens"] += out_tok
    messages.append({"role": "assistant", "content": resp_text})
    action, args = parse_action(resp_text)
    step_record["action"] = action
    step_record["args"] = list(args)
    return action, args, resp_text
