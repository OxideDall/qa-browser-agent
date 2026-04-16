# FSM redesign proposal for `qa_agent/agent.py`

Per `~/fsm.guide.md`. This doc is a **design proposal**, not a PR. It
enumerates the agent's current implicit state machine, identifies the
problems, and lays out a concrete migration to the explicit
table-driven form.

## Current state: nested-if soup

`run_task`'s main `for step in range(max_steps)` body is the canonical
"nested-if-plus-flags" anti-pattern from the guide:

- implicit states encoded as combinations of Python locals:
  `mm_popup_active`, `pending_verification`, `done_reasks`, `prev_actions`,
  plus local `action`, `args` after each LLM call.
- control flow as `continue` / `break` inside `if action == "done"` /
  `elif action == "look"` / `elif action == "tab"` / `elif action == "error"` /
  `else` branches.
- side effects (printing, evidence check, reask message, loop-vision
  retry, MM popup detection) scattered across 10+ locations.

Evidence that this is costing us today:

1. The `look` handler had an **inline `done` check that bypassed evidence
   validation** — fixed by `_DONE_REASK_MSG` extraction + duplication. The
   duplication is itself a sign of missing abstraction: in FSM form, there
   is one `done`-dispatching action, reused by both the main branch and
   the vision re-dispatch.
2. A new DSL action (`press`) meant touching:
   `parse_action`, the command-recognition tuple, `execute_action`, and
   `SYSTEM_PROMPT`. In FSM form, adding a new action means one new row
   in the table + one new Action function.
3. Loop detection sprinkles `step_record["loop_hit"] = "soft"` /
   `"hard"` across the body; in FSM form, loop-detection is a state
   (`SOFT_LOOP_VISIONING` / `HARD_LOOP_FAIL`) whose entry is observable
   from the outside.

## Proposed decomposition

One Root FSM, one Child FSM (MetaMask popup handler). No sync
orchestration; Async bridge is the default per guide §5.3.

```
AgentFSM (Root)                                MMPopupFSM (Child)
  IDLE                                           IDLE
   │                                             │ SPAWNED
   ▼ START                                       ▼
  SNAPSHOTTING                                  SCANNING
   │                                            ├─ UNLOCK_NEEDED  → unlock  →┐
   ▼ SNAPSHOT_READY                             │                             │
  THINKING                                      └─ ACTIONABLE ──bridge───────→│
   │ LLM_REPLIED                                                               ▼
   ▼                                                             (parent moves to DISPATCHING
  DISPATCHING           ←─────loop-vision result─────┐            with popup-visible snapshot)
   │                                                │
   ├─ PARSED_DONE       → evidence gate → EVIDENCE_OK    → DONE_PASS
   │                                   → EVIDENCE_MISS  → REASKING_DONE → THINKING
   │                                   → REASKS_EXHAUSTED → DONE_FAIL
   ├─ PARSED_LOOK       → VISIONING ──── (internal sub-cycle) → DISPATCHING
   ├─ PARSED_TAB        → EXECUTING_TAB    → SNAPSHOTTING
   ├─ PARSED_ERROR      → NUDGE_INVALID    → SNAPSHOTTING
   ├─ PARSED_NORMAL     → LOOP_CHECK
   │                      │  HARD_LOOP    → DONE_FAIL
   │                      │  SOFT_LOOP    → VISIONING (forced)
   │                      │  NO_LOOP      → MM_GUARD_CHECK
   │                      │                 │ MM_POPUP_ACTIVE ∧ action ∈ {tab,goto,done PASS}
   │                      │                 │   → POPUP_LOCKED (blocked nudge) → SNAPSHOTTING
   │                      │                 │ otherwise
   │                      │                 │   → EXECUTING
   │                      │                 ▼
   │                    EXECUTING
   │                      │ EXEC_RESULT
   │                      │  click + tx_trigger           → arm pending_verification
   │                      │  click + extension_popup_open → spawn MMPopupFSM
   │                      │
   │                      ▼ → SNAPSHOTTING
   │
   └─ (MAX_STEPS)     → DONE_FAIL

  DONE_PASS  (terminal)
  DONE_FAIL  (terminal)
  ERROR      (terminal — unrecoverable LLM/playwright crash)
```

