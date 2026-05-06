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
python -m qa_agent --tagged steps.txt        # LLM-less deterministic mode
python -m qa_agent --macro <name> --param k=v --param k=v ...   # invoke saved skill
python -m qa_agent --list-macros             # catalog of installed macros
```

Bench (browser):
```bash
python -m bench.runner --all                 # full suite
python -m bench.runner --category static_ui  # filter by category
python -m bench.runner --level 3             # filter by level
python -m bench.runner static_l3_pricing     # single fixture
python -m bench.runner --all --fail-fast     # stop after first FAIL (skips OK)
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
| `QA_DISABLE_CAPTURE` | Set `1` to opt out of automatic per-run trace capture to `~/.config/qa_agent/captures/{browser,tagged}/<run_id>.jsonl`. Captures are inputs for the macro mining pipeline (see `bench/macros_design.md`); off-by-default storage is fine for one-off runs but you'll want it on for regression suites. |

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

### Macro pipeline — Phase 1 offline miner

`python -m qa_agent.macros.miner` reads accumulated capture JSONLs (Phase 0 substrate), mines frequent contiguous (verb, role) N-grams, infers parameter slots vs. concrete args, optionally asks the LLM to label / gate candidates, validates structural alignment against source captures, emits tagged-DSL macros into `~/.config/qa_agent/macros/`. Hybrid: symbolic discovery + LLM naming, neither alone.

Pipeline modules in `qa_agent/macros/miner/`:

