"""Main agent loop: a thin wrapper that drives the FSM dispatcher.

Phase 3c: run_task's job is now (1) set up the browser + ctx, (2) kick
off the AgentFSM with the START event, (3) let the dispatcher drain the
event queue until a terminal state is reached, (4) emit the final
record and tear down. The per-step dispatch logic lives in
qa_agent/runtime/{fsm,fsm_actions,transitions,states}.py.
"""

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from playwright.sync_api import Page, sync_playwright

from .browser import _launch_browser
from .config import NAV_TIMEOUT, SCREENSHOT_DIR, STEP_TIMEOUT


# ---------------------------------------------------------------------------
# Capture writer — Phase 0 of the macro pipeline.
#
# Every run automatically writes a JSONL trace to
#   ~/.config/qa_agent/captures/{browser|tagged}/<run_id>.jsonl
# unless `QA_DISABLE_CAPTURE=1` in the environment. The format is:
#   {"t": "start", task, url, max_steps, ts, mode}
#   {"t": "step", ...}                — one per loop iteration
#   {"t": "result", ...}              — final summary
# Step records carry pre_signature / post_signature so the offline
# miner can bucket steps by template + diff effectiveness without
# replaying anything.
# ---------------------------------------------------------------------------

CAPTURES_ROOT = Path.home() / ".config" / "qa_agent" / "captures"


class _Capture:
    """Append-only JSONL writer. Tolerates anything — instrumentation
    must never break a run, so all errors are swallowed.

    Honours `QA_CAPTURES_DIR` env override for the root path; useful
    for bench / CI scenarios that want isolated capture archives.
    """

    def __init__(self, kind: str, run_id: str):
        if os.environ.get("QA_DISABLE_CAPTURE") == "1":
            self.disabled = True
            self.path = None
            self._fh = None
            return
        self.disabled = False
        try:
            override = os.environ.get("QA_CAPTURES_DIR")
            base = Path(override) if override else CAPTURES_ROOT
            root = base / kind
            root.mkdir(parents=True, exist_ok=True)
            self.path = root / f"{run_id}.jsonl"
            self._fh = self.path.open("w", encoding="utf-8")
        except Exception:
            self.disabled = True
            self.path = None
            self._fh = None

    def write(self, record: dict) -> None:
        if self.disabled or self._fh is None:
            return
        try:
            self._fh.write(
                json.dumps(record, ensure_ascii=False, default=str) + "\n"
            )
            self._fh.flush()
        except Exception:
            pass

    def close(self) -> None:
        if self._fh is None:
            return
        try:
            self._fh.close()
        except Exception:
            pass


def _wrap_step_callback(user_cb, capture: _Capture):
    """Compose the user-supplied on_step (if any) with the capture
    writer so both fire per step."""
    def _emit(rec: dict) -> None:
        capture.write(rec)
        if user_cb is not None:
            try:
                user_cb(rec)
            except Exception:
                pass
    return _emit


def _dump_artefacts(ctx) -> dict:
    """Serialise the per-run console / network / flicker / done-reask
    streams into JSONL files next to the screenshots so post-mortem
    review doesn't need a re-run. Returns a {name: path} dict that gets
    folded into the on_finish summary; missing dir or write errors are
    swallowed (instrumentation must never break a run).

    The DIAG block surfaced to the LLM is intentionally compact — these
    full dumps are the "click for full" view the operator wanted.
    """
    out: dict = {}
    if ctx.screenshots_dir is None:
        return out

    streams = (
        ("console", ctx.console_log),
        ("network", ctx.network_errors),
        ("flicker", ctx.flicker_log),
        ("done_reasks", ctx.done_reasks_log),
    )
    for name, records in streams:
        if not records:
            continue
        path = ctx.screenshots_dir / f"{name}.jsonl"
        try:
            with path.open("w", encoding="utf-8") as f:
                for rec in records:
                    f.write(json.dumps(rec, ensure_ascii=False, default=str)
                            + "\n")
            out[f"{name}_log_path"] = str(path)
        except Exception:
            pass
    return out


_CONSOLE_ERROR_LEVELS = frozenset({"error", "pageerror"})


def _count_console_errors(log: list[dict]) -> int:
    """How many entries in `console_log` are error-level (errors + uncaught)."""
    return sum(1 for r in log if r.get("level") in _CONSOLE_ERROR_LEVELS)