### Enumerated states

**Root `AgentFSM`:**

| state              | kind       | purpose                                                  |
|--------------------|------------|----------------------------------------------------------|
| `IDLE`             | initial    | pre-start                                                |
| `SNAPSHOTTING`     | action     | `extract_elements` → ctx.snapshot                        |
| `THINKING`         | action     | `ask_llm` → ctx.resp_text                                |
| `DISPATCHING`      | action     | `parse_action` + classify → emit PARSED_*                |
| `LOOP_CHECK`       | action     | inspect `prev_actions` → emit SOFT_LOOP / HARD_LOOP / NO |
| `VISIONING`        | action     | annotated screenshot + re-ask LLM → emit PARSED_*        |
| `MM_GUARD_CHECK`   | action     | if popup_active ∧ action ∈ blocked → emit MM_BLOCKED     |
| `POPUP_LOCKED`     | action     | append BLOCKED reminder → SNAPSHOTTING                   |
| `EXECUTING`        | action     | `execute_action` + tx-trigger + popup detection          |
| `REASKING_DONE`    | action     | append `_DONE_REASK_MSG` → SNAPSHOTTING                  |
| `DONE_PASS`        | terminal   |                                                          |
| `DONE_FAIL`        | terminal   |                                                          |
| `ERROR`            | terminal   |                                                          |

**Child `MMPopupFSM`** (spawned from `EXECUTING` action when a popup is
detected after a click; async bridge back to Root):

| state           | kind     | purpose                                              |
|-----------------|----------|------------------------------------------------------|
| `SCANNING`      | action   | sniff popup body for unlock / actionable markers     |
| `UNLOCKING`     | action   | type TEST_PASSWORD + click submit                    |
| `ACTIONABLE`    | terminal | popup is open + has Confirm/Sign — parent takes over |
| `DISMISSED`     | terminal | popup had no actionable content; closed              |
| `UNLOCK_FAILED` | terminal | password didn't work / spinner never resolved        |

### Enumerated events

**Root:**

```
START, SNAPSHOT_READY, SNAPSHOT_ERR,
LLM_REPLIED, LLM_RATE_LIMITED, LLM_FATAL,
PARSED_DONE_PASS, PARSED_DONE_FAIL, PARSED_LOOK, PARSED_TAB,
PARSED_ERROR, PARSED_NORMAL, PARSED_UNKNOWN,
HARD_LOOP, SOFT_LOOP, NO_LOOP,
MM_BLOCKED, MM_NOT_BLOCKED,
EVIDENCE_OK, EVIDENCE_MISS, REASKS_EXHAUSTED,
EXEC_OK, EXEC_TIMEOUT, EXEC_ERROR,
POPUP_DETECTED, POPUP_RELEASED,
MAX_STEPS
```

**MMPopupFSM:**

```
SPAWNED, UNLOCK_NEEDED, UNLOCK_DONE, UNLOCK_FAIL,
ACTIONABLE_FOUND, NO_ACTION_NEEDED
```

**Bridge (Child → Root):**

```ts
{
  MMPopupFSM.ACTIONABLE      → AgentFSM.POPUP_DETECTED
  MMPopupFSM.DISMISSED       → AgentFSM.POPUP_RELEASED
  MMPopupFSM.UNLOCK_FAILED   → AgentFSM.EXEC_ERROR   // surfaced as error
}
```

### Transition table shape

