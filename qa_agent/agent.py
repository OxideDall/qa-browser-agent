"""Main agent loop: a thin wrapper that drives the FSM dispatcher.

Phase 3c: run_task's job is now (1) set up the browser + ctx, (2) kick
off the AgentFSM with the START event, (3) let the dispatcher drain the
event queue until a terminal state is reached, (4) emit the final
record and tear down. The per-step dispatch logic lives in
qa_agent/runtime/{fsm,fsm_actions,transitions,states}.py.
"""

import os
import re
import time
from typing import Callable

from playwright.sync_api import Page, sync_playwright

from .browser import _launch_browser
from .config import NAV_TIMEOUT, STEP_TIMEOUT


SYSTEM_PROMPT = """QA browser agent. Snapshot → one action. No prose.

## Page DSL
@ Title | url
<id> <tag> "text" [placeholder] ->/href ="selected" + !disabled r:role @section

Tags: a link, btn button, in.email/.password/.text input, sel select, txt textarea
Flags: + checked, ! disabled, -> href, @ section, r: ARIA role
Text: # h1 / ## h2 / ### h3 / | body

## Actions (one per reply, no markdown)
click <id>
type <id> "text"
select <id> "option"
hover <id>
scroll up|down
press <key>       — Enter | Escape | Tab | ArrowUp/Down/Left/Right | Backspace
goto <url>
wait <ms>
look              — annotated screenshot
screenshot        — save to disk
tab <n>           — switch tab (0-indexed)
done PASS|FAIL "why"

## Rules
1. Element missing → scroll down or wait 500.
2. Stuck 3 turns → done FAIL.
3. Forms: type fields → click submit, OR `press Enter` to submit from input.
4. ABAB loop (open/close modal etc.) = stuck. Different action or done FAIL.
5. Do NOT pre-click input fields. `type <id> "text"` already focuses + types in one step. Pre-clicking each field wastes steps and is a common trap on multi-field forms (clicking without typing leaves the field empty and you end up submitting a blank form).
6. First turn: trust the snapshot. Do NOT call `look` unless the DSL list is empty or the page is non-interactive. Vision costs ~5× more tokens than a DSL snapshot.

## MM popup
Open → MUST click Confirm/Approve/Sign or Cancel INSIDE it.
tab/goto/done PASS BLOCKED till popup closes. done FAIL allowed as abort.

## TX triggers
Supply/Borrow/Repay/Withdraw/Swap/Stake/Send/Deposit/Claim/Mint/Bridge/
Approve/Sign/Confirm → before done PASS verify BOTH:
  (a) MM popup closed
  (b) dApp shows success (toast / receipt / updated balance / tx hash)
Unsure → look.

## done PASS evidence
MUST cite: inner quoted UI text (≥5 chars) OR tx hash 0x...
OK:  done PASS 'toast: "Supply complete"'
OK:  done PASS "tx 0xabc123def received"
BAD: done PASS "successful" / "completed" / "done" / "works"  (no source → REJECTED)"""


ANDROID_SYSTEM_PROMPT = """QA Android agent. Snapshot → one action. No prose.

## Screen DSL
@ package / activity
<id> <tag> "text" (content-desc) #resource-id [in:text]

Tags: btn button, in EditText, txt TextView, img ImageView,
      chk checkbox, sw switch, rad radio, list RecyclerView/ViewPager, view other
Only interactive nodes (clickable / long-clickable / focusable / editable)
are listed. The first line shows the current foreground app.

## Actions (one per reply, no markdown)
click <id>                    — `click 5` (NOT `click [5]`). Integer id, no brackets.
type <id> "text"              — `type 5 "отвёртка"`. Focuses EditText and types.
scroll up|down                — half-screen swipe in the centre column
press <key>                   — back | home | menu | enter | search
wait <ms>
look                          — annotated screenshot
screenshot                    — save to disk
done PASS|FAIL "why"

NOT SUPPORTED on Android: goto, tab, hover, select. Use `press back` to
leave an activity.

## Rules
1. Element missing → scroll down or wait 500.
2. Stuck 3 turns → done FAIL.
3. `type <id> "text"` already focuses + types. Then press Enter or click
   a submit-like button.
4. ABAB loop = stuck. Different action or done FAIL.
5. First turn: trust the snapshot. Use `look` only when the DSL is empty
   or the page is clearly media-heavy (icon grids with no text).
6. You're locked inside the target app — if you end up in Settings or
   the launcher, that's wrong: `press back` and retry.

## done PASS evidence
MUST cite a concrete UI string (≥5 chars) from the current snapshot —
inner-quoted text that's actually on the screen, a number+unit pair
(e.g. "299 ₽"), a product title, or a resource-id-anchored value.
OK:  done PASS 'toast: "Заказ оформлен"'
OK:  done PASS "top card: Отвёртка крестовая — 199 ₽"
BAD: done PASS "search worked" / "found results" (no source → REJECTED)"""


