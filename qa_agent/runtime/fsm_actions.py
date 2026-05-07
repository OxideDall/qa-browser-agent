"""FSM-compatible action wrappers.

Each function here is a single state's action per bench/fsm_design.md.
Contract:

  - Takes exactly one parameter: `ctx: AgentCtx`.
  - Reads ctx fields it needs; writes ctx fields it produces.
  - On success: emits the next event via ctx.send_event(E) and returns.
  - On unrecoverable failure: raises — dispatcher routes to err_state.
  - State transitions are owned by AGENT_TRANSITIONS (transitions.py),
    NOT by these functions.

All the real work lives in the plain-Python helpers in this package
(snapshot_page, evidence_verdict, loop_check, vision_retry, etc). These
wrappers just glue them into the FSM contract.
"""

from __future__ import annotations

import time
from typing import Any

from ..actions import execute_action, _el_info, parse_action
from ..config import HISTORY_WINDOW, TEST_PASSWORD
from ..llm import ask_llm
from .actions import (
    detect_flicker, evidence_verdict, loop_check, snapshot_page, vision_retry,
)
from .ctx import AgentCtx, on_popup_opened, on_tx_trigger
from .messages import DONE_REASK_MSG
from .mm_popup import has_mm_action
from .states import AgentEvent


class _MaxStepsReached(Exception):
    """Raised by act_new_step when ctx.step has hit ctx.max_steps."""


# -----------------------------------------------------------------------
# Step-record helpers (mirror the old _emit_step closure from agent.py).
# -----------------------------------------------------------------------

def _new_step_record(ctx: AgentCtx) -> dict:
    return {
        "t": "step", "step": ctx.step, "action": None, "args": [],
        "result": None, "in_tokens": 0, "out_tokens": 0,
        "page_url": None, "mm_active": False, "loop_hit": None,
        "blocked": None, "done_reasked": False,
        "evidence_present": None, "vision": False,
        "latency_ms": None,
        "_t0": time.time(),
    }


def _emit_step(ctx: AgentCtx) -> None:
    """Idempotent per-step record emit. Safe to call multiple times; only the
    first call (per step_record) hits the on_step listener.

    Also closes out the per-step diagnostics window: takes a final-state
    screenshot, slices console/network/flicker logs since the previous
    cursor into sr["console"]/["network"]/["flicker"], and advances the
    cursors so the next step starts with a clean slice.
    """
    sr = ctx.step_record
    if sr is None or sr.get("_emitted"):
        return
    sr["_emitted"] = True
    sr["latency_ms"] = int((time.time() - sr["_t0"]) * 1000)
    try:
        sr["page_url"] = ctx.page.url
        sr["mm_active"] = ctx.mm_popup_active is not None
    except Exception:
        pass

    # Per-step screenshot. Filename embeds step number for stable
    # ordering. Errors (closed page / extension page that disallows
    # shots / missing dir) are tolerated silently — instrumentation
    # must never break a run.
    if ctx.screenshots_dir is not None:
        kind = getattr(ctx, "driver_kind", "browser")
        try:
            if kind == "android" and ctx.android_device is not None:
                shot = ctx.screenshots_dir / f"step_{ctx.step:03d}.png"
                # uiautomator2's Device.screenshot(path) writes a PNG.
                ctx.android_device.screenshot(str(shot))
            elif kind == "browser" and ctx.page is not None:
                shot = ctx.screenshots_dir / f"step_{ctx.step:03d}.jpg"
                # full_page=True so post-mortem audits see content below
                # the fold; viewport-only shots dropped fixed-positioned
                # overlays inconsistently because of scroll position.
                ctx.page.screenshot(
                    path=str(shot), type="jpeg", quality=60,
                    full_page=True, timeout=3500,
                )
            else:
                shot = None
            if shot is not None:
                shot_str = str(shot)
                sr["screenshot"] = shot_str
                ctx.screenshots.append(shot_str)
        except Exception:
            pass

    # Slice console / network / flicker logs accumulated since the
    # previous step's _emit_step. Each gets its own cursor on ctx so
    # the slices never overlap.
    sr["console"] = ctx.console_log[ctx.console_cursor:]
    ctx.console_cursor = len(ctx.console_log)
    sr["network"] = ctx.network_errors[ctx.network_cursor:]
    ctx.network_cursor = len(ctx.network_errors)
    sr["flicker"] = ctx.flicker_log[ctx.flicker_cursor:]
    ctx.flicker_cursor = len(ctx.flicker_log)

    # Stash the diagnostic blurb on ctx — act_think on the next turn
    # prepends it to its user_msg so we keep strict user/assistant
    # alternation in ctx.messages.
    diag_msg = _build_diag_msg(sr)
    if diag_msg:
        ctx.pending_diag = diag_msg
        if ctx.verbose:
            # Indent under the step label for readability.
            for line in diag_msg.splitlines():
                print(f"    {line}")

    if sr.get("flicker"):
        flap_count = sum(f.get("flaps", 0) for f in sr["flicker"])
        if ctx.verbose:
            sample = sr["flicker"][0]
            print(
                f"    [flicker] {len(sr['flicker'])} node(s), "
                f"{flap_count} flaps total — first: "
                f"{sample.get('node', '')[:60]} "
                f"({sample.get('flaps', 0)} flaps in "
                f"{sample.get('duration_ms', 0):.0f}ms)"
            )

    if ctx.on_step:
        try:
            ctx.on_step({k: v for k, v in sr.items() if not k.startswith("_")})
        except Exception:
            pass