```python
# Form B everywhere — each entry has ok/err states.
AGENT_TRANSITIONS: dict[AgentState, dict[AgentEvent, Entry]] = {
    AgentState.IDLE: {
        AgentEvent.START: (Action.begin, AgentState.SNAPSHOTTING, AgentState.ERROR),
    },
    AgentState.SNAPSHOTTING: {
        AgentEvent.SNAPSHOT_READY: (Action.build_user_msg, AgentState.THINKING, AgentState.ERROR),
    },
    AgentState.THINKING: {
        AgentEvent.LLM_REPLIED: (Action.classify_action, AgentState.DISPATCHING, AgentState.ERROR),
        AgentEvent.LLM_RATE_LIMITED: (Action.refresh_token, AgentState.THINKING, AgentState.ERROR),
        AgentEvent.LLM_FATAL: AgentState.ERROR,
    },
    AgentState.DISPATCHING: {
        AgentEvent.PARSED_DONE_PASS: (Action.evidence_gate, AgentState.DONE_PASS, AgentState.REASKING_DONE),
        AgentEvent.PARSED_DONE_FAIL: AgentState.DONE_FAIL,
        AgentEvent.PARSED_LOOK:      (Action.begin_vision, AgentState.VISIONING, AgentState.ERROR),
        AgentEvent.PARSED_TAB:       (Action.switch_tab, AgentState.SNAPSHOTTING, AgentState.SNAPSHOTTING),
        AgentEvent.PARSED_ERROR:     (Action.nudge_invalid, AgentState.SNAPSHOTTING, AgentState.SNAPSHOTTING),
        AgentEvent.PARSED_NORMAL:    (Action.check_loop, AgentState.LOOP_CHECK, AgentState.ERROR),
    },
    AgentState.LOOP_CHECK: {
        AgentEvent.HARD_LOOP: (Action.hard_fail_msg, AgentState.DONE_FAIL, AgentState.DONE_FAIL),
        AgentEvent.SOFT_LOOP: (Action.begin_vision, AgentState.VISIONING, AgentState.ERROR),
        AgentEvent.NO_LOOP:   (Action.check_mm_guard, AgentState.MM_GUARD_CHECK, AgentState.ERROR),
    },
    AgentState.MM_GUARD_CHECK: {
        AgentEvent.MM_BLOCKED:     (Action.append_blocked_nudge, AgentState.SNAPSHOTTING, AgentState.SNAPSHOTTING),
        AgentEvent.MM_NOT_BLOCKED: (Action.exec_step, AgentState.EXECUTING, AgentState.ERROR),
    },
    AgentState.VISIONING: {
        # same parser output events as DISPATCHING (the vision re-dispatch
        # goes through exactly the same gates).
        AgentEvent.PARSED_DONE_PASS: (Action.evidence_gate, AgentState.DONE_PASS, AgentState.REASKING_DONE),
        AgentEvent.PARSED_DONE_FAIL: AgentState.DONE_FAIL,
        AgentEvent.PARSED_LOOK:      (Action.noop, AgentState.SNAPSHOTTING, AgentState.SNAPSHOTTING),
        AgentEvent.PARSED_NORMAL:    (Action.check_mm_guard, AgentState.MM_GUARD_CHECK, AgentState.ERROR),
    },
    AgentState.REASKING_DONE: {
        AgentEvent.SNAPSHOT_READY: (Action.build_user_msg, AgentState.THINKING, AgentState.ERROR),
    },
    AgentState.EXECUTING: {
        AgentEvent.EXEC_OK:      (Action.post_exec_checks, AgentState.SNAPSHOTTING, AgentState.ERROR),
        AgentEvent.EXEC_TIMEOUT: (Action.feedback_timeout, AgentState.SNAPSHOTTING, AgentState.SNAPSHOTTING),
        AgentEvent.EXEC_ERROR:   (Action.feedback_error, AgentState.SNAPSHOTTING, AgentState.SNAPSHOTTING),
        AgentEvent.POPUP_DETECTED: (Action.register_popup, AgentState.SNAPSHOTTING, AgentState.SNAPSHOTTING),
    },
    AgentState.DONE_PASS:  {},   # terminal
    AgentState.DONE_FAIL:  {},   # terminal
    AgentState.ERROR:      {},   # terminal
}
```

Every row is Form A or B (`[action, next]` / `[action, ok, err]`). The
three Form-C entries (`PARSED_DONE_FAIL → DONE_FAIL`, and the two
`LLM_FATAL/... → ERROR`) go to terminals → allowed per R6.

### `ctx` payload