from .runtime.ctx import AgentCtx  # noqa: E402
from .runtime.fsm import FSM  # noqa: E402
from .runtime.states import AgentEvent, AgentState  # noqa: E402
from .runtime.transitions import AGENT_TRANSITIONS  # noqa: E402


def run_task(task: str, url: str | None, headless: bool, verbose: bool,
             max_steps: int,
             extensions: list[str] | None = None,
             init_script: str | None = None,
             on_step: Callable[[dict], None] | None = None,
             on_finish: Callable[[dict], None] | None = None,
             before_close: Callable[[Page, "object"], None] | None = None,
             profile_dir=None,
             ) -> tuple[str, str, int]:
    """Run a QA task end-to-end. Returns (status, description, steps_used).

    `init_script` (optional JS source) is injected via `add_init_script`
    before any navigation so runs can pre-populate localStorage/sessionStorage
    for an auth session without walking the login UI.

    `on_step(record)` fires once per loop iteration with a structured dict
    (action, args, result, in/out tokens, latency_ms, page_url, mm_active,
    loop_hit, blocked, done_reasked, evidence_present). Used by the bench
    runner; recorder exceptions are swallowed so instrumentation can never
    break a run. `on_finish(summary)` fires after the loop exits with the
    aggregate run record. `before_close(page, context)` fires right before
    Playwright tears down — used by bench fixtures to assert against the
    live DOM / localStorage / open tabs.
    """
    ctx = AgentCtx(
        task=task, url=url, headless=headless, verbose=verbose,
        max_steps=max_steps,
        extensions=extensions, init_script=init_script,
        profile_dir=profile_dir,
        on_step=on_step, on_finish=on_finish, before_close=before_close,
        t_start=time.time(),
    )

    with sync_playwright() as p:
        ctx.context, ctx.page, _has_browser = _launch_browser(
            p, headless, extensions, init_script=init_script,
            profile_dir=profile_dir,
        )
        ctx.page.set_default_timeout(STEP_TIMEOUT)

        # Track new popup/tab pages (MetaMask opens approval popups).
        _new_pages: list[Page] = []
        ctx.context.on("page", lambda pg: _new_pages.append(pg))

        start_url = url
        if not start_url:
            m = re.search(r"https?://[^\s,\"']+", task)
            if m:
                start_url = m.group()
        if start_url:
            if verbose:
                print(f"  -> {start_url}")
            ctx.page.goto(start_url, timeout=NAV_TIMEOUT,
                          wait_until="domcontentloaded")

        # Phase-3c: the FSM replaces the old 400-line for-loop. Build it,
        # hook ctx.send_event, kick off with START. All further transitions
        # are driven by events that actions emit through ctx.send_event;
        # FSM.send() drains its queue until a terminal state is reached
        # (DONE_PASS / DONE_FAIL / ERROR) or the queue empties.
        fsm = FSM("agent", AgentState.IDLE, AGENT_TRANSITIONS, ctx)
        ctx.send_event = fsm.send
        try:
            fsm.send(AgentEvent.START)
        except Exception as e:
            # Unrecoverable crash during an FSM action — fall through to
            # cleanup with best-effort error reporting.
            if verbose:
                print(f"  FSM crashed: {type(e).__name__}: {e}")
            if not ctx.description:
                ctx.description = f"crash: {type(e).__name__}: {e}"
            if ctx.status not in ("PASS", "FAIL"):
                ctx.status = "ERROR"

        # Map terminal state → ctx.status for the return tuple. Terminal
        # actions (act_emit_done_pass / _fail / _forced_fail / _hard_fail)
        # already set ctx.status; this is the defensive path that covers
        # ERROR transitions (budget exhaustion, raise in action) where
        # ctx.status wasn't explicitly set by the action.
        if fsm.state is AgentState.DONE_PASS and ctx.status != "PASS":
            ctx.status = "PASS"
        elif fsm.state is AgentState.DONE_FAIL and ctx.status not in ("FAIL", "ERROR"):
            ctx.status = "FAIL"

        elapsed = time.time() - ctx.t_start

        # Emit final summary BEFORE before_close so the assert hook can read
        # the recorded result. before_close still has live page+context.
        if on_finish:
            try:
                on_finish({
                    "t": "result",
                    "status": ctx.status,
                    "description": ctx.description,
                    "steps_used": ctx.step,
                    "wall_seconds": elapsed,
                    "total_in": ctx.total_in,
                    "total_out": ctx.total_out,
                    "max_steps": max_steps,
                })
            except Exception:
                pass

        # Asserts that need live page state run here, before close.
        if before_close:
            try:
                before_close(ctx.page, ctx.context)
            except Exception as e:
                if verbose:
                    print(f"  [before_close hook failed: {e}]")

        ctx.context.close()

    print(f"\n{'='*50}")
    print(f"  Result: {ctx.status}")
    print(f"  {ctx.description}")
    print(f"  Steps: {ctx.step}/{max_steps} | Time: {elapsed:.1f}s")
    print(f"  Tokens: {ctx.total_in} in / {ctx.total_out} out")
    print(f"  Provider: {os.environ.get('LLM_PROVIDER', 'anthropic')}")
    print(f"{'='*50}")

    return ctx.status, ctx.description, ctx.step