def _build_diag_msg(sr: dict) -> str:
    """Compact summary of console/network errors that arose during this
    step. Returns "" if nothing notable happened — caller skips the inject.
    Cap at 6 entries total to keep the LLM context lean.
    """
    console = [c for c in sr.get("console") or []
               if c.get("level") in ("error", "pageerror", "warning")]
    network = sr.get("network") or []
    if not console and not network:
        return ""
    lines: list[str] = []
    for c in console[:3]:
        lvl = c.get("level", "?")
        txt = (c.get("text") or "")[:160].replace("\n", " ")
        lines.append(f"  [{lvl}] {txt}")
    for n in network[:3]:
        st = n.get("status") or n.get("kind") or "?"
        url = (n.get("url") or "")[:120]
        method = n.get("method") or "?"
        lines.append(f"  [net {st}] {method} {url}")
    if not lines:
        return ""
    extras = []
    if len(console) > 3:
        extras.append(f"{len(console) - 3} more console")
    if len(network) > 3:
        extras.append(f"{len(network) - 3} more network")
    suffix = f" (+ {', '.join(extras)})" if extras else ""
    return (
        "[DIAG since last action]\n" + "\n".join(lines) + suffix
    )


# -----------------------------------------------------------------------
# act_new_step — budget check, step-record init, page snapshot, emit
# SNAPSHOT_READY. Entry action for the IDLE→SNAPSHOTTING (and all
# loops back to SNAPSHOTTING) transition.
# -----------------------------------------------------------------------

def act_new_step(ctx: AgentCtx) -> None:
    # Close out the previous step (if any) before starting the next.
    _emit_step(ctx)

    # Budget check.
    if ctx.step >= ctx.max_steps:
        ctx.status = "ERROR"
        ctx.description = "Max steps reached"
        raise _MaxStepsReached()

    ctx.step += 1
    ctx.step_record = _new_step_record(ctx)
    ctx.label = f"[{ctx.step}/{ctx.max_steps}]"

    ctx.snapshot = snapshot_page(ctx)
    if ctx.snapshot["is_fallback"] and ctx.verbose and ctx.step == 1:
        print("  [fallback mode: JS eval blocked, using HTML parser + vision]")
    # Surface the pre-action signature on the step record so per-step
    # listeners (bench recorder, capture writer) see it without
    # reaching into ctx.snapshot themselves.
    if ctx.snapshot.get("signature"):
        ctx.step_record["pre_signature"] = ctx.snapshot["signature"]
    ctx.send_event(AgentEvent.SNAPSHOT_READY)


# -----------------------------------------------------------------------
# act_think — build the user message, run history compression, call LLM
# with 401-retry, emit LLM_REPLIED. Entry action for
# SNAPSHOTTING → THINKING.
# -----------------------------------------------------------------------

def act_think(ctx: AgentCtx) -> None:
    from ..agent import ANDROID_SYSTEM_PROMPT, SYSTEM_PROMPT
    prompt = (ANDROID_SYSTEM_PROMPT
              if getattr(ctx, "driver_kind", "browser") == "android"
              else SYSTEM_PROMPT)

    elements_text = ctx.snapshot["elements_text"]
    step_image = ctx.snapshot["step_image"]

    # Multi-turn with compressed history (same policy as pre-FSM loop):
    # first msg carries the task verbatim; later msgs just the snapshot.
    # Prefix every turn with the step budget so the agent knows how many
    # turns it still has — without this it tends to call `done` early on
    # multi-turn tasks ("supervisor reply" style flows that need ≥ N
    # exchanges before evidence is on the page).
    remaining = max(0, ctx.max_steps - ctx.step)
    budget_hdr = f"[step {ctx.step}/{ctx.max_steps} | budget: {remaining} left]\n"
    diag_prefix = ""
    if ctx.pending_diag:
        diag_prefix = ctx.pending_diag.rstrip() + "\n\n"
        ctx.pending_diag = ""
    if ctx.step == 1 and not ctx.messages:
        user_msg = f"{budget_hdr}{diag_prefix}Task: {ctx.task}\n\n{elements_text}"
    elif ctx.step == 1:
        user_msg = f"{budget_hdr}{diag_prefix}Task: {ctx.task}\n\n{elements_text}"
    else:
        user_msg = budget_hdr + diag_prefix + elements_text

    # Post-tx verification nudge — one-shot.
    if ctx.pending_verification and ctx.mm_popup_active is None:
        user_msg += (
            f"\n\n[POST-ACTION CHECK] The previous click was "
            f"'{ctx.pending_verification['label']}' — a "
            f"{ctx.pending_verification['trigger']} action. Any MetaMask "
            f"popup has closed. Before `done PASS`, verify the "
            f"transaction actually completed on the dApp: look for a "
            f"success toast, updated balance, or tx hash. If you "
            f"cannot see one in the snapshot above, use `look` now."
        )
        ctx.pending_verification = None

    ctx.messages.append({"role": "user", "content": user_msg})

    # History compression (unchanged from the pre-FSM loop).
    if len(ctx.messages) > HISTORY_WINDOW * 2:
        first = ctx.messages[0]
        recent = ctx.messages[-(HISTORY_WINDOW * 2 - 1):]
        old = ctx.messages[1:-(HISTORY_WINDOW * 2 - 1)]
        compressed = []
        for m in old:
            if m["role"] == "assistant":
                compressed.append(m)
            else:
                content = (m["content"] if isinstance(m["content"], str)
                           else str(m["content"]))
                if "\n" in content and len(content) > 200:
                    first_line = content.split("\n")[0]
                    compressed.append({
                        "role": "user",
                        "content": f"{first_line} [page snapshot truncated]",
                    })
                else:
                    compressed.append(m)
        ctx.messages = [first] + compressed + recent

    try:
        resp_text, in_tok, out_tok = ask_llm(
            ctx.access_token, ctx.messages, prompt, image_b64=step_image
        )
    except RuntimeError as e:
        # Provider raised — bad API key, rate limit, transient network,
        # etc. Stop the run with a clear ERROR. Callers can retry at the
        # bench-fixture level (config [budget].retries).
        print(f"  LLM error: {e}")
        ctx.description = f"LLM error: {e}"
        ctx.status = "ERROR"
        ctx.step_record["result"] = f"LLM error: {e}"
        raise

    ctx.total_in += in_tok
    ctx.total_out += out_tok
    ctx.step_record["in_tokens"] += in_tok
    ctx.step_record["out_tokens"] += out_tok
    ctx.messages.append({"role": "assistant", "content": resp_text})
    ctx.resp_text = resp_text
    ctx.send_event(AgentEvent.LLM_REPLIED)