```python
@dataclass
class AgentCtx:
    # static inputs
    task: str
    url: str | None
    max_steps: int
    headless: bool
    extensions: list[str]
    init_script: str | None
    # running state (data, not FSM flags)
    page: Page
    context: BrowserContext
    access_token: str
    messages: list[dict]
    prev_actions: list[str]
    snapshot: SnapshotDSL        # filled in SNAPSHOTTING
    resp_text: str               # filled in THINKING
    action: str                  # filled in DISPATCHING
    args: list[str]              # filled in DISPATCHING
    last_result: str             # filled in EXECUTING
    pending_verification: dict | None
    popup_child: FSM | None      # live MMPopupFSM, set by register_popup
    step: int
    # counters
    done_reasks: int
    total_in: int
    total_out: int
    # recorder hooks
    on_step: Callable | None
    on_finish: Callable | None
    before_close: Callable | None
```

Notice what's NOT in ctx: `mm_popup_active` (was a Python-level state
flag — becomes the *presence of a live popup_child* plus the
`MM_GUARD_CHECK` state), no `is_looking`, no `is_done` — all those are
implicit in `state`.

### Loop budget

Per guide R6, each EXECUTING → SNAPSHOTTING transition increments
`ctx.step`. The "MAX_STEPS" fence is enforced by a single guard action:

```python
def exec_step(ctx):
    if ctx.step >= ctx.max_steps:
        ctx.last_result = "Max steps reached"
        raise MaxStepsReached           # → DONE_FAIL via entry's err slot
    ctx.step += 1
    ctx.last_result = execute_action(ctx.page, ctx.action, ctx.args, ...)
```

The err slot of the transition captures the budget-exceeded case. No
`if step >= max_steps` floating around in the main loop.

### Proxies

Per R2, thin one-liners per external source:

```python
def on_extraction(dsl: SnapshotDSL):         ctx.snapshot = dsl;  send(SNAPSHOT_READY)
def on_llm_reply(resp: str, ...):            ctx.resp_text = resp; send(LLM_REPLIED)
def on_llm_401():                             send(LLM_RATE_LIMITED)
def on_llm_fatal(e: Exception):              ctx.error = e;       send(LLM_FATAL)
def on_exec_result(res: str):                ctx.last_result = res; send(EXEC_OK)
def on_exec_timeout(elid: str):              send(EXEC_TIMEOUT)
def on_playwright_crash(e):                  ctx.error = e;       send(EXEC_ERROR)
# MM popup child emits these through the bridge (see above).
```

None of them read state. Each one emits exactly one event.

### Child: MMPopupFSM

Spawned inside `Action.register_popup` when `EXECUTING.click` sees a new
`chrome-extension://…/notification.html` tab.

```python
MM_TRANSITIONS = {
    MMState.IDLE: {
        MMEvent.SPAWNED: (Action.scan_popup, MMState.SCANNING, MMState.DISMISSED),
    },
    MMState.SCANNING: {
        MMEvent.UNLOCK_NEEDED:    (Action.unlock_flow, MMState.UNLOCKING, MMState.UNLOCK_FAILED),
        MMEvent.ACTIONABLE_FOUND: MMState.ACTIONABLE,       # terminal — parent acts
        MMEvent.NO_ACTION_NEEDED: MMState.DISMISSED,
    },
    MMState.UNLOCKING: {
        MMEvent.UNLOCK_DONE: (Action.re_scan, MMState.SCANNING, MMState.UNLOCK_FAILED),
        MMEvent.UNLOCK_FAIL: MMState.UNLOCK_FAILED,
    },
    MMState.ACTIONABLE:    {},
    MMState.DISMISSED:     {},
    MMState.UNLOCK_FAILED: {},
}
```

The bridge in Root reads `child.state` only on transition (per R5), maps
terminal states to `POPUP_DETECTED` / `POPUP_RELEASED` / `EXEC_ERROR`.

### What we lose / what we gain

Lose:
- Some flexibility to sneak in ad-hoc side effects mid-loop.
- ~50 lines of imperative glue are replaced by ~80 lines of table +
  actions — marginal code-size win at best.

Gain:
- **One source of truth.** Adding a new state or event = one row; today
  it's a grep-for-every-`if-action-==`.
