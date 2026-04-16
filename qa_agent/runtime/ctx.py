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