# -----------------------------------------------------------------------
# act_classify — parse the LLM reply, record it, emit one of the PARSED_*
# events to drive the DISPATCHING fork.
# -----------------------------------------------------------------------

_ACTION_TO_EVENT = {
    "look": AgentEvent.PARSED_LOOK,
    "tab":  AgentEvent.PARSED_TAB,
    "error": AgentEvent.PARSED_ERROR,
}


def _aria_role_from_el(el: dict) -> str:
    """Resolve the ARIA-role we should classify the element as.

    Priority: explicit ARIA role attribute > HTML-tag mapping > raw tag.
    Mapping is the conservative subset Playwright's get_by_role accepts:
    `<input type=text>` is `textbox`, `<input type=submit>` is `button`,
    `<select>` is `combobox`, `<a>` is `link`, etc. Without this map
    the miner emits role classifiers like `input` that Playwright
    doesn't recognise — the resulting `click input "name"` selector
    falls through to a CSS-locator interpretation of `input "name"`
    which is malformed and times out at replay.
    """
    role = el.get("role")
    if role:
        return str(role)
    tag = el.get("tag") or "?"
    if tag == "input":
        t = str(el.get("type") or "text").lower()
        if t in ("submit", "button", "image", "reset"):
            return "button"
        if t == "checkbox":
            return "checkbox"
        if t == "radio":
            return "radio"
        # text / email / password / search / tel / url / number etc.
        return "textbox"
    if tag == "textarea":
        return "textbox"
    if tag == "select":
        return "combobox"
    if tag == "a":
        return "link"
    return tag


def _populate_target_role(ctx: AgentCtx) -> None:
    """Resolve the target element's role + accessible name for verbs
    that act on a snapshot id, and stamp them on the current
    step_record. Called from BOTH act_classify (LLM-direct path) and
    _run_vision (post-`look` path), so vision-generated actions get
    the same vocabulary annotation.

    `target_role` feeds the miner vocabulary (alphabet for n-gram
    matching). `target_name` feeds the emit-time selector strategy:
    when every occurrence of a click step targeted the same accessible
    name, emit can produce `click button "name"` instead of role-only
    — significantly more stable against live-replay drift.
    """
    action, args = ctx.action, ctx.args
    if action not in ("click", "type", "select", "hover") or not args:
        return
    try:
        eid = int(args[0])
    except (ValueError, TypeError):
        return
    for el in (ctx.snapshot or {}).get("elements") or []:
        if el.get("id") == eid:
            ctx.step_record["target_role"] = _aria_role_from_el(el)
            # Accessible name candidates, in priority order: visible
            # text > aria-label > placeholder. Truncated to 80 chars
            # so a giant nav element's concatenated text doesn't end
            # up as a baked-in selector.
            name = (
                el.get("text") or el.get("aria-label") or el.get("ph") or ""
            )
            if name:
                ctx.step_record["target_name"] = str(name)[:80]
            return


