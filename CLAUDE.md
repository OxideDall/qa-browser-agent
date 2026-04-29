# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

No `pyproject.toml` / `requirements.txt` — dependencies are installed ad-hoc:
```bash
pip install playwright uiautomator2 Pillow mcp
playwright install chromium
```

Single task (browser):
```bash
python -m qa_agent "verify signup at http://localhost:3000"
python -m qa_agent --metamask "connect wallet on https://app.uniswap.org"
python -m qa_agent --setup-metamask          # one-shot MM wallet bootstrap
python -m qa_agent --json-result ...         # MCP mode: JSON → stdout, logs → stderr
```

Bench (browser):
```bash
python -m bench.runner --all                 # full suite
python -m bench.runner --category static_ui  # filter by category
python -m bench.runner --level 3             # filter by level
python -m bench.runner static_l3_pricing     # single fixture
python -m bench.analyze                      # aggregate results/runs/*.jsonl
python -m bench.ab promptA.txt promptB.txt   # A/B two SYSTEM_PROMPTs
```

Bench (Android — needs `adb connect` done first):
```bash
ANDROID_SERIAL=<ip>:5555 python -m bench.android.runner android_aliexpress_l1_search
ANDROID_SERIAL=<ip>:5555 python -m bench.android.runner --all
```

Makefile shortcuts (run from `bench/`):
```bash
make bench-static        # static_ui only
make bench-web3          # web3_defi only (needs funding + setup-mm)
make analyze
make balances            # bench wallet balances across 5 testnets
make setup-mm            # bootstrap MM in bench_profile/ with BENCH_SEED
make verify-mm           # confirm MM shows BENCH_ADDRESS_0
make ab A=path B=path    # A/B harness
make clean               # wipe results/runs/
```

MCP server (stdio, FastMCP):
```bash
python3 mcp_server.py    # tools: qa_run, qa_setup_metamask, qa_status
```

There is **no test runner** — `bench/fixtures/` IS the test suite. Per-fixture run: `python -m bench.runner <fixture_id>`. No lint/typecheck config.

## Environment variables

| var                  | purpose                                                                 |
|----------------------|-------------------------------------------------------------------------|
| `LLM_PROVIDER`       | `anthropic` (default) \| `openrouter` \| `subscription` (lazy-imports gitignored `qa_agent/oauth/`) |
| `ANTHROPIC_API_KEY`  | required for `anthropic` provider                                       |
| `OPENROUTER_API_KEY` | required for `openrouter` provider                                      |
| `LLM_MODEL`          | model override (provider-specific id); default `claude-haiku-4-5`       |
| `LLM_MAX_TOKENS`     | default 1024                                                            |
| `ANDROID_SERIAL`     | `<ip>:5555` — for `bench.android.runner` / `qa_agent.android`           |
| `BENCH_SEED`         | 24-word mnemonic for web3 fixtures (testnet-only; see `.env.example`)   |
| `BENCH_ADDRESS_0`    | Address derived at `m/44'/60'/0'/0/0` from BENCH_SEED (pre-flight check)|
| `BENCH_PASSWORD`     | MetaMask unlock password inside `bench_profile/`                        |
| `QA_MAX_WAIT_MS`     | Hard cap for the `wait <ms>` DSL action; default 60_000. Bump for fixtures that legitimately wait on slow backends (supervisor replies, long polls). Cap, not target — agent still chooses the value, this just bounds the upper end. |

`mcp_server.py` auto-loads `.env` with a minimal inline parser (no python-dotenv dep). Existing env vars win over `.env` so MCP hosts can override.

## Architecture — big picture

### The central design bet: DSL snapshot, not screenshot

Unlike computer-use / Operator / Manus agents that send a 1 MPix screenshot per step (~$0.03, 4–5 s/step), this agent compresses the page DOM into a **~300-token text DSL** and asks a small LLM (Haiku-class) for exactly **one action** per step. Screenshots are only taken when the agent emits `look` (ambiguous DSL). This is why a single run costs ~an order of magnitude less and why the same loop works for browser, browser+extension (MetaMask), and Android phones — only the extractor/executor pair changes.

DSL contract lives in two `SYSTEM_PROMPT` strings in `qa_agent/agent.py` (one for browser, one for Android). **Do not drift these out of sync with the parser in `qa_agent/actions.py::parse_action`** and the recognized-command tuple — adding a new DSL verb is a ≥3-site change (prompt text, parser branch, executor branch, plus `runtime/` if it affects dispatching).

### Table-driven FSM (agent loop) — read `bench/fsm_design.md` before touching

The main loop is **not** nested if/elif on `action == "..."` — that was the pre-Phase-3 design and the cause of several bugs documented in `bench/fsm_design.md`. Current design follows `~/fsm.guide.md` (R1–R9):