def run_android_task(task: str, package: str | None, *,
                     serial: str | None = None,
                     verbose: bool = False,
                     max_steps: int = 30,
                     stop_app_first: bool = True,
                     on_step: Callable[[dict], None] | None = None,
                     on_finish: Callable[[dict], None] | None = None,
                     before_close: Callable[[object, object], None] | None = None,
                     ) -> tuple[str, str, int]:
    """Android counterpart of `run_task`. Drives the same FSM but via
    uiautomator2 instead of Playwright.

    Shape of the flow:
      1. `u2.connect(serial)` — assumes `adb connect <serial>` is done.
      2. Optionally `stop + start` the target `package` so the run begins
         from a known state. If `package` is None, the caller is expected
         to have put the phone in the right place already.
      3. Stand up `AgentCtx` with `driver_kind="android"` and kick off the
         FSM the same way `run_task` does.
      4. `before_close(device, None)` fires right before the function
         returns so bench asserts can probe the live UI hierarchy.

    Returns (status, description, steps_used) — identical contract.
    """
    from .android import DEFAULT_SERIAL, connect_device

    serial = serial or DEFAULT_SERIAL

    ctx = AgentCtx(
        task=task, url=None, headless=True, verbose=verbose,
        max_steps=max_steps,
        extensions=None, init_script=None, profile_dir=None,
        on_step=on_step, on_finish=on_finish, before_close=before_close,
        t_start=time.time(),
        driver_kind="android",
    )

    device = connect_device(serial)
    ctx.android_device = device

    # Wake + unlock up-front. The phone is on a dev keyguard without a
    # PIN, so `unlock()` + a fallback upward swipe reliably lands on the
    # home screen (or the previously-active app if it wasn't fully stopped).
    try:
        device.screen_on()
        device.unlock()
    except Exception as e:
        if verbose:
            print(f"  [unlock attempt failed: {e}]")
    try:
        sw, sh = device.window_size()
        device.swipe(sw // 2, int(sh * 0.9), sw // 2, int(sh * 0.3), duration=0.2)
    except Exception:
        pass
    time.sleep(0.6)

    if package:
        if verbose:
            print(f"  -> launching {package} (stop_first={stop_app_first})")
        try:
            device.app_start(package, stop=stop_app_first)
            # Give Android a moment to surface the first drawable activity.
            time.sleep(2.5)
        except Exception as e:
            ctx.description = f"app_start failed: {type(e).__name__}: {e}"
            ctx.status = "ERROR"
            if on_finish:
                try:
                    on_finish({
                        "t": "result", "status": "ERROR",
                        "description": ctx.description,
                        "steps_used": 0,
                        "wall_seconds": time.time() - ctx.t_start,
                        "total_in": 0, "total_out": 0,
                        "max_steps": max_steps,
                    })
                except Exception:
                    pass
            return ctx.status, ctx.description, 0

    fsm = FSM("agent", AgentState.IDLE, AGENT_TRANSITIONS, ctx)
    ctx.send_event = fsm.send
    try:
        fsm.send(AgentEvent.START)
    except Exception as e:
        if verbose:
            print(f"  FSM crashed: {type(e).__name__}: {e}")
        if not ctx.description:
            ctx.description = f"crash: {type(e).__name__}: {e}"
        if ctx.status not in ("PASS", "FAIL"):
            ctx.status = "ERROR"

    if fsm.state is AgentState.DONE_PASS and ctx.status != "PASS":
        ctx.status = "PASS"
    elif fsm.state is AgentState.DONE_FAIL and ctx.status not in ("FAIL", "ERROR"):
        ctx.status = "FAIL"

    elapsed = time.time() - ctx.t_start

    if on_finish:
        try:
            on_finish({
                "t": "result",
                "status": ctx.status,
                "description": ctx.description,
                "steps_used": ctx.step,
                "wall_seconds": elapsed,
                "total_in": ctx.total_in,
                "total_out": ctx.total_out,
                "max_steps": max_steps,
            })
        except Exception:
            pass

    if before_close:
        try:
            before_close(device, None)
        except Exception as e:
            if verbose:
                print(f"  [before_close hook failed: {e}]")

    print(f"\n{'='*50}")
    print(f"  Result: {ctx.status}")
    print(f"  {ctx.description}")
    print(f"  Steps: {ctx.step}/{max_steps} | Time: {elapsed:.1f}s")
    print(f"  Tokens: {ctx.total_in} in / {ctx.total_out} out")
    print(f"  Provider: {os.environ.get('LLM_PROVIDER', 'anthropic')}")
    print(f"{'='*50}")

    return ctx.status, ctx.description, ctx.step