def act_classify(ctx: AgentCtx) -> None:
    # Online MacroFSM (auto-invoke mode) may have stashed a synthetic
    # action while the LLM was thinking. If so, consume it INSTEAD of
    # parsing the LLM's reply — the macro pre-empts whatever the LLM
    # was about to do this turn. The detector's cooldown / precondition
    # gate ensures this doesn't fire indefinitely.
    auto = getattr(ctx, "macro_auto_action", "")
    if auto:
        ctx.macro_auto_action = ""
        action, args = parse_action(auto)
        if ctx.verbose:
            print(f"  {ctx.label} [macro auto-invoke] {auto[:80]}")
    else:
        action, args = parse_action(ctx.resp_text)
    ctx.action = action
    ctx.args = list(args)
    ctx.step_record["action"] = action
    ctx.step_record["args"] = list(args)
    _populate_target_role(ctx)
    ctx.prev_actions.append(f"{action}:{':'.join(args)}")

    # Parse-error throttle. The agent occasionally drifts into prose
    # ("The screenshot was taken. The DSL snapshot shows..."), the
    # nudge in act_nudge_invalid asks it to retry, but if 3 turns in
    # a row come back as prose the agent isn't going to recover —
    # bail with a forced FAIL instead of burning the whole budget.
    if action == "error":
        ctx.parse_errors += 1
        ctx.signals["parse_errors"] += 1
        if ctx.parse_errors >= 3:
            raw = (ctx.resp_text or "").strip().replace("\n", " ")[:160]
            ctx.args = [
                "FAIL",
                f"3 consecutive parse errors — agent emitted prose "
                f"instead of DSL. Last raw: {raw!r}",
            ]
            ctx.action = "done"
            ctx.send_event(AgentEvent.PARSED_DONE_FAIL)
            return
    else:
        ctx.parse_errors = 0

    if action == "done":
        status = args[0] if args else "PASS"
        if status == "FAIL":
            ctx.send_event(AgentEvent.PARSED_DONE_FAIL)
        else:
            ctx.send_event(AgentEvent.PARSED_DONE_PASS)
        return
    evt = _ACTION_TO_EVENT.get(action, AgentEvent.PARSED_NORMAL)
    ctx.send_event(evt)


# -----------------------------------------------------------------------
# act_evidence_gate — done PASS evidence check. Emits EVIDENCE_OK,
# EVIDENCE_MISS, or REASKS_EXHAUSTED.
# -----------------------------------------------------------------------

def act_evidence_gate(ctx: AgentCtx) -> None:
    status = ctx.args[0] if ctx.args else "PASS"
    description = ctx.args[1] if len(ctx.args) > 1 else ""
    verdict = evidence_verdict(ctx, status, description)
    if verdict == "accept":
        ctx.status = "PASS"
        ctx.description = description
        ctx.step_record["evidence_present"] = True
        ctx.send_event(AgentEvent.EVIDENCE_OK)
    elif verdict == "reask":
        ctx.step_record["done_reasked"] = True
        ctx.step_record["evidence_present"] = False
        ctx.signals["done_reasks"] += 1
        ctx.done_reasks_log.append({
            "step": ctx.step,
            "description": description,
            "reason": _evidence_failure_reason(description),
            "verdict": "reask",
        })
        ctx.send_event(AgentEvent.EVIDENCE_MISS)
    elif verdict == "forced_fail":
        ctx.step_record["done_reasked"] = True
        ctx.step_record["evidence_present"] = False
        ctx.done_reasks_log.append({
            "step": ctx.step,
            "description": description,
            "reason": _evidence_failure_reason(description),
            "verdict": "forced_fail",
        })
        ctx.send_event(AgentEvent.REASKS_EXHAUSTED)
    else:  # "pass_fail" — done FAIL always accepted
        ctx.status = "FAIL"
        ctx.description = description
        ctx.send_event(AgentEvent.EVIDENCE_OK)


def _evidence_failure_reason(description: str) -> str:
    """Best-effort label for WHY evidence_verdict rejected this PASS.

    Inspected categories mirror runtime/evidence.py::has_evidence. The
    label is for humans reading bench logs / MCP results — it doesn't
    feed back into the agent loop.
    """
    if not description:
        return "empty_description"
    if len(description.strip()) < 5:
        return "too_short"
    # quick re-runs of the per-pattern checks for diagnostics only
    from .evidence import (
        EVIDENCE_NUM_NOUN, EVIDENCE_PROPER_NOUN, EVIDENCE_QUOTE,
        EVIDENCE_TXHASH, EVIDENCE_UNIT, EVIDENCE_YEAR,
        _content_words_count,
    )
    misses: list[str] = []
    if not EVIDENCE_QUOTE.search(description):
        misses.append("no_quoted_text")
    if not EVIDENCE_TXHASH.search(description):
        misses.append("no_tx_hash")
    if not EVIDENCE_UNIT.search(description):
        misses.append("no_number_unit")
    if not EVIDENCE_PROPER_NOUN.search(description):
        misses.append("no_proper_noun")
    if not EVIDENCE_YEAR.search(description):
        misses.append("no_year")
    if len(EVIDENCE_NUM_NOUN.findall(description)) < 2:
        misses.append("no_num_noun_pair")
    if _content_words_count(description) < 4:
        misses.append("narrative_too_thin")
    return "all_checks_failed: " + ",".join(misses) if misses else "unknown"


# -----------------------------------------------------------------------
# Terminal-emitting actions — print the final line, mark step_record.
# The FSM table routes these to terminal states (DONE_PASS / DONE_FAIL),
# so no event emit is needed.
# -----------------------------------------------------------------------

def act_emit_done_pass(ctx: AgentCtx) -> None:
    ctx.status = "PASS"
    description = ctx.description or (ctx.args[1] if len(ctx.args) > 1 else "")
    print(f"  {ctx.label} DONE PASS: {description}")
    ctx.step_record["result"] = f"DONE PASS: {description}"
    _emit_step(ctx)


