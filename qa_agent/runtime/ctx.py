"""AgentCtx — the persistent state of a run_task invocation.

Phase 2 of the FSM refactor (bench/fsm_design.md §Phase 2). This carves
out every local variable that spans iterations of the main loop into a
single dataclass so Phase 3 can build a transition table whose actions
read/write exactly this object.

Not in ctx (stay as per-iteration locals):
  - the per-step record dict
  - extracted elements of the current snapshot
  - parsed (action, args) of the current LLM reply
  - transient exec result

Those become ctx fields in Phase 3 when the FSM class arrives and the
for-loop body splits into named actions. For now they're just scratch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


@dataclass
class AgentCtx:
    # --- inputs from run_task() parameters -------------------------------
    task: str
    url: str | None
    headless: bool
    verbose: bool
    max_steps: int
    extensions: list[str] | None
    init_script: str | None
    profile_dir: Path | None

    # --- recorder hooks (bench runner, MCP, future FSM listeners) --------
    on_step: Callable[[dict], None] | None = None
    on_finish: Callable[[dict], None] | None = None
    before_close: Callable[[Any, Any], None] | None = None

    # --- LLM / conversation ----------------------------------------------
    access_token: str = ""
    total_in: int = 0
    total_out: int = 0
    messages: list[dict] = field(default_factory=list)

    # --- agent-loop persistent state -------------------------------------
    prev_actions: list[str] = field(default_factory=list)
    mm_popup_active: Any = None          # Playwright Page or None
    pending_verification: dict | None = None
    done_reasks: int = 0

    # --- diagnostics: console / network / screenshots --------------------
    # Append-only logs populated by listeners attached in run_task. The
    # *_cursor fields track how much each step's _emit_step has already
    # consumed; the per-step slice goes into step_record["console"] /
    # step_record["network"] / step_record["mutations"] so bench logs
    # carry exactly what surfaced during that step (not the whole run
    # history every step).
    console_log: list[dict] = field(default_factory=list)
    network_errors: list[dict] = field(default_factory=list)
    flicker_log: list[dict] = field(default_factory=list)
    console_cursor: int = 0
    network_cursor: int = 0
    flicker_cursor: int = 0
    # Per-run screenshot output dir (populated in run_task before the FSM
    # starts). Per-step screenshot paths get appended to `screenshots`
    # and also written into step_record["screenshot"].
    screenshots_dir: Any = None           # pathlib.Path | None
    screenshots: list[str] = field(default_factory=list)
    # Pending diagnostic blurb stashed by _emit_step, consumed (and
    # cleared) by act_think on the very next turn so the message
    # alternation user/assistant stays clean.
    pending_diag: str = ""
    # Per-run done-PASS reasks: every time the evidence gate sends a
    # `done PASS` back for a re-ask, append {step, description, reason}
    # so the operator can see WHY the gate kept rejecting (not just that
    # it did). Surfaced in the final summary as `done_reasks_log`.
    done_reasks_log: list[dict] = field(default_factory=list)
    # Consecutive parse errors. Reset when any action parses cleanly.
    # 3 in a row triggers a forced FAIL — agent is emitting prose
    # instead of DSL and won't recover from a polite nudge.
    parse_errors: int = 0
    # Last vision-forced action (action:args) + how many times vision
    # has returned that same string. ≥2 → forced FAIL ("vision stuck").
    last_vision_act: str = ""
    vision_repeat: int = 0
    # Cumulative quality signals — distinct from the counters above
    # (which are sliding/resettable). These never reset, accumulate
    # across the whole run, and feed `compute_confidence(ctx)` into
    # the final summary. Operators use the score to gate CI: a PASS
    # with confidence < 0.5 is a soft-PASS and probably needs a
    # human eyeball.
    signals: dict = field(default_factory=lambda: {
        "done_reasks": 0,
        "soft_loops": 0,
        "vision_repeats": 0,
        "hallucinated_ids": 0,
        "parse_errors": 0,
        "flicker": 0,
    })
    # Tracing toggle — true while context.tracing.start was successful;
    # run_task uses it to decide whether to call tracing.stop().
    trace_active: bool = False
    # Online macro detector — populated by MacroManager when QA_AUTO_MACRO=1
    # and a match fires. act_classify reads & clears this on the next
    # LLM-reply boundary, replacing the parsed action with a
    # synthetic `macro <name> k=v ...` invocation. Empty string ⇒ no
    # pending auto-invoke.
    macro_auto_action: str = ""
    # Names of macros that successfully executed at least once during
    # this run. MacroFSM consults this set in its precondition / page
    # checks to refuse re-triggering an already-fired macro — without
    # this, a login macro keeps firing on every successive page-ready
    # event when login (e.g. locked_out_user) didn't redirect off the
    # login page, multiplying token cost.
    macro_succeeded_names: set = field(default_factory=set)

    # --- result / timing -------------------------------------------------
    status: str = "ERROR"
    description: str = "Max steps reached"
    step: int = 0
    t_start: float = 0.0

    # --- browser handles (populated after _launch_browser) ---------------
    page: Any = None                      # Playwright Page
    context: Any = None                   # Playwright BrowserContext

    # --- driver dispatch -------------------------------------------------
    # "browser" (default) drives Playwright via extract.py + actions.py +
    # the MM-popup-aware snapshot path. "android" drives uiautomator2 via
    # qa_agent.android and skips all browser/MM-specific logic.
    driver_kind: str = "browser"
    android_device: Any = None             # u2.Device or None

    # --- transient per-iteration state (Phase 3c) ------------------------
    # These are populated and consumed WITHIN a single loop pass. The FSM
    # dispatcher uses them to thread information between its state actions
    # without adding parameters to every action signature.
    snapshot: dict | None = None          # {elements, elements_text, is_fallback, step_image}
    resp_text: str = ""                   # last LLM reply
    action: str = ""                      # parsed DSL action
    args: list[str] = field(default_factory=list)
    last_result: str = ""                 # execute_action result string
    step_record: dict | None = None       # per-step recorder buffer
    label: str = ""                       # "[N/M]" formatted step label

    # --- FSM plumbing ----------------------------------------------------
    # Actions emit the next event via ctx.send_event(E). The dispatcher
    # installs this as a closure over `fsm.send` at FSM construction time.
    send_event: Any = None                # Callable[[AgentEvent], None]


# -----------------------------------------------------------------------
# Proxies — thin helpers that mutate ctx in response to an external event.
# Per fsm.guide.md §R2 they do not read state, do not branch by business
# logic; they write data and (in Phase 3) emit one event. For Phase 2
# they just mutate ctx.
# -----------------------------------------------------------------------

def on_tx_trigger(ctx: AgentCtx, trigger: str, label: str) -> None:
    """One-shot arm of the post-tx verification nudge."""
    ctx.pending_verification = {"trigger": trigger, "label": label[:80]}


def on_popup_opened(ctx: AgentCtx, popup_page: Any) -> None:
    ctx.mm_popup_active = popup_page


def on_done_reask(ctx: AgentCtx) -> None:
    ctx.done_reasks += 1