- **Testable in isolation.** Each action is a pure function over `ctx`;
  each transition is a lookup. The rules baked into the table can be
  unit-asserted: "DISPATCHING + PARSED_DONE_PASS should end up in
  DONE_PASS when ctx has evidence, REASKING_DONE when it doesn't."
- **Dead-branch test** for free — the guide §6.4 BFS pattern. Today
  the `look` handler's missing evidence gate was a dead branch that
  **silently succeeded** (wrong PASS); in FSM form, the missing edge
  would be flagged by the test.
- **Bench instrumentation becomes trivial.** `on_step` today reconstructs
  the step record in a dozen manual assignments (`step_record["action"]
  = action` here, `step_record["loop_hit"] = "soft"` there). In FSM form
  every `(from, event, to)` is emitted by the dispatcher as a uniform
  record, no manual tracking.

## Migration path

Incremental, bench-gated. Don't drop the current agent.py; keep it
working while the FSM variant comes up alongside.

### Phase 1 — extract helpers, no state-machine yet

- Move `_has_evidence`, `_is_oscillating`, tx-trigger detection,
  MM-popup scanning into plain pure functions in a new
  `qa_agent/runtime/` package.
- Keep agent.py's loop mostly as-is, just calling the new helpers.
- A/B: no behavior change expected; bench should stay at 12/12.

### Phase 2 — ctx dataclass + Proxies

- Introduce `AgentCtx` dataclass; refactor `run_task` to instantiate it
  once, not use long local variable lists.
- Rewrite the loop steps to call `on_*` proxies that populate `ctx` —
  still a for-loop, but every side effect is now routed through a named
  function. This makes Phase 3 mechanical.
- Bench: expect parity (same PASS/FAIL, token counts within 5%).

### Phase 3 — introduce FSM class + transition table

- Add `qa_agent/runtime/fsm.py` mirroring guide §3 (generic; ~40 lines).
- Build `AGENT_TRANSITIONS` with Action thunks that read/write `ctx`.
- Wire `run_task` to instantiate `AgentFSM` and loop
  `while fsm.state not in TERMINALS: ...` — single line replacing the
  current 400-line body.
- Bench: expect 12/12 PASS (this is the gate). Token counts may rise
  slightly due to the second dispatch layer; acceptable if < +5%.

### Phase 4 — extract MMPopupFSM

- Move the MM popup detection + auto-unlock logic into a Child FSM.
- Bridge it back to Root via `POPUP_DETECTED` / `POPUP_RELEASED`.
- Bench: expect parity; web3 fixtures should improve (cleaner popup
  state means fewer wasted steps in agent reading partial popup DOM).

### Phase 5 — kill the old `run_task` loop body

- Delete the for-loop body in agent.py once Phase 3–4 are proven.
- Agent.py becomes a thin façade: instantiate AgentFSM, call `send`
  until terminal, return `(status, description, step)`.

### Gating

Each phase must land **9/9 PASS** on the current bench (static_ui × 4 +
spa_dynamic × 1 + web3_defi × 4) **and the three live-net fixtures**
before the next phase is reviewed. No yolo-commits.

### What this doesn't fix

- The `SYSTEM_PROMPT` itself — still a single text blob, still sent on
  every LLM call. FSM redesign is orthogonal to prompt design. The
  few-shot-v1 regression (findings F4) is a prompt problem, not a
  structural one.
- Vision over-use — still driven by the agent's response. FSM just
  makes the "when did vision fire" observable.
- Rate limits on live-net fixtures — FSM doesn't help here either.

## TL;DR

- Root `AgentFSM` with 10 states + 3 terminals + ~20 events.
- Child `MMPopupFSM` spawned from `EXECUTING`.
- All side effects through named actions; all "where to go" through the
  table; all external inputs through one-line proxies.
- Migration is 5 phases, each bench-gated. The current 12/12 suite is
  the regression fence.
- Main value: every hidden-state bug that the bench catches today
  (`look` bypassing evidence, forgotten `press Enter`, numeric-only
  evidence slipping through) becomes a table row that either exists and
  is tested, or is intentionally absent per R6.