def act_emit_done_fail_direct(ctx: AgentCtx) -> None:
    """PARSED_DONE_FAIL path — agent emergency aborted."""
    ctx.status = "FAIL"
    ctx.description = ctx.args[1] if len(ctx.args) > 1 else ""
    print(f"  {ctx.label} DONE FAIL: {ctx.description}")
    ctx.step_record["result"] = f"DONE FAIL: {ctx.description}"
    _emit_step(ctx)


def act_emit_done_forced_fail(ctx: AgentCtx) -> None:
    """REASKS_EXHAUSTED path — too many done-PASS reasks."""
    last = ctx.args[1] if len(ctx.args) > 1 else ""
    ctx.status = "FAIL"
    ctx.description = (
        f"done PASS rejected {ctx.done_reasks}x — no concrete "
        f"evidence provided. Last claim: {last!r}"
    )
    print(f"  {ctx.label} FORCED FAIL: {ctx.description}")
    ctx.step_record["result"] = ctx.description
    _emit_step(ctx)


def act_emit_hard_fail(ctx: AgentCtx) -> None:
    """HARD_LOOP path — oscillation detected."""
    ctx.status = "FAIL"
    ctx.description = (
        f"Hard loop: action '{ctx.action}' repeated or oscillating"
    )
    print(f"  {ctx.label} FORCED FAIL: {ctx.description}")
    ctx.step_record["loop_hit"] = "hard"
    ctx.step_record["result"] = ctx.description
    _emit_step(ctx)


# -----------------------------------------------------------------------
# Reask / nudge / invalid — these all append a message, bump step,
# start a new snapshot cycle via SNAPSHOT_READY on next iteration. We
# emit START to trigger act_new_step (which will close the current
# step_record and open a new one).
# -----------------------------------------------------------------------

def act_reask_done(ctx: AgentCtx) -> None:
    description = ctx.args[1] if len(ctx.args) > 1 else ""
    print(f"  {ctx.label} REJECTED done PASS (no evidence): {description!r}")
    ctx.messages.append({"role": "user", "content": DONE_REASK_MSG})
    ctx.step_record["result"] = "REJECTED done PASS (no evidence)"
    _emit_step(ctx)
    ctx.send_event(AgentEvent.START)


def act_nudge_invalid(ctx: AgentCtx) -> None:
    print(f"  {ctx.label} parse error: {ctx.args[0] if ctx.args else ''}")
    if ctx.verbose:
        print(f"    raw: {ctx.resp_text[:200]}")
    ctx.messages.append({
        "role": "user",
        "content": "Invalid action. Respond with exactly one action line.",
    })
    ctx.step_record["result"] = (
        f"parse error: {ctx.args[0] if ctx.args else ''}"
    )
    _emit_step(ctx)
    ctx.send_event(AgentEvent.START)


def act_append_blocked_nudge(ctx: AgentCtx) -> None:
    print(f"  {ctx.label} BLOCKED {ctx.action}: MM popup still open")
    try:
        ctx.page = ctx.mm_popup_active
        ctx.page.bring_to_front()
    except Exception:
        pass
    ctx.messages.append({
        "role": "user",
        "content": (
            "BLOCKED: A MetaMask popup is still open. You MUST "
            "click Confirm / Approve / Sign or Reject / Cancel "
            "INSIDE the popup before you can use tab, goto, or "
            "done. The next snapshot will show the popup's "
            "buttons — pick the correct one."
        ),
    })
    ctx.step_record["blocked"] = "mm_popup"
    ctx.step_record["result"] = f"BLOCKED {ctx.action}: MM popup still open"
    _emit_step(ctx)
    ctx.send_event(AgentEvent.START)


# -----------------------------------------------------------------------
# act_switch_tab — `tab N` DSL action. Picks a page, brings to front.
# -----------------------------------------------------------------------

def act_switch_tab(ctx: AgentCtx) -> None:
    tab_idx = (
        int(ctx.args[0]) if ctx.args and ctx.args[0].isdigit() else 0
    )
    pages = ctx.context.pages
    if 0 <= tab_idx < len(pages):
        ctx.page = pages[tab_idx]
        ctx.page.bring_to_front()
        print(f"  {ctx.label} tab {tab_idx} -> {ctx.page.url[:60]}")
        ctx.step_record["result"] = (
            f"tab {tab_idx} -> {ctx.page.url[:60]}"
        )
    else:
        print(f"  {ctx.label} tab {tab_idx} "
              f"(invalid, {len(pages)} tabs open)")
        tab_list = "\n".join(
            f"  tab {i}: {pg.url[:80]}" for i, pg in enumerate(pages)
        )
        ctx.messages.append({
            "role": "user",
            "content": f"Invalid tab. Open tabs:\n{tab_list}",
        })
        ctx.step_record["result"] = f"invalid tab {tab_idx}"
    _emit_step(ctx)
    ctx.send_event(AgentEvent.START)


# -----------------------------------------------------------------------
# act_loop_check — classify oscillation via the helper and emit
# HARD_LOOP / SOFT_LOOP / NO_LOOP.
# -----------------------------------------------------------------------

def act_loop_check(ctx: AgentCtx) -> None:
    kind = loop_check(ctx, ctx.action)
    if kind == "hard":
        ctx.send_event(AgentEvent.HARD_LOOP)
    elif kind == "soft":
        ctx.step_record["loop_hit"] = "soft"
        ctx.signals["soft_loops"] += 1
        ctx.send_event(AgentEvent.SOFT_LOOP)
    else:
        ctx.send_event(AgentEvent.NO_LOOP)