- **Rules the dispatcher enforces** (`qa_agent/runtime/fsm.py::FSM._send_one`):
  - R1: dispatcher is pure table lookup + action call, **no `if`/`switch` by state or event**.
  - R3: only actions produce side-effects. Action returns → FSM moves to `ok_state`. Action raises → FSM moves to `err_state`.
  - R6: **missing table row = intentional no-op**. Don't add dead branches.
  - R7: transitions happen **only** via `ctx.send_event(E)`. Never mutate `ctx.send_event` or `fsm.state` directly from an action.
  - R8: states/events are `Enum`, never strings.
  - Re-entrant `send()` is queued + drained (sync-Python equivalent of guide's `queueMicrotask`) — an action calling `ctx.send_event(next)` appends to the queue; the outer `send()` keeps draining.

- **States** (`qa_agent/runtime/states.py`): `IDLE → SNAPSHOTTING → THINKING → DISPATCHING → { LOOP_CHECK → MM_GUARD_CHECK → EXECUTING } → back to SNAPSHOTTING`. Terminals: `DONE_PASS`, `DONE_FAIL`, `ERROR`.

- **Transition table** (`qa_agent/runtime/transitions.py::AGENT_TRANSITIONS`): the single source of truth for what happens on each `(state, event)`. Every live row points to one `act_*` action function in `fsm_actions.py`. Adding a new branch = one new row + one new action; **never** `if`-branch inside an existing action on "what kind of action is this".

- **Actions** (`qa_agent/runtime/fsm_actions.py`): thin FSM-contract wrappers around pure helpers in `runtime/actions.py` (snapshot, evidence, loop-check, vision-retry). Each takes `ctx: AgentCtx`, reads/writes ctx fields, emits next event via `ctx.send_event`, and returns. Per-step transient state (`snapshot`, `resp_text`, `action`, `args`, `last_result`, `step_record`) lives on `ctx` so actions don't need parameters beyond `ctx` (`runtime/ctx.py::AgentCtx`).

### Driver abstraction: browser ↔ Android

`AgentCtx.driver_kind` ∈ `{"browser", "android"}` switches snapshot + execute implementations. Everything else — FSM, evidence gate, LLM, loop detection, MM popup guard (browser-only branches are gated by `driver_kind` in the helpers) — is shared. When adding an Android-only DSL verb or browser-only feature:

- Extend both `SYSTEM_PROMPT` strings in `agent.py` (browser vs Android).
- Add executor branch in `qa_agent/actions.py` (browser) or `qa_agent/android.py` (Android). The Android driver is a standalone port of `browser.py + extract.py + actions.py` — keep the contract identical so `runtime/actions.py` dispatch stays clean.
- The `look` action still goes through `vision.py`; both drivers produce a JPEG + element annotation.

### Evidence gate — why `done PASS "success"` is rejected

`qa_agent/runtime/evidence.py` enforces 7 accept patterns on the `done PASS` reason string: inner-quoted ≥5-char text, 0x hex fragment, number+unit, 4-digit year, 2–4 capitalized proper noun, two `<digit> <noun>` anchors, or narrative (4+ distinct ≥3-char non-hedge words). Generic success-fluff ("completed", "works", "passed") fails the gate. On miss, `act_reask_done` increments `ctx.done_reasks` and re-enters `SNAPSHOTTING`; after `REASKS_EXHAUSTED` → `act_emit_done_forced_fail → DONE_FAIL`.

Keep the taxonomy honest: if you add evidence patterns, add regression fixtures that prove the pattern fires on real runs and doesn't over-match fluff.

### Loop detection + MM guard

- **Hard loop**: same `(action, args)` 3× in a row → `act_emit_hard_fail → DONE_FAIL`.
- **Soft loop** (ABAB pattern): `act_vision_forced` re-asks with an annotated screenshot before executing.
- **MetaMask popup guard**: when an MM extension popup is open, `act_mm_guard` blocks `tab | goto | done PASS` until the popup closes (recognized by `runtime/mm_popup.py::has_mm_action` against a RU+EN keyword list). The agent may still call `done FAIL` to abort.
- **TX trigger** (web3): any DSL action matching supply/borrow/repay/withdraw/swap/stake/send/deposit/claim/mint/bridge/approve/sign/confirm arms `ctx.pending_verification` — before `done PASS`, the agent must see BOTH popup closed AND dApp success (toast / receipt / updated balance / tx hash).

### MCP server — subprocess isolation is deliberate

`mcp_server.py` shells out to `python -m qa_agent --json-result ...` via `subprocess.run` **on purpose**. Do not refactor to in-process calls: `playwright.sync_api` cannot run inside FastMCP's asyncio/sniffio context (event-loop conflict + contextvar leak into anyio's thread executor). The CLI reroutes all `print` to stderr under `--json-result` and emits exactly one JSON line on stdout — `_run_cli` scans from end of stdout for the last parseable `{"status": ...}` line. If you add a new tool, follow the same shell-out pattern.

### Bench harness