# Per-signal weights for confidence_score. Tuned so a single done-reask
# or hallucinated id drops a clean run to ~0.8 (still PASS, but visible),
# and accumulating multiple signals can drive a verbose run below 0.5
# even if final status is PASS — the operator's CI gate.
_CONFIDENCE_WEIGHTS = {
    "done_reasks":      0.20,
    "hallucinated_ids": 0.20,
    "soft_loops":       0.15,
    "vision_repeats":   0.10,
    "parse_errors":     0.05,
    "flicker":          0.05,
}


def _compute_confidence(ctx) -> tuple[float, list[str]]:
    """Composite confidence score in [0, 1] + a list of human-readable
    reasons explaining why it isn't 1.0. Empty reasons list ⇔ score=1.0.

    Not a probability. A heuristic the operator can use for CI gating:
    PASS with confidence < 0.5 should be treated as soft-PASS.

    Two penalty families:
      1. Self-reported quality signals (done_reasks, hallucinated_ids,
         soft_loops, vision_repeats, parse_errors, flicker) — what the
         agent knows about its own struggle.
      2. Terminal-state penalty — applied when ctx.status != "PASS".
         FAIL/ERROR runs by definition didn't reach a passing terminal,
         so confidence collapses regardless of how clean the signals
         were. Without this, an agent that died from `done FAIL` on
         step 2 with no other signals scored 1.0 — the operator-level
         calibration showed confidence on FAIL ≈ confidence on PASS,
         making the score useless as a discriminator.
    """
    reasons: list[str] = []
    score = 1.0
    sig = ctx.signals
    for name, weight in _CONFIDENCE_WEIGHTS.items():
        n = sig.get(name, 0)
        if n <= 0:
            continue
        # Sub-linear penalty on counts > 1 so a flaky run doesn't
        # immediately collapse to zero — but it does drop steeply.
        penalty = weight * (1 + 0.5 * (n - 1))
        score -= penalty
        reasons.append(f"{n} {name.replace('_', ' ')}")
    status = getattr(ctx, "status", "PASS")
    if status == "FAIL":
        score -= 0.6
        reasons.append("status=FAIL")
    elif status == "ERROR":
        score -= 0.8
        reasons.append("status=ERROR")
    return max(0.0, min(1.0, round(score, 3))), reasons


def _attach_diagnostics(ctx) -> None:
    """Wire console / pageerror / network listeners onto every page in the
    BrowserContext. New tabs (extension popups, target=_blank links) get
    the same listeners via the `context.on("page", ...)` hook.

    Captured records land on `ctx.console_log` and `ctx.network_errors`
    as append-only lists; per-step _emit_step slices them into the
    step record using ctx.console_cursor / ctx.network_cursor.
    """
    def _attach_to_page(pg) -> None:
        # console messages — capture level + text + location.
        def _on_console(msg) -> None:
            try:
                level = msg.type
                text = msg.text
            except Exception:
                return
            try:
                loc = msg.location or {}
            except Exception:
                loc = {}
            ctx.console_log.append({
                "ts": time.time(),
                "level": level,
                "text": text[:1000],
                "url": (loc.get("url") or pg.url or "")[:200],
                "line": loc.get("lineNumber"),
            })

        # uncaught JS exceptions (promise rejections, throw on event handlers).
        def _on_pageerror(exc) -> None:
            try:
                msg = str(exc)
            except Exception:
                msg = "<pageerror>"
            ctx.console_log.append({
                "ts": time.time(),
                "level": "pageerror",
                "text": msg[:2000],
                "url": (pg.url or "")[:200],
            })

        try:
            pg.on("console", _on_console)
            pg.on("pageerror", _on_pageerror)
        except Exception:
            pass

    # Per-context: response failures (4xx/5xx) and request failures.
    def _on_response(resp) -> None:
        try:
            st = resp.status
            if st < 400:
                return
            req = resp.request
            # Try to grab the response body for failed requests — most
            # backend errors carry the actual reason in the body
            # ("validation failed: missing field 'email'") which an
            # operator needs in the audit trail. Capped at 2KB to keep
            # the JSONL artefact lean.
            body_excerpt: str | None = None
            try:
                raw = resp.body()
                if raw:
                    text = raw.decode("utf-8", errors="replace")
                    body_excerpt = text[:2048]
                    if len(text) > 2048:
                        body_excerpt += f"... [+{len(text) - 2048} bytes]"
            except Exception:
                pass
            ctx.network_errors.append({
                "ts": time.time(),
                "kind": "http",
                "status": st,
                "method": req.method,
                "url": resp.url[:300],
                "type": req.resource_type,
                "body": body_excerpt,
            })
        except Exception:
            pass

    def _on_request_failed(req) -> None:
        try:
            ctx.network_errors.append({
                "ts": time.time(),
                "kind": "failed",
                "status": None,
                "method": req.method,
                "url": req.url[:300],
                "type": req.resource_type,
                "failure": (req.failure or "")[:200],
            })
        except Exception:
            pass

    try:
        ctx.context.on("response", _on_response)
        ctx.context.on("requestfailed", _on_request_failed)
    except Exception:
        pass

    # Attach to existing pages and any new ones spawned later.
    for pg in ctx.context.pages:
        _attach_to_page(pg)
    try:
        ctx.context.on("page", _attach_to_page)
    except Exception:
        pass


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
evaluate <jsExpr> — run JS in page; result returned as text. PREFER this over
                    `look` for assertions on hidden state, counters, dialog
                    contents, attributes — DOM truth beats vision guessing.
                    Examples:
                      evaluate document.querySelector('[role=dialog]').textContent
                      evaluate document.querySelectorAll('.alert-row').length
                      evaluate window.__APP_STATE__?.userId ?? null
                    For multi-statement use: evaluate (()=>{ /* ... */; return x; })()
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
BAD: done PASS "successful" / "completed" / "done" / "works"  (no source → REJECTED)