# -----------------------------------------------------------------------
# act_vision — look DSL handler. Re-asks LLM with a screenshot + snapshot.
# The new (action, args) go through the PARSED_* pipeline again, so the
# vision answer is just another classification cycle.
# -----------------------------------------------------------------------

def _run_vision(ctx: AgentCtx, reason: str) -> None:
    from ..agent import ANDROID_SYSTEM_PROMPT, SYSTEM_PROMPT
    prompt = (ANDROID_SYSTEM_PROMPT
              if getattr(ctx, "driver_kind", "browser") == "android"
              else SYSTEM_PROMPT)

    ctx.step_record["vision"] = True
    # Fresh snapshot for vision — the page may have changed since the
    # main SNAPSHOTTING pass.
    ctx.snapshot = snapshot_page(ctx)
    try:
        action, args, resp_text = vision_retry(
            ctx, ctx.messages, prompt, ctx.step_record,
            ctx.snapshot["elements_text"],
            is_fallback=ctx.snapshot["is_fallback"],
            reason=reason,
        )
    except Exception as e:
        if ctx.verbose:
            print(f"    vision failed: {e}")
        ctx.step_record["result"] = f"vision failed: {e}"
        _emit_step(ctx)
        ctx.send_event(AgentEvent.START)   # try again next step
        return

    ctx.action = action
    ctx.args = list(args)
    ctx.resp_text = resp_text
    # Same target_role annotation as act_classify — without this the
    # miner vocabulary gets `type:_` for vision-path actions and
    # `type:input` for direct ones, splitting one logical token in two.
    _populate_target_role(ctx)
    if ctx.verbose:
        print(f"    vision decided: {resp_text.strip()}")

    # Vision-stuck break. Loop-vision is supposed to break stalls by
    # picking a *different* action when the agent is repeating itself.
    # If vision keeps returning the same action across consecutive
    # forced-vision invocations, we're not breaking the stall — we're
    # just burning steps. Force FAIL so the operator sees the truth.
    if reason == "loop":
        cur = f"{action}:{':'.join(args)}"
        if cur == ctx.last_vision_act:
            ctx.vision_repeat += 1
            ctx.signals["vision_repeats"] += 1
        else:
            ctx.vision_repeat = 1
            ctx.last_vision_act = cur
        if ctx.vision_repeat >= 2 and action != "done":
            ctx.args = [
                "FAIL",
                f"Vision stuck: returned `{cur}` "
                f"{ctx.vision_repeat}× under loop-vision. Page state "
                f"is not advancing.",
            ]
            ctx.action = "done"
            print(
                f"  {ctx.label} VISION STUCK: `{cur}` repeated "
                f"{ctx.vision_repeat}×, forcing FAIL"
            )
            ctx.send_event(AgentEvent.PARSED_DONE_FAIL)
            return

    # Cross-check: vision sometimes hallucinates element ids ("click 99
    # to expand the alert" when 99 isn't on the page). The DSL snapshot
    # is ground truth for what's actionable — reject any id-bearing
    # vision action whose id isn't in the snapshot, and feed the LLM
    # a list of valid ids so it can correct itself.
    if action in ("click", "type", "select", "hover") and args:
        try:
            eid = int(args[0])
        except (ValueError, TypeError):
            eid = None
        if eid is not None:
            elements = (ctx.snapshot or {}).get("elements") or []
            valid_ids = sorted({int(e["id"]) for e in elements
                                if isinstance(e.get("id"), int)})
            if eid not in valid_ids:
                shown = ", ".join(str(x) for x in valid_ids[:30])
                if len(valid_ids) > 30:
                    shown += f", ... (+{len(valid_ids) - 30} more)"
                ctx.step_record["vision_hallucinated"] = {
                    "action": action, "id": eid, "valid_ids": valid_ids,
                }
                ctx.signals["hallucinated_ids"] += 1
                ctx.messages.append({
                    "role": "user",
                    "content": (
                        f"REJECTED: vision returned `{action} {eid}` but id "
                        f"{eid} is NOT in the current page snapshot. The "
                        f"snapshot has these ids: [{shown}]. Either pick a "
                        f"real id from the snapshot or `done FAIL` if the "
                        f"target genuinely isn't on the page."
                    ),
                })
                ctx.step_record["result"] = (
                    f"vision rejected: hallucinated id {eid} "
                    f"(valid: {len(valid_ids)} ids)"
                )
                if ctx.verbose:
                    print(f"    vision rejected: id {eid} not in snapshot")
                _emit_step(ctx)
                ctx.send_event(AgentEvent.START)
                return

    # Re-append to prev_actions so soft-loop detection sees the new action.
    if reason == "loop":
        ctx.prev_actions.append(f"{action}:{':'.join(args)}")

    # Route to the same PARSED_* events.
    if action == "done":
        status = args[0] if args else "PASS"
        if status == "FAIL":
            ctx.send_event(AgentEvent.PARSED_DONE_FAIL)
        else:
            ctx.send_event(AgentEvent.PARSED_DONE_PASS)
        return
    if action in ("look", "screenshot"):
        # The vision told us to `look` again — just loop back to a fresh
        # snapshot next step. Inline re-vision risks infinite recursion.
        ctx.step_record["result"] = f"vision -> {action}"
        _emit_step(ctx)
        ctx.send_event(AgentEvent.START)
        return
    evt = _ACTION_TO_EVENT.get(action, AgentEvent.PARSED_NORMAL)
    ctx.send_event(evt)