| module | role |
|---|---|
| `loader.py` | JSONL → `Trace` (normalises LLM-mode `action` ↔ tagged-mode `verb`); drops failed / tagged runs by default |
| `vocabulary.py` | `Trace` → `list[VocabItem]`, `(verb, classifier)` per step. Drops `look` / `screenshot` / `tab` / `macro` (operator-instrumentation, not skills). |
| `mining.py` | contiguous N-gram mining + closed-pattern (BIDE-style) filter |
| `inference.py` | for each (step_idx, arg_idx): all-equal args → concrete, varying → parameter slot. Snapshot-id at arg 0 of click/type/etc. dropped (varies trivially run-to-run, not a real parameter). |
| `curator.py` | LLM names + gates candidates. Falls back to offline auto-name on LLM failure. JSON-only structured output, response validation (every inference slot must appear in LLM's `params`, name regex-checked). |
| `validate.py` | structural alignment score: `matched_steps / total_steps` re-walked against source captures. ≥0.95 passes. Live-page validation is Phase 1.5 (not implemented). |
| `emit.py` | per-verb tagged-DSL rendering + meta.json. `click <role>` (no name — captures lack accessible names; replay uses role-based selectors). |

CLI flags: `--no-curate` (skip LLM, offline auto-name), `--no-validate` (skip structural check), `--dry-run` (print, don't write), `--include-failed` / `--include-tagged` (relax default filters), `--min-support N --min-len N --max-len N --max-emit N`.

Verified on synthetic 4-run search workload: emits a clean `goto / click / type ${text} / press Enter / expect_visible` macro with proper param schema. On real-world captures (7 traces from this repo's own tests, dry-run with `--include-failed --include-tagged --min-len 1`): finds 3 candidate patterns including the campo-staging smoke workflow.

### Macro pipeline — Phase 2 replay

A macro is a saved skill at `~/.config/qa_agent/macros/<name>/` (or `$QA_MACROS_DIR`):

- `macro.tagged.txt` — body in tagged DSL with `${param}` placeholders.
- `meta.json` — schema: `{name, version, description, params: [{name, type, required, default, description}], preconditions: {url_templates}, support_count, success_rate, learned_from_runs}`. Param types: `string`, `int`, `url`.

Three invocation paths, all going through `qa_agent/tagged.py::execute_step` for the actual work:

| path | command | when |
|---|---|---|
| **Standalone** | `python -m qa_agent --macro <name> --param k=v ...` (CLI) or `qa_macro_run(macro, params, ...)` (MCP) | operator script / CI gate. Spins a browser, navigates to the macro's URL precondition (overridable via `--url`), replays via `run_macro_task` → `run_tagged_task`. Full diagnostics surface. |
| **Inline from tagged** | `macro <name> k=v ...` verb inside another `*.tagged.txt` | composing skills out of skills; tested working with the campo-staging smoke macro. |
| **From LLM (deferred)** | not in this batch — LLM-path DSL doesn't yet expose `macro` verb | will be added once we have curated macros worth advertising. Tagged-path nesting covers operator-driven cases until then. |

Public API is `qa_agent.macros.{load_macro, list_macros, compile_macro, Macro, ParamSpec, MacroNotFound, MacroParamError, MACROS_DIR}`. `compile_macro` does typed substitution: missing required → MacroParamError, unknown name → MacroParamError, type mismatch (`int` param given non-int) → MacroParamError. Tagged-DSL grammar errors surface separately at parse time, after substitution.

`--list-macros` CLI flag prints installed catalog. `qa_macro_list` MCP tool returns `{macros: [...]}` with the same per-entry summary.

Macros are versioned: `meta.version` is the macro author's responsibility; bumping it on every breaking change keeps replay auditable. The macro pipeline (Phase 1 miner) emits `version: 1` at first sighting and increments when the same skill name is re-mined with a different body.

### Capture management — `qa_agent.macros.captures`

`python -m qa_agent.macros.captures <stats|list|gc>` — operational hygiene for the capture archive (Phase 0 substrate). Captures grow without bound by default; this is how you prune.

| subcommand | what |
|---|---|
| `stats` | inventory size, counts by mode (llm/tagged) and final status (PASS/FAIL/ERROR), oldest+newest mtimes |
| `list [--mode] [--status] [--limit N]` | per-capture metadata table — run_id, mode, status, steps, total size (JSONL + screenshots), age in days |
| `gc --days N [--apply] [--keep-failed]` | drop captures older than `N` days. Default dry-run; `--apply` actually deletes. `--keep-failed` exempts FAIL/ERROR captures (often you want those preserved for debugging long after pruning successful runs). |

GC also removes the per-run `qa_screenshots/<run_id>/` directory so Phase 0's run_id-stamp symmetry stays clean. Public API: `qa_agent.macros.captures.{compute_stats, list_captures_meta, gc_old_captures}` for tooling integration.

### Macro pipeline — Phase 0 capture + page signatures

Every run automatically writes a JSONL trace to `~/.config/qa_agent/captures/{browser,tagged}/<run_id>.jsonl`. Each step record carries a `pre_signature` from `qa_agent/runtime/page_signature.py`:

- `url_template` — URL with numeric / UUID / slug-like / long-hex segments normalised, query keys sorted, values dropped.
- `struct_hash` — 16-hex SHA-1 over `(tag, role, type, disabled, checked, has_href, has_placeholder)` per interactive element, in DOM order. Invariant under content changes.
- `content_hash` — SHA-1 over the bag of visible text strings (lowercased, deduped). Invariant under structural changes.
- `n_elements` — quick filter.

Two pages are *same template* if `(url_template, struct_hash)` match, *same instance* if all three match. Captures are inputs for the macro mining pipeline — see `bench/macros_design.md` for the full plan (PrefixSpan/BIDE for sub-trace mining, hybrid LLM curator for naming + parameter slots, tagged DSL as the compile target, APTED for cross-site generalisation in Phase 4). Phase 0 (capture infrastructure) is what's wired today; Phases 1-4 are documented and not yet implemented.

`screenshots_dir` and the capture file share the same `run_id` stamp so post-mortem can correlate them by stem.

### Two execution modes — natural-language (LLM) vs tagged (deterministic)

This codebase has **two** independent execution paths:

1. **`run_task` (LLM-driven)** — `qa_agent/agent.py`. Natural-language task, vision + DSL snapshot loop, evidence gate, loop detection, vision hallucination guard. Use for exploratory and "log in and find X" workflows. The whole FSM in `qa_agent/runtime/` belongs to this path.
2. **`run_tagged_task` (deterministic, NO LLM)** — `qa_agent/agent.py`, `qa_agent/tagged.py`. Takes an explicit list of typed steps (`click`, `expect_visible`, `expect_text`, `expect_count`, `expect_eval`, ...) and runs them straight through Playwright. No vision, no LLM cost, no evidence gate, deterministic timing. Stops at first FAIL by default.

Both modes share the **diagnostics surface**: per-step pre+post screenshots, console / network / flicker capture, JSONL artefact dumps, optional Playwright trace.zip, the same final-summary schema (with `tagged: True` flag in the tagged path). Operators can slot tagged-mode runs into the same MCP / CLI / bench pipelines they already use for LLM runs.

CLI: `python -m qa_agent --tagged path/to/steps.txt [--continue-on-fail]`. MCP: `qa_tagged(steps, ...)`. Bench: drop a `task.tagged.txt` next to `task.txt` (or set `[run].tagged` in `config.toml`) and the runner picks tagged mode automatically.

Tagged grammar (one step per line; `#` starts a comment, blank lines skipped, `- ` bullet prefix tolerated):

```
click <selector>
type <selector> "text"
goto <url>
wait <ms>
wait_for <selector> [timeout_ms]
press <key>
scroll up|down
evaluate <jsExpr>
screenshot

expect_visible <selector> [timeout_ms]
expect_hidden <selector> [timeout_ms]
expect_text "<substring>"
expect_url <regex>
expect_count <selector> <op> <n>          # op ∈ {==, !=, >, >=, <, <=}
expect_eval <jsExpr> <op> "<expected>"    # + equals / contains / matches
```

Selectors:
- `button "OK"`, `dialog`, `link "Sign in"`, `heading "Title"` — Playwright `get_by_role(role, name=name)`.
- `"Click me"` (bare quoted) or `text:"..."` — `get_by_text`.
- Anything else — handed to `page.locator(...)`. CSS, `[attr=value]`, `data-testid=foo`, xpath= etc. all work.

Use `evaluate` for "compute the answer" and `expect_eval` for "compute and assert" — these are the cheapest assertion shapes (~10ms each, no DOM dance) and the right tool for hidden state, counters, dialog text, anything that's faster to check via JS than via UI traversal. Heavy `expect_visible` / `expect_text` is best for "did the right thing render" gates.

Runtime: `qa_agent/tagged.py::parse_tagged` → `list[Step]`, `execute_step(page, step) -> StepResult`. Selector resolver is `resolve_selector(page, sel)`; `_resolve_selector_args` handles the `<role> "name"` two-token form for action verbs. Timeouts default to `DEFAULT_STEP_TIMEOUT=5000` ms; override per-step with the optional trailing integer arg (e.g. `expect_visible dialog 15000`).

### `evaluate <jsExpr>` DSL action — DOM truth beats vision guessing

The browser DSL has `evaluate <jsExpr>` (`qa_agent/actions.py::_execute_evaluate`). The LLM should reach for it whenever an assertion can be settled by reading the DOM directly — counters, dialog text, hidden state, computed style, `window.__APP_STATE__` — instead of asking vision to interpret a screenshot. Result is JSON-stringified, capped at `EVAL_RESULT_MAX=1500` chars, prefixed `eval -> ...`, and **always** fed back into the conversation (`runtime/fsm_actions.py::act_exec`) so the next LLM turn sees the answer. Wrap multi-statement code as `(()=>{ /*…*/; return x; })()` since bare `throw` / `return` aren't expressions.

This is the single biggest lever against the "vision hallucinates under pressure" failure mode — operators reported Haiku confidently describing UI states that didn't match the screenshot. Anything that can be checked against the DOM should be.

### Diagnostics: console, network, screenshots, flicker

Every browser run automatically captures four streams that the original loop dropped on the floor. None of these are opt-in — they are wired in `qa_agent/agent.py::_attach_diagnostics` and `qa_agent/runtime/fsm_actions.py::_emit_step`.

- **Per-step screenshots — before AND after**. Browser: JPEG (`q60`, `full_page=True`) at `qa_screenshots/run_<UTC>_<pid>/step_NNN.jpg` (post-action) and `step_NNN_pre.jpg` (pre-action, only emitted for `act_exec` steps — `done` paths don't generate one because no DOM action runs). Android: PNG via `device.screenshot(path)`. Paths land on `step_record["screenshot"]` and `step_record["screenshot_pre"]`. Final summary keys: `screenshots: list[str]`, `screenshots_dir: str`. `full_page=True` was deliberate — viewport-only shots inconsistently captured fixed-positioned overlays because of scroll position; the vision capture path additionally calls `window.scrollTo(0, 0)` before each shot for the same reason.
- **Console + uncaught exceptions**. `page.on("console")` + `page.on("pageerror")` cover every page in the context — including new tabs spawned later (MM popups, target=_blank). Records land on `ctx.console_log`; per-step slice is in `step_record["console"]`. Final counter (errors only, not warns): `console_errors`.
- **Failed HTTP responses + request failures**. `context.on("response")` filters status≥400, `context.on("requestfailed")` catches DNS / TLS / aborted. For 4xx/5xx responses we additionally pull `resp.body()` and stash up to 2KB on the record's `body` field — most backend errors carry the actual reason in the body ("validation failed: missing field 'email'") which you need in the audit trail. Per-step slice: `step_record["network"]`. Final counter: `network_errors`.
- **Flicker (sub-second DOM oscillation)**. `qa_agent/browser.py::MUTATION_INIT_SCRIPT` injects a MutationObserver before any page script runs; it writes to a bounded `window.__qa_mutations` ring buffer. After every action `qa_agent/runtime/actions.py::detect_flicker` drains the buffer and emits one event per node-fingerprint that flapped ≥`FLICKER_MIN_FLAPS=4` times within `FLICKER_WINDOW_MS=500`. Per-step slice: `step_record["flicker"]`. Final counter: `flicker_events`.

When console/network produced anything error-level during a step, `_emit_step` builds a compact `[DIAG since last action]` blurb and stashes it on `ctx.pending_diag`. The very next `act_think` prepends it to the user message so the LLM sees diagnostic context **before** committing to an action. The two SYSTEM_PROMPTs (browser / android) tell the agent how to interpret these blocks — don't drop those instructions when editing the prompt.

**Full per-run dumps** of every stream are written next to screenshots when records exist:
- `qa_screenshots/run_<UTC>_<pid>/console.jsonl` — every console event captured (no level filter; the inline DIAG only filters for compactness)
- `.../network.jsonl` — every status≥400 response and every `requestfailed` event
- `.../flicker.jsonl` — every flicker event
- `.../done_reasks.jsonl` — every `done PASS` rejected by the evidence gate, with `step`, `description`, `reason` (a `_evidence_failure_reason` label like `all_checks_failed: no_quoted_text,no_tx_hash,...`), and `verdict` (`reask` / `forced_fail`)

Paths surface in the final summary as `console_log_path`, `network_log_path`, `flicker_log_path`, `done_reasks_log_path`. The full `done_reasks_log` is also inlined in the summary so MCP callers don't need to read the file.

### Failure-mode breakers — finite badges per run

Three counters on `AgentCtx` short-circuit otherwise-budget-burning loops:

- **`parse_errors`** (`runtime/fsm_actions.py::act_classify`). Increments on every `parse_action` returning `("error", ...)`, resets on any clean parse. Reaching `3` forces `PARSED_DONE_FAIL` with `"3 consecutive parse errors — agent emitted prose instead of DSL. Last raw: ..."`. Catches the failure mode where the LLM drifts into narration ("The screenshot was taken. The DSL snapshot shows...") and the gentle nudge alone doesn't recover it.
- **`vision_repeat`** (`runtime/fsm_actions.py::_run_vision`, only on `reason="loop"`). Increments when forced-vision returns the **same** action it returned last time, resets on a different action. Reaching `2` forces `PARSED_DONE_FAIL` with `"Vision stuck: returned `<action>` 2× under loop-vision. Page state is not advancing."`. Catches the failure mode where vision keeps re-confirming a click that the page isn't responding to — instead of burning 5+ steps clicking the same thing, fail visibly.
- **`done_reasks`** (existing — `runtime/actions.py::evidence_verdict`). `≥2` forces `REASKS_EXHAUSTED → DONE_FAIL`. Reasons of every reask now in `done_reasks_log`.

### `--http-creds user:pass` for Basic auth

CLI flag (`--http-creds user:pass`) and MCP `qa_run(http_credentials={"username":..., "password":...})` forward to Playwright's `http_credentials` context kwarg. Resolves Basic-auth challenges across every navigation, fetch, **and EventSource** in the context — the latter is why a `fetch`-monkeypatch via `init_script` isn't enough (SSE doesn't accept custom request headers, so an injected fetch wrapper breaks streaming endpoints).

### Confidence score & quality signals

`AgentCtx.signals` is a cumulative counter dict (`done_reasks`, `hallucinated_ids`, `soft_loops`, `vision_repeats`, `parse_errors`, `flicker`). Distinct from the resettable counters of the same names (`ctx.parse_errors`, `ctx.vision_repeat`) — those drive single-incident breakers; `ctx.signals` accumulates for the whole-run quality picture.

`agent.py::_compute_confidence(ctx)` turns those signals into a score ∈ [0, 1] plus a list of human-readable `uncertainty_reasons`. Weights live in `_CONFIDENCE_WEIGHTS`. The penalty is sub-linear past the first incident (`weight * (1 + 0.5*(n-1))`) so a single flake doesn't collapse the score, but a noisy run drops steeply.

The score is **not a probability** — it's a heuristic CI-gate signal. Operators should treat `PASS with confidence < 0.5` as a soft-PASS that needs human review. Both `signals` and `confidence` ride in the on_finish summary, MCP `qa_run` return dict, and CLI `--json-result` line.

### `--trace` Playwright tracing

`run_task(trace=True)` (CLI: `--trace`, MCP: `qa_run(trace=True)`) starts `context.tracing.start(snapshots=True, screenshots=True, sources=False)` after `_attach_diagnostics` and stops with `tracing.stop(path=<screenshots_dir>/trace.zip)` before `context.close()`. Open with `playwright show-trace <path>` for time-travel debugging — DOM snapshot + screenshot + console + network at every actionable point. ~5–15 MB per run; opt-in.

### `--show-browser` (CLI only)

`--show-browser` overrides `--headless` to off and wires a `before_close` callback that blocks on stdin until Enter. Use this for live inspection when vision is suspected of fabricating observations — reproduce, pause, look at the actual page yourself. **Not safe for CI** (will hang).

### Vision hallucination guard (`runtime/fsm_actions.py::_run_vision`)

Haiku in vision mode sometimes returns `click N` / `type N "..."` with `N` that isn't actually present in the DSL snapshot. The cross-check rejects these: it compares the parsed action's id against the live snapshot ids, appends a `REJECTED ... id N is NOT in the current page snapshot. The snapshot has ids: [...]` user message, sets `step_record["vision_hallucinated"] = {action, id, valid_ids}`, and re-enters `SNAPSHOTTING` so the agent picks again. This catches the most expensive failure mode: vision confidently fabricating an action the page can't satisfy.

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