## Step budget & diagnostics
Every user msg starts with `[step N/M | budget: K left]`. K is steps you
still have. **Don't `done` early just because the surface looks calm** —
if the task says "wait N turns / supervisor reply / 25s wait", spend
the budget. Use `wait <ms>` (cap 60000) to wait deterministically.

If a `[DIAG since last action]` block precedes the snapshot, real
console / network errors fired during the previous action. Treat them
as evidence:
  - `[error] Failed to fetch ...` or `[net 401] POST /api/...` → the
    previous action did NOT silently succeed. Do not done PASS the
    feature; either retry, or done FAIL citing the error verbatim.
  - `[error] Cannot read properties of undefined ...` → JS crash on the
    page, the UI you see may be stale.
A diag block is only emitted on real errors — silence means clean."""


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
BAD: done PASS "search worked" / "found results" (no source → REJECTED)

## Step budget
Every user msg starts with `[step N/M | budget: K left]`. K is steps
you still have. Don't `done` early just because the surface looks
calm — if the task implies multiple turns ("wait N seconds", "scroll
through 5 cards"), spend the budget. Use `wait <ms>` (cap 60000)."""


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
             http_credentials: dict | None = None,
             trace: bool = False,
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
    # Run id stamps both the screenshots dir AND the capture file.
    run_id = f"run_{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}_{os.getpid()}"
    capture = _Capture("browser", run_id)
    capture.write({
        "t": "start", "mode": "llm", "run_id": run_id, "task": task,
        "url": url, "max_steps": max_steps, "ts": time.time(),
    })

    ctx = AgentCtx(
        task=task, url=url, headless=headless, verbose=verbose,
        max_steps=max_steps,
        extensions=extensions, init_script=init_script,
        profile_dir=profile_dir,
        on_step=_wrap_step_callback(on_step, capture),
        on_finish=on_finish, before_close=before_close,
        t_start=time.time(),
    )

    with sync_playwright() as p:
        ctx.context, ctx.page, _has_browser = _launch_browser(
            p, headless, extensions, init_script=init_script,
            profile_dir=profile_dir,
            http_credentials=http_credentials,
        )
        ctx.page.set_default_timeout(STEP_TIMEOUT)

        # Per-run screenshot directory shares its name with the capture
        # file's run_id so post-mortem can correlate them by stem.
        ctx.screenshots_dir = SCREENSHOT_DIR / run_id
        try:
            ctx.screenshots_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            ctx.screenshots_dir = None

        # Wire console/network/pageerror diagnostics BEFORE the agent does
        # anything. After this point every event the SPA fires is captured.
        _attach_diagnostics(ctx)

        # Optional Playwright tracing — records DOM snapshots, screenshots,
        # network at every actionable point. Output is a single .zip
        # opened with `playwright show-trace <path>`. Off by default
        # (5–15 MB per run is overkill for clean CI passes).
        ctx.trace_active = False
        if trace:
            try:
                ctx.context.tracing.start(
                    snapshots=True, screenshots=True, sources=False,
                )
                ctx.trace_active = True
            except Exception as e:
                if verbose:
                    print(f"  [tracing.start failed: {e}]")

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
            # Surface the auto-detected URL on ctx so MacroManager can
            # see it (it pre-feeds a synthetic goto event for the
            # implicit run-start navigation).
            ctx.url = start_url

        # Phase-3c: the FSM replaces the old 400-line for-loop. Build it,
        # hook ctx.send_event, kick off with START. All further transitions
        # are driven by events that actions emit through ctx.send_event;
        # FSM.send() drains its queue until a terminal state is reached
        # (DONE_PASS / DONE_FAIL / ERROR) or the queue empties.
        fsm = FSM("agent", AgentState.IDLE, AGENT_TRANSITIONS, ctx)
        ctx.send_event = fsm.send

        # Phase-3 online macro detector — child FSM bridged via
        # parent.on_transition. Manager handles env-flag gating and
        # silently no-ops if no macros are installed. Detection runs
        # alongside the main loop until run_task tears down.
        from .macros.online import MacroManager
        macro_manager = MacroManager(fsm, ctx)
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

        # Macro-detection finalise: detach bridge listener; collect
        # metrics for the summary regardless of whether detection
        # was actually enabled (manager.summary() handles disabled).
        macro_manager.finalise()
        macro_summary = macro_manager.summary()

        # Stop tracing first so the .zip is flushed before _dump_artefacts
        # surfaces its path in the summary. tracing.stop is best-effort —
        # failures during stop don't taint the run.
        trace_path: str | None = None
        if getattr(ctx, "trace_active", False) and ctx.screenshots_dir is not None:
            try:
                tp = ctx.screenshots_dir / "trace.zip"
                ctx.context.tracing.stop(path=str(tp))
                trace_path = str(tp)
            except Exception as e:
                if verbose:
                    print(f"  [tracing.stop failed: {e}]")

        # Dump artefact JSONL files next to screenshots, then emit final
        # summary BEFORE before_close so the assert hook can read the
        # recorded result. before_close still has live page+context.
        artefact_paths = _dump_artefacts(ctx)
        if trace_path:
            artefact_paths["trace_path"] = trace_path
        if on_finish:
            try:
                conf, conf_reasons = _compute_confidence(ctx)
                summary = {
                    "t": "result",
                    "status": ctx.status,
                    "description": ctx.description,
                    "steps_used": ctx.step,
                    "wall_seconds": elapsed,
                    "total_in": ctx.total_in,
                    "total_out": ctx.total_out,
                    "max_steps": max_steps,
                    "screenshots": list(ctx.screenshots),
                    "screenshots_dir": (
                        str(ctx.screenshots_dir)
                        if ctx.screenshots_dir is not None else None
                    ),
                    "console_errors": _count_console_errors(ctx.console_log),
                    "network_errors": len(ctx.network_errors),
                    "flicker_events": len(ctx.flicker_log),
                    "done_reasks_log": list(ctx.done_reasks_log),
                    "signals": dict(ctx.signals),
                    "confidence": conf,
                    "uncertainty_reasons": conf_reasons,
                    "macro_detection": macro_summary,
                }
                summary.update(artefact_paths)
                capture.write(summary)
                on_finish(summary)
            except Exception:
                pass
        else:
            # No user-supplied on_finish — still write the summary to
            # the capture so the trace is self-contained.
            try:
                conf, conf_reasons = _compute_confidence(ctx)
                capture.write({
                    "t": "result", "status": ctx.status,
                    "description": ctx.description,
                    "steps_used": ctx.step,
                    "wall_seconds": elapsed,
                    "total_in": ctx.total_in,
                    "total_out": ctx.total_out,
                    "max_steps": max_steps,
                    "confidence": conf,
                    "uncertainty_reasons": conf_reasons,
                    "signals": dict(ctx.signals),
                    **artefact_paths,
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

    capture.close()
    print(f"\n{'='*50}")
    print(f"  Result: {ctx.status}")
    print(f"  {ctx.description}")
    print(f"  Steps: {ctx.step}/{max_steps} | Time: {elapsed:.1f}s")
    print(f"  Tokens: {ctx.total_in} in / {ctx.total_out} out")
    print(f"  Provider: {os.environ.get('LLM_PROVIDER', 'anthropic')}")
    if capture.path:
        print(f"  Capture: {capture.path}")
    print(f"{'='*50}")

    return ctx.status, ctx.description, ctx.step


def run_tagged_task(steps_text: str,
                    url: str | None = None,
                    *,
                    headless: bool = True,
                    verbose: bool = False,
                    extensions: list[str] | None = None,
                    init_script: str | None = None,
                    profile_dir=None,
                    http_credentials: dict | None = None,
                    trace: bool = False,
                    continue_on_fail: bool = False,
                    on_step: Callable[[dict], None] | None = None,
                    on_finish: Callable[[dict], None] | None = None,
                    before_close: Callable[[Page, "object"], None] | None = None,
                    ) -> tuple[str, str, int]:
    """LLM-less counterpart of run_task. Parse `steps_text` (tagged DSL),
    execute deterministically against Playwright, return summary.

    Same diagnostics surface as run_task (per-step screenshots, console /
    network / flicker streams, JSONL artefacts, optional Playwright
    trace.zip) — only the agent loop is replaced.

    `continue_on_fail=False` (default) stops at the first FAIL/ERROR
    step. `True` runs every step regardless and reports the worst
    overall status. Either way, individual step results land in
    `step_record` via on_step.

    Returns (status, description, steps_executed).
    """
    from .runtime.ctx import AgentCtx
    from .tagged import (
        TaggedParseError, execute_step, parse_tagged,
    )

    t_start = time.time()

    # Parse up-front. Bad grammar -> structured ERROR before launching
    # a browser; cheaper than crashing mid-run.
    try:
        steps = parse_tagged(steps_text)
    except TaggedParseError as e:
        if on_finish:
            try:
                on_finish({
                    "t": "result", "status": "ERROR",
                    "description": f"parse error: {e}",
                    "steps_used": 0, "wall_seconds": 0.0,
                    "total_in": 0, "total_out": 0,
                    "max_steps": 0, "screenshots": [],
                    "screenshots_dir": None,
                    "console_errors": 0, "network_errors": 0,
                    "flicker_events": 0, "done_reasks_log": [],
                    "signals": {}, "confidence": 0.0,
                    "uncertainty_reasons": [f"parse error: {e}"],
                })
            except Exception:
                pass
        return "ERROR", f"parse error: {e}", 0

    if not steps:
        return "ERROR", "no steps parsed (empty input?)", 0

    run_id = (
        f"run_tagged_{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}_{os.getpid()}"
    )
    capture = _Capture("tagged", run_id)
    capture.write({
        "t": "start", "mode": "tagged", "run_id": run_id,
        "task": "tagged: " + steps_text[:80].replace("\n", " | "),
        "url": url, "n_steps": len(steps), "ts": time.time(),
    })

    ctx = AgentCtx(
        task="tagged: " + steps_text[:80].replace("\n", " | "),
        url=url, headless=headless, verbose=verbose,
        max_steps=len(steps),
        extensions=extensions, init_script=init_script,
        profile_dir=profile_dir,
        on_step=_wrap_step_callback(on_step, capture),
        on_finish=on_finish, before_close=before_close,
        t_start=t_start,
    )

    overall_status = "PASS"
    description = f"all {len(steps)} steps passed"
    step_results: list[dict] = []
    executed = 0

    with sync_playwright() as p:
        ctx.context, ctx.page, _ = _launch_browser(
            p, headless, extensions, init_script=init_script,
            profile_dir=profile_dir,
            http_credentials=http_credentials,
        )

        ctx.screenshots_dir = SCREENSHOT_DIR / run_id
        try:
            ctx.screenshots_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            ctx.screenshots_dir = None

        _attach_diagnostics(ctx)

        ctx.trace_active = False
        if trace:
            try:
                ctx.context.tracing.start(
                    snapshots=True, screenshots=True, sources=False,
                )
                ctx.trace_active = True
            except Exception as e:
                if verbose:
                    print(f"  [tracing.start failed: {e}]")

        # Initial navigation if url provided.
        if url:
            try:
                ctx.page.goto(url, timeout=NAV_TIMEOUT,
                              wait_until="domcontentloaded")
            except Exception as e:
                overall_status = "ERROR"
                description = f"initial navigation failed: {e}"
                steps = []  # skip step loop

        for i, step in enumerate(steps, start=1):
            ctx.step = i
            ctx.label = f"[{i}/{len(steps)}]"

            # pre-action shot, mirrored from act_exec.
            pre_path: str | None = None
            if ctx.screenshots_dir is not None:
                try:
                    pre = ctx.screenshots_dir / f"step_{i:03d}_pre.jpg"
                    ctx.page.screenshot(
                        path=str(pre), type="jpeg", quality=60,
                        full_page=True, timeout=3000,
                    )
                    pre_path = str(pre)
                    ctx.screenshots.append(pre_path)
                except Exception:
                    pass

            if verbose:
                print(f"  {ctx.label} {step}")

            res = execute_step(ctx.page, step)
            executed = i

            # post-action shot.
            post_path: str | None = None
            if ctx.screenshots_dir is not None:
                try:
                    post = ctx.screenshots_dir / f"step_{i:03d}.jpg"
                    ctx.page.screenshot(
                        path=str(post), type="jpeg", quality=60,
                        full_page=True, timeout=3000,
                    )
                    post_path = str(post)
                    ctx.screenshots.append(post_path)
                except Exception:
                    pass

            # Per-step diagnostic slice (mirrors fsm_actions._emit_step).
            console_slice = ctx.console_log[ctx.console_cursor:]
            ctx.console_cursor = len(ctx.console_log)
            network_slice = ctx.network_errors[ctx.network_cursor:]
            ctx.network_cursor = len(ctx.network_errors)

            record = {
                "t": "step", "step": i, "verb": step.verb,
                "args": list(step.args),
                "line_no": step.line_no, "raw": step.raw,
                "status": res.status, "message": res.message,
                "latency_ms": res.latency_ms,
                "eval_result": res.eval_result,
                "screenshot": post_path,
                "screenshot_pre": pre_path,
                "page_url": ctx.page.url if not ctx.page.is_closed() else None,
                "console": console_slice,
                "network": network_slice,
            }
            step_results.append(record)
            # ctx.on_step is the capture-wrapped version (whether the
            # caller supplied an on_step or not); local `on_step` here
            # is the user's raw callback only — using it would skip
            # the capture write.
            if ctx.on_step:
                try:
                    ctx.on_step(record)
                except Exception:
                    pass

            if verbose:
                print(f"    -> {res.status}: {res.message[:120]}")

            if res.status != "PASS":
                if overall_status == "PASS":
                    overall_status = res.status
                    description = (
                        f"step {i} ({step.verb}) {res.status}: {res.message}"
                    )
                if not continue_on_fail:
                    break

        elapsed = time.time() - t_start

        trace_path: str | None = None
        if ctx.trace_active and ctx.screenshots_dir is not None:
            try:
                tp = ctx.screenshots_dir / "trace.zip"
                ctx.context.tracing.stop(path=str(tp))
                trace_path = str(tp)
            except Exception as e:
                if verbose:
                    print(f"  [tracing.stop failed: {e}]")

        artefact_paths = _dump_artefacts(ctx)
        if trace_path:
            artefact_paths["trace_path"] = trace_path

        # Confidence in tagged mode: 1.0 on clean pass, 0.0 on any FAIL,
        # halfway-house between the two with errors-but-passed never
        # happens (continue_on_fail still records overall as worst).
        if overall_status == "PASS":
            conf = 1.0
            conf_reasons: list[str] = []
        else:
            conf = 0.0
            conf_reasons = [f"{overall_status} on step {executed}"]

        ctx.status = overall_status
        ctx.description = description

        summary = {
            "t": "result",
            "status": overall_status,
            "description": description,
            "steps_used": executed,
            "wall_seconds": elapsed,
            "total_in": 0,
            "total_out": 0,
            "max_steps": len(steps),
            "screenshots": list(ctx.screenshots),
            "screenshots_dir": (
                str(ctx.screenshots_dir)
                if ctx.screenshots_dir is not None else None
            ),
            "console_errors": _count_console_errors(ctx.console_log),
            "network_errors": len(ctx.network_errors),
            "flicker_events": len(ctx.flicker_log),
            "done_reasks_log": [],
            "signals": {},
            "confidence": conf,
            "uncertainty_reasons": conf_reasons,
            "tagged": True,
            "step_results": step_results,
            **artefact_paths,
        }
        capture.write(summary)
        if on_finish:
            try:
                on_finish(summary)
            except Exception:
                pass

        if before_close:
            try:
                before_close(ctx.page, ctx.context)
            except Exception as e:
                if verbose:
                    print(f"  [before_close hook failed: {e}]")

        ctx.context.close()

    capture.close()
    print(f"\n{'='*50}")
    print(f"  Result: {overall_status}")
    print(f"  {description}")
    print(f"  Steps: {executed}/{len(steps)} | Time: {elapsed:.1f}s")
    print(f"  Mode: tagged (no LLM)")
    if capture.path:
        print(f"  Capture: {capture.path}")
    print(f"{'='*50}")

    return overall_status, description, executed


def run_macro_task(macro_name: str,
                   params: dict | None = None,
                   *,
                   url: str | None = None,
                   headless: bool = True,
                   verbose: bool = False,
                   extensions: list[str] | None = None,
                   init_script: str | None = None,
                   profile_dir=None,
                   http_credentials: dict | None = None,
                   trace: bool = False,
                   continue_on_fail: bool = False,
                   on_step: Callable[[dict], None] | None = None,
                   on_finish: Callable[[dict], None] | None = None,
                   before_close: Callable[[Page, "object"], None] | None = None,
                   macros_root=None,
                   ) -> tuple[str, str, int]:
    """Run a saved macro by name. Loads the macro, substitutes params,
    delegates to `run_tagged_task` with the compiled body. Returns the
    same (status, description, steps) tuple shape.

    Use this when an operator says "run the marketplace_search skill
    with query='отвёртка'". For LLM-mid-run invocation the agent uses
    the `macro` tagged-DSL verb instead, which calls into the macros
    library directly without spinning a new browser.

    `macros_root` overrides the default `~/.config/qa_agent/macros/`
    storage location — used by tests to point at a temp dir without
    polluting user state.
    """
    from .macros import compile_macro, load_macro

    macro = load_macro(macro_name, root=macros_root)
    body = compile_macro(macro, params or {})

    # Use macro's URL precondition as start URL if caller didn't override.
    # Macros that are tied to a specific landing page record one in
    # meta.preconditions.url_templates; the first entry is the canonical
    # start URL. Macros that run on whatever page the operator opens
    # leave preconditions empty, in which case `url` must be supplied
    # by the caller.
    if url is None:
        urls = macro.preconditions.get("url_templates") or []
        if urls:
            # Templates carry placeholders like <num>; we need a real URL.
            # If the first entry has no placeholder, use it as-is;
            # otherwise the operator must pass --url explicitly.
            candidate = urls[0]
            if "<" not in candidate:
                url = candidate

    return run_tagged_task(
        body, url=url,
        headless=headless, verbose=verbose,
        extensions=extensions, init_script=init_script,
        profile_dir=profile_dir,
        http_credentials=http_credentials,
        trace=trace,
        continue_on_fail=continue_on_fail,
        on_step=on_step, on_finish=on_finish, before_close=before_close,
    )


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

    # Per-run screenshot directory, parity with the browser path.
    ctx.screenshots_dir = (
        SCREENSHOT_DIR
        / f"run_android_{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}_{os.getpid()}"
    )
    try:
        ctx.screenshots_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        ctx.screenshots_dir = None

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

    artefact_paths = _dump_artefacts(ctx)
    if on_finish:
        try:
            conf, conf_reasons = _compute_confidence(ctx)
            summary = {
                "t": "result",
                "status": ctx.status,
                "description": ctx.description,
                "steps_used": ctx.step,
                "wall_seconds": elapsed,
                "total_in": ctx.total_in,
                "total_out": ctx.total_out,
                "max_steps": max_steps,
                "screenshots": list(ctx.screenshots),
                "screenshots_dir": (
                    str(ctx.screenshots_dir)
                    if ctx.screenshots_dir is not None else None
                ),
                "console_errors": 0,         # android: no console capture
                "network_errors": 0,         # android: no http capture
                "flicker_events": 0,
                "done_reasks_log": list(ctx.done_reasks_log),
                "signals": dict(ctx.signals),
                "confidence": conf,
                "uncertainty_reasons": conf_reasons,
            }
            summary.update(artefact_paths)
            on_finish(summary)
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