def act_vision_look(ctx: AgentCtx) -> None:
    print(f"  {ctx.label} look (vision)")
    _run_vision(ctx, reason="look")


def act_vision_forced(ctx: AgentCtx) -> None:
    if ctx.verbose:
        print("  [loop detected → auto-vision]")
    _run_vision(ctx, reason="loop")


# -----------------------------------------------------------------------
# act_mm_guard — MetaMask popup escape guard. Emits MM_BLOCKED if a
# popup is active and the agent is trying to tab/goto/done-PASS away.
# -----------------------------------------------------------------------

def act_mm_guard(ctx: AgentCtx) -> None:
    is_done_fail = (
        ctx.action == "done" and ctx.args and ctx.args[0] == "FAIL"
    )
    if (ctx.mm_popup_active is not None and not is_done_fail
            and ctx.action in ("tab", "goto", "done")):
        ctx.send_event(AgentEvent.MM_BLOCKED)
    else:
        ctx.send_event(AgentEvent.MM_NOT_BLOCKED)


# -----------------------------------------------------------------------
# act_exec — run the parsed DSL action. Handles tx-trigger arming and
# MM popup detection post-click. Always emits START (advance to the
# next step); action errors are stringified into ctx.last_result and
# fed back to the LLM rather than terminating.
# -----------------------------------------------------------------------

def _print_action_line(ctx: AgentCtx, elements: list) -> None:
    if ctx.action in ("click", "type", "select", "hover") and ctx.args:
        print(f"  {ctx.label} {ctx.action} -> {_el_info(elements, ctx.args[0])}")
    else:
        print(f"  {ctx.label} {ctx.action} {' '.join(ctx.args)}")


def _find_metamask_popup(context) -> Any:
    """Return an actionable MM notification page, or None."""
    for pg in context.pages:
        try:
            if pg.is_closed():
                continue
            if "chrome-extension://" not in pg.url:
                continue
            pg.wait_for_load_state("domcontentloaded", timeout=2000)
            body = pg.inner_text("body", timeout=2000)
            if has_mm_action(body):
                return pg
        except Exception:
            pass
    return None