- Fixtures under `bench/fixtures/<category>/<id>/` (browser) or `bench/android/fixtures/<id>/` (Android). Each is: `config.toml` + `task.txt` + (`assert.json` declarative OR `assert.py` programmatic). Optional `site/` dir → served by `bench/runner/server.py`; URL placeholder `{base}` gets substituted.
- `bench/runner/runner.py::run_one` orchestrates: load → pre-flight web3 balance check (`skip_if_underfunded`) → serve static site → `run_task(...)` with `on_step` / `on_finish` / `before_close` hooks → programmatic OR declarative assert → JSONL record. Retry loop honors `[budget].retries` from `config.toml`.
- Web3 fixtures use the dedicated `BENCH_PROFILE` (`~/.config/qa_agent/bench_profile`) that has MM pre-seeded with `BENCH_SEED`; non-web3 fixtures run profile-less.
- Run log schema is documented in `bench/README.md` — `{t: start|step|result|assert|skip|error|attempt|note}` JSONL lines, one file per run under `bench/results/runs/`.

### Diagnostics: console, network, screenshots, flicker

Every browser run automatically captures four streams that the original loop dropped on the floor. None of these are opt-in — they are wired in `qa_agent/agent.py::_attach_diagnostics` and `qa_agent/runtime/fsm_actions.py::_emit_step`.

- **Per-step screenshot**. Browser: JPEG (`q60`, viewport-only) at `qa_screenshots/run_<UTC>_<pid>/step_NNN.jpg`. Android: PNG via `device.screenshot(path)`. Path goes to `step_record["screenshot"]` and to `ctx.screenshots`. Final summary key: `screenshots: list[str]`.
- **Console + uncaught exceptions**. `page.on("console")` + `page.on("pageerror")` cover every page in the context — including new tabs spawned later (MM popups, target=_blank). Records land on `ctx.console_log`; per-step slice is in `step_record["console"]`. Final counter (errors only, not warns): `console_errors`.
- **Failed HTTP responses + request failures**. `context.on("response")` filters status≥400, `context.on("requestfailed")` catches DNS / TLS / aborted. Per-step slice: `step_record["network"]`. Final counter: `network_errors`.
- **Flicker (sub-second DOM oscillation)**. `qa_agent/browser.py::MUTATION_INIT_SCRIPT` injects a MutationObserver before any page script runs; it writes to a bounded `window.__qa_mutations` ring buffer. After every action `qa_agent/runtime/actions.py::detect_flicker` drains the buffer and emits one event per node-fingerprint that flapped ≥`FLICKER_MIN_FLAPS=4` times within `FLICKER_WINDOW_MS=500`. Per-step slice: `step_record["flicker"]`. Final counter: `flicker_events`.

When console/network produced anything error-level during a step, `_emit_step` builds a compact `[DIAG since last action]` blurb and stashes it on `ctx.pending_diag`. The very next `act_think` prepends it to the user message so the LLM sees diagnostic context **before** committing to an action. The two SYSTEM_PROMPTs (browser / android) tell the agent how to interpret these blocks — don't drop those instructions when editing the prompt.

The MCP `qa_run` return dict and the CLI `--json-result` line surface all four counters plus the screenshot list:

```json
{"status": "PASS", "description": "...", "steps": 2, "elapsed": 6.8,
 "screenshots": ["qa_screenshots/run_.../step_001.jpg", ...],
 "console_errors": 0, "network_errors": 0, "flicker_events": 0}
```

### Step-budget hint

Every `act_think` prefixes its user message with `[step N/M | budget: K left]`. The SYSTEM_PROMPTs explicitly tell the agent **not** to `done` early when the task implies multiple turns. Without this hint the agent has no scalar signal of "how many turns I still have" — it would call `done` whenever the surface looks calm, which broke fixtures that needed e.g. a 25-second wait for a supervisor reply.

### Recorder / run-record hooks

`run_task` (and `run_android_task`) expose three callbacks used by the bench harness and should be preserved when refactoring the loop:

- `on_step(record)` — fires once per FSM iteration with the full step record (action, args, result, in/out tokens, latency_ms, page_url, mm_active, loop_hit, blocked, done_reasked, evidence_present, vision, **screenshot, console, network, flicker**).
- `on_finish(summary)` — fires after FSM drains, BEFORE `before_close`, so live-DOM asserts can read the agent's final `status`.
- `before_close(page, context)` — runs with Playwright page/context still alive so declarative asserts can inspect live DOM / localStorage / open tabs.

All three are wrapped in try/except — recorder crashes must never break a run.

## MetaMask test seeds — safety

`qa_agent/config.py::TEST_SEED` is the well-known Hardhat mnemonic ("test test test … junk"). It IS checked in intentionally — deterministic addresses on every EVM chain, safe for local forks. **Do not fund it on mainnet.** For real testnet fixtures use `BENCH_SEED` from `.env` (gitignored). `setup_metamask()` accepts both via `seed=` kwarg; `bench/setup_mm.py` uses `BENCH_SEED` + a separate `bench_profile` directory.