def act_exec(ctx: AgentCtx) -> None:
    elements = ctx.snapshot["elements"]
    is_fallback = ctx.snapshot["is_fallback"]
    _print_action_line(ctx, elements)

    # Pre-action screenshot — captures the page state the agent is about
    # to act upon. Combined with the post-action shot in _emit_step this
    # gives a clean before/after pair per step. Errors swallowed; the
    # post-action shot will still get written by _emit_step regardless.
    if ctx.screenshots_dir is not None:
        kind = getattr(ctx, "driver_kind", "browser")
        try:
            if kind == "android" and ctx.android_device is not None:
                pre = ctx.screenshots_dir / f"step_{ctx.step:03d}_pre.png"
                ctx.android_device.screenshot(str(pre))
            elif kind == "browser" and ctx.page is not None:
                pre = ctx.screenshots_dir / f"step_{ctx.step:03d}_pre.jpg"
                ctx.page.screenshot(
                    path=str(pre), type="jpeg", quality=60,
                    full_page=True, timeout=3000,
                )
            else:
                pre = None
            if pre is not None:
                pre_str = str(pre)
                ctx.step_record["screenshot_pre"] = pre_str
                ctx.screenshots.append(pre_str)
        except Exception:
            pass

    # Android driver path: uiautomator2 dispatch; no MM popup / tx-trigger
    # handling (browser-only concerns). Feed errors back to the LLM and
    # advance to the next step exactly like the browser path does.
    if getattr(ctx, "driver_kind", "browser") == "android":
        from ..android import execute_action as execute_action_android
        result = execute_action_android(
            ctx.android_device, ctx.action, ctx.args, elements,
        )
        ctx.last_result = result
        ctx.step_record["result"] = result
        if ctx.verbose:
            print(f"    {result}")
        if result.startswith(("TIMEOUT:", "ERROR:")):
            ctx.messages.append({"role": "user", "content": result})
        _emit_step(ctx)
        ctx.send_event(AgentEvent.START)
        return

    result = execute_action(
        ctx.page, ctx.action, ctx.args, elements, is_fallback
    )
    ctx.last_result = result
    ctx.step_record["result"] = result
    if ctx.verbose:
        print(f"    {result}")

    # Mark successful macro execution on ctx so MacroFSM's detection
    # passes can suppress re-triggering the same macro within the
    # same run. State-delta gating (S2): if the macro reported
    # `[page-state unchanged]`, all its sub-steps PASSed but the
    # page didn't actually move (rejected login, dead button click,
    # etc.) — DON'T success-lock, leave room for retry with
    # different params. Without this carve-out a macro that types
    # invalid creds on a login page would block forever; agent
    # could never recover.
    if (ctx.action == "macro" and ctx.args
            and result.startswith("macro '") and " OK:" in result
            and "[page-state unchanged]" not in result):
        ctx.macro_succeeded_names.add(ctx.args[0])

    # Drain MutationObserver buffer and detect flicker. We give the page
    # 200ms to settle so async re-renders right after a click land in the
    # buffer before we read it. Flicker entries that emerge here go onto
    # ctx.flicker_log; _emit_step's slice picks them up for this step.
    try:
        ctx.page.wait_for_timeout(200)
        events = detect_flicker(ctx.page)
        for ev in events:
            ctx.flicker_log.append(ev)
        if events:
            ctx.signals["flicker"] += len(events)
    except Exception:
        pass

    # Tx-trigger detection.
    if (ctx.action == "click" and ctx.args
            and not result.startswith(("TIMEOUT:", "ERROR:"))):
        try:
            el_label = _el_info(elements, ctx.args[0])
        except Exception:
            el_label = ""
        from .tx_trigger import is_tx_trigger
        trigger = is_tx_trigger(el_label)
        if trigger:
            on_tx_trigger(ctx, trigger, el_label)
            if ctx.verbose:
                print(f"    [tx trigger '{trigger}' armed]")

    # MM popup detection after click when MM extension is loaded.
    if ctx.action == "click" and ctx.extensions:
        from ..browser import _find_metamask_id
        ext_page = None
        for attempt in range(2):
            ctx.page.wait_for_timeout(1500 if attempt == 0 else 2000)
            ext_page = _find_metamask_popup(ctx.context)
            if ext_page:
                break
            # Fallback: MM sometimes delays opening the popup tab — try
            # loading notification.html directly to probe.
            mm_id = _find_metamask_id(ctx.context)
            if mm_id:
                probe = None
                try:
                    probe = ctx.context.new_page()
                    probe.goto(
                        f"chrome-extension://{mm_id}/notification.html",
                        timeout=5000, wait_until="domcontentloaded",
                    )
                    probe.wait_for_timeout(1500)
                    body = probe.inner_text("body", timeout=2000)
                    if has_mm_action(body):
                        ext_page = probe
                        break
                    probe.close()
                except Exception:
                    if probe is not None:
                        try:
                            probe.close()
                        except Exception:
                            pass
        if ext_page:
            # Auto-unlock if needed.
            try:
                body = ext_page.inner_text("body", timeout=2000)
                if "Разблокировать" in body or "Unlock" in body:
                    if ctx.verbose:
                        print("    [auto-unlocking MetaMask...]")
                    pwd_loc = ext_page.locator(
                        "input[type='password']"
                    ).first
                    if pwd_loc.is_visible(timeout=2000):
                        pwd_loc.click(timeout=2000)
                        pwd_loc.type(TEST_PASSWORD, delay=20)
                        ext_page.wait_for_timeout(300)
                        for btn_sel in (
                            "button[data-testid='unlock-submit']",
                            "button:has-text('Разблокировать')",
                            "button:has-text('Unlock')",
                        ):
                            try:
                                btn = ext_page.locator(btn_sel).first
                                if btn.is_visible(timeout=500):
                                    btn.click(timeout=3000)
                                    break
                            except Exception:
                                continue
                        ext_page.wait_for_timeout(2000)
                        body2 = ext_page.inner_text("body", timeout=2000)
                        if ctx.verbose:
                            print(f"    [after unlock: {body2[:60]}]")
                        if not has_mm_action(body2):
                            if ctx.verbose:
                                print("    [no pending MM request, "
                                      "staying on dApp]")
                            ext_page.close()
                            ext_page = None
            except Exception as e:
                if ctx.verbose:
                    print(f"    [auto-unlock failed: {e}]")
        if ext_page:
            ctx.page = ext_page
            ctx.page.bring_to_front()
            on_popup_opened(ctx, ext_page)
            if ctx.verbose:
                print(f"    [extension popup: {ctx.page.url[:60]}]")
            ctx.messages.append({
                "role": "user",
                "content": (
                    f"MetaMask popup opened: {ctx.page.url[:80]}\n"
                    f"If it asks for password, use: {TEST_PASSWORD}\n"
                    f"You MUST click Confirm/Approve/Sign or "
                    f"Reject/Cancel INSIDE this popup now. `tab`, "
                    f"`goto`, and `done` are BLOCKED until the popup "
                    f"closes — there is no escape."
                ),
            })

    # Feed errors back to the LLM.
    if result.startswith(("TIMEOUT:", "ERROR:")):
        ctx.messages.append({"role": "user", "content": result})
    # `evaluate` results MUST reach the LLM — that's the whole point of
    # the action. Without this the agent would fly blind on the next
    # turn, having asked a question and never seeing the answer.
    elif ctx.action == "evaluate" and result.startswith(
        ("eval -> ", "EVAL_ERROR:", "EVAL_THROW:")
    ):
        ctx.messages.append({"role": "user", "content": result})
    # `macro` results similarly — without this, the agent sees the
    # post-macro page state cold and can't correlate it to the macro
    # that just ran. Critical for auto-invocation: agent needs to
    # know "login_with_credentials just completed, you're on inventory"
    # to skip redoing the login.
    elif ctx.action == "macro":
        ctx.messages.append({"role": "user", "content": result})

    _emit_step(ctx)
    ctx.send_event(AgentEvent.START)   # advance to the next step
