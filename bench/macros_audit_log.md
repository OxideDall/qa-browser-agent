# Macros pipeline — audit journey (A → E)

This file tracks the methodical-with-proof-audits sequence that took
the macro pipeline from "infra is wired but real-world brittle" to
"end-to-end measurable on 12 real-site fixtures with calibrated
confidence". Each step reports actual numbers from real bench runs
on public test sites (the-internet.herokuapp.com, saucedemo.com,
en.wikipedia.org), no synthetic data.

The current snapshot of one bench run lives in
[`macros_bench_report.md`](macros_bench_report.md). This file is the
delta history.

## Baseline — commit `9833fc1`

First real-world bench: 5 fixtures × 3 iter, no FAIL fixtures, naive
emit pipeline.

| metric | baseline |
|---|---|
| Warmup pass rate | 15/15 (100%) |
| Confidence on PASS | 0.957 (n=15) |
| Confidence on FAIL | _no data — all PASS_ |
| Mining candidates | 3 (incl. 1 silent name collision) |
| Live-validate | 1 kept, 1 dropped, 1 silently overwritten |
| Detection — suggest | 1/5 fixtures matched |
| Detection — auto | _not measured_ |
| Token deltas | ±0.5% (no real saving from suggest) |

Known issues at baseline:
- LLM curator can produce same name for two different patterns; emit
  silently overwrites — collision invisible to caller.
- Vision-path actions skip `target_role` annotation; miner sees them
  as different vocabulary tokens than direct-path actions, splitting
  what should be one mining cluster.
- HTML tag `input` becomes the role classifier; downstream
  Playwright `get_by_role("input")` doesn't exist → broken selectors.
- `${param}` substitutions emitted unquoted → tagged-parser
  ambiguity, `type textbox tomsmith` interpreted as
  role+accessible-name instead of role+text.
- emit has no self-check; broken bodies installed and only caught
  at expensive live-validate time.
- Confidence formula counts only agent self-signals; doesn't observe
  ctx.status, so a FAIL run with no signals scores 1.0.
- All warmup fixtures so easy that Haiku always passed → no FAIL
  side data for confidence calibration.

## Step A (`1673a9f`) — emit collision guard + target_role in vision

| change | before → after |
|---|---|
| LLM curator silent name overwrite | first-mined wins; second skipped with explicit reason in summary |
| `target_role` on vision-path actions | absent → populated |
| Mining yield | 3 candidates with 1 silent overwrite → 2 candidates with 1 explicit `duplicate name` skip |
| Live-validate flake | login sometimes timed out → reproducible PASS |

Audit performed by full real-world bench (5 fixtures × 3 iter) twice;
collision skip surfaced in summary's `skipped` array.

## Step B (`948f7ab`) — auto-mode bench phase

| change | before → after |
|---|---|
| Bench measures only suggest mode | bench measures BOTH suggest and auto mode per run |
| Token-delta table | warmup vs single post-install column → warmup vs suggest vs auto with delta-% |
| New section | "Auto-mode aggregate" with total auto-invocations + mean token delta |

Audit revealed: **0 auto-invocations even with QA_AUTO_MACRO=1**.
Mined macro `login_with_credentials` Aho-matched at runtime
(verified by debug instrumentation in Step A audit), but the
precondition gate correctly rejected the fire because the matched
position was after page navigation to `/inventory.html`, not the
recorded `/` precondition.

Honest finding documented: auto-mode infrastructure works; mining
without boundary detection produces malformed cross-page patterns
that can't fire in production. Phase 4 area.

## Step C (`f0a043c`) — selector hardening

Five layered fixes that took the emit pipeline from
"timeout-at-replay" to "compiles, parses, replays clean".

1. **ARIA role mapping** (`fsm_actions._aria_role_from_el`):
   `<input type=text>` → `textbox`, not `input`.
2. **Baked accessible names** for click/hover when consistent across
   occurrences: `click button "Login"` instead of role-only.
3. **Quoted param substitutions** in emit: `"${username}"` so
   compile_macro produces `"tomsmith"` (text), not bare `tomsmith`
   (parsed as accessible name).
4. **Tagged DSL disambig** in `_h_type`: last-arg-is-text convention,
   so `type textbox "tomsmith"` always means "type tomsmith into the
   first textbox", never "type empty into textbox named tomsmith".
5. **Emit self-check** rejects bodies that don't compile + parse
   against their own examples; broken bodies never written to disk.

Audit before fixes:
- `login_with_credentials` body: `type input "tomsmith" / type input
  "secret_sauce" / click input "Login"` — wrong ARIA role → live-validate
  TIMEOUT at step 1.

Audit after all 5 fixes:
- `login_with_credentials` body: `type textbox "${username}" / type
  textbox "${password}" / click button "Login"` — properly
  parameterised, ARIA-correct, baked button name.
- `meta.params`: `[{name: username, type: string}, {name: password,
  type: string}]`.
- `meta.preconditions.url_templates`: `[herokuapp/login, saucedemo/]`
  — cross-site pattern.
- `meta.examples`: 2 entries, both credential pairs.
- Live-validate: ✓ PASS, score 1.000, 4.5s.

Known unresolved at end of Step C: post-install detection still
shows 0 matches across all fixtures even though Aho should match.
Investigation deferred.

## Step D (`610d6b3`) — provocation fixtures + status-aware confidence

Three FAIL-by-design fixtures (`real_fail_impossible_text`,
`real_fail_tight_steps`, `real_fail_search_no_result`) populate
the FAIL side of confidence calibration.

Audit BEFORE confidence formula fix (warmup, repeat=2, 8 fixtures):

| metric | value |
|---|---|
| conf̄ on PASS | 0.953 (n=10) |
| conf̄ on FAIL | 0.967 (n=6) — **higher than PASS!** |
| delta | -0.014 |

Confidence wasn't observing ctx.status; runs with no agent
self-signals scored ~1.0 even when the run died (status=ERROR via
budget exhaustion or status=FAIL via done FAIL).

Fix added explicit terminal-state penalty:
- `status == "FAIL"` → score -= 0.6
- `status == "ERROR"` → score -= 0.8

Audit AFTER fix:

| metric | value |
|---|---|
| conf̄ on PASS | 0.955 (n=10) |
| conf̄ on FAIL | 0.355 (n=5) |
| **delta** | **+0.600** |

`confidence < 0.5` is now an empirically-meaningful threshold.

## Step E (`<this commit>`) — harder real flows + final picture

Four edge-case fixtures added to broaden coverage:

- `real_saucedemo_locked_out` — login form rejects locked account,
  agent must catch error banner.
- `real_saucedemo_perf_glitch` — login as slow user (5s artificial
  delays); tests timing tolerance.
- `real_herokuapp_infinite_scroll` — scroll until ≥3 items render.
- `real_herokuapp_js_alerts` — trigger native JS alert, verify
  result text (Playwright auto-accepts).

Final audit (12 fixtures × 2 iter + mine + live_validate +
suggest-detect + auto-detect):

| metric | value |
|---|---|
| Total runs | 24 warmup + ~25 detect = 49 |
| Wallclock | ~9 minutes |
| Pass rate (PASS-by-design) | 18/18 (100%) |
| Pass rate (FAIL-by-design) | 0/6 (correct: they should fail) |
| Confidence on PASS | **0.960** (n=18) |
| Confidence on FAIL | **0.367** (n=6) |
| **Confidence delta** | **+0.593** — strong discriminator |
| Flicker events captured | 23 across 24 runs |
| Mining candidates | 2 emitted, **both pass live-validate** |
| `login_with_credentials` | len=3, support=8, params=[username, password] |
| `scroll_and_count_loaded_items` | len=3, support=2 |
| Auto-invocations fired | **1 / 12 post-install runs** (proof-of-life) |
| Token delta auto vs warmup | +13.5% (auto adds extra macro execution overhead) |

## What works at the end of Step E

- Capture pipeline writes per-step JSONL with signature, target_role,
  target_name; sandboxed via `QA_CAPTURES_DIR`.
- Miner produces clean param-extracted multi-site macros; collision
  guard prevents silent overwrites; LLM curator names them
  semantically.
- Emit's self-check refuses to install bodies that don't compile +
  parse against their own examples.
- Live-validate exercises emitted macros against real browsers and
  drops broken ones.
- Online MacroFSM (Aho-Corasick + child FSM + bridge) loads installed
  macros, fires matches when patterns appear in the live stream,
  applies cooldown + precondition gates before suggesting / auto-
  invoking.
- Confidence score discriminates PASS from FAIL by ~0.6 — usable
  CI gate.
- Bench fixture (`bench.runner static_macro_smoke`) provides CI
  coverage for the loader → tagged DSL `macro` verb → library →
  compile → executor chain.

## Open issues — remaining R&D scope

1. **Mining boundary detection (Phase 4)**. Mined patterns can cross
   page navigation boundaries (login flow + post-login first action
   end up in one pattern). Current macros work because precondition
   gate filters bad fires, but auto-invocation rate is low because
   most candidates are mis-bounded. Solution would be split mining
   sequences at large struct_hash deltas + URL template changes.
2. **Online detection coverage low**. Only 1 auto-invocation across
   12 runs — patterns are too specific. Better mining vocabulary
   (clustering similar tokens) or fuzzy Aho matching could raise
   coverage. APTED / fuzzy tree edit distance is the headline
   Phase 4 R&D.
3. **Wikipedia mined-macro drops**. The agent clicks links whose
   accessible name is a noisy concat of nav text + link text;
   target_name baking captures the noise. Could improve by
   detecting concatenated-text patterns in the classifier or by
   trimming common nav prefixes/suffixes.
4. **Token deltas don't show savings yet**. Suggest mode by design
   doesn't save tokens; auto mode adds macro-exec overhead before
   the agent's own first action. Real savings would need
   pre-emptive macros that can replace ≥3 LLM turns; current
   3-step macros barely cover one back-and-forth.

These are documented for the next iteration. None block the
pipeline being usable for ops today.

---

# R&D iterations (Phase 1 → Phase 3 + G1 → G4)

After Step E baseline (real-world bench), several rounds of
honest measurement + targeted fixes lifted detection coverage
from 1/12 invocations to 6/12 with the worst-case auto-mode
overhead from +311% down to +128%, and the **mean** auto-mode
overhead from +59.7% to +1.5%. Each round commit / audit pair
is committed separately for traceability.

## R&D Phase 1 (`de012dd`) — page-boundary segmentation + bridge ARIA fix

Two fixes that unblocked detection from 0 matches to first match.

**Boundary segmentation** (`miner/boundaries.py`). Mining was
producing cross-page N-grams that the precondition gate
correctly rejected at runtime. New `segment_trace(trace)` splits
each capture at `pre_signature.url_template` change → mining
sees within-page subsequences. Default `split_by_page=True`.

**Bridge ARIA fix** (`online/vocab.py`). Step C added
`_aria_role_from_el` so step records carried `target_role=textbox`
for `<input type=text>`. The MINER picked it up correctly (via
step_record), but the BRIDGE re-resolved role from the live
snapshot using the OLD path (`el.role || el.tag` ⇒ raw `input`).
Aho-Corasick saw `(type, input)` tokens while macros expected
`(type, textbox)` — never matched.

Fix: bridge reads `step_record["target_role"]` directly. Single
source of truth.

Audit: saucedemo addcart auto-mode tokens fed went from
`(type, input)` → `(type, textbox)`; Aho-Corasick state
progressed through pattern; first match fired.

Open finding: match fires AT END of pattern (after agent already
did the actions). Auto-invoke at that point is redundant.

## R&D Phase 2 (`929ceb2`) — page-driven pre-emption + URL-anchored examples

**Page-driven pre-emption**. New event `PAGE_READY` fires from
parent's `SNAPSHOTTING → THINKING` (just before `act_think`
calls the LLM). Bridge listens for two parent transitions now:

```
SNAPSHOTTING → THINKING  (SNAPSHOT_READY) → PAGE_READY
THINKING → DISPATCHING   (LLM_REPLIED)    → ACTION_SEEN
```

`act_page_ready` scans installed macros' preconditions against
the current page signature; first match (cooldown clean) gets
suggested or auto-invoked **before** the LLM thinks. Genuine
turn replacement instead of post-hoc confirmation.

**URL-anchored examples** (`miner/emit.py`). Multi-site mined
macros store examples as `{"url_template": "...", "params": {...}}`
now. `_params_from_examples(macro, parent_ctx)` matches the
live page's url_template against examples' anchors —
saucedemo run gets saucedemo creds, herokuapp run gets
herokuapp creds.

Audit: page-driven match on saucedemo at step 2 (before any
LLM action), correct creds picked.

Open finding: `[macro auto-invoke]` print appeared but macro
never actually executed — LLM-path `parse_action` didn't know
the verb yet.

## R&D Phase 3 (`8c9a1a1`) — actual LLM-path execution + nth-indexed selectors

**LLM-path macro verb** (`actions.py`). Added `macro` to
recognized command tuple, wrote `_execute_macro(page, args)` that
loads + compiles + runs nested via `tagged.execute_step`. Result
goes back into the LLM conversation as user_msg
("macro 'X' OK: 3/3 sub-steps. Now on '<url>'.").

**nth-indexed selectors** (`tagged.py` + `miner/emit.py`).
`type textbox` × 2 in pattern previously both targeted nth(0),
overwriting each other on the username field. New `<role>:<n>`
selector form (`textbox:0`, `textbox:1`) disambiguates. emit
auto-applies when (verb, role) repeats in pattern.

Audit: saucedemo login auto-invoke now actually executes,
navigates to `/inventory.html`, run PASS.

Open finding: total run tokens went UP (33k vs 11k warmup) —
agent over-explores after macro returns.

## G1 (`5bb1e0c`) — full bench audit + validate-anchored-examples fix

Live-validate had a hidden bug from R2: `_pick_example_params`
expected required param names as direct keys, but examples
moved to anchored shape `{"url_template": "...", "params": {...}}`.
Login macro was being false-negative-dropped from the catalog
in every bench run. Fixed `_params_of(ex)` helper accepting
both shapes.

Audit before fix: 1/12 auto-invocations (only scroll macro).
Audit after fix: 10/12 — **10× coverage jump**. login, addcart,
locked_out, perf_glitch all auto-invoking.

But aggregate tokens spiked +59.7% — multi-firing on
locked_out / perf_glitch fixtures (3 invocations each).

## G2 (`5216e26`) — run-lifetime success lock

Step-window cooldown wasn't enough: page-ready re-fires on
every snapshot of a stuck-on-login page. Run-lifetime success
lock blocks re-trigger of any macro that already returned OK.

```python
# AgentCtx field
macro_succeeded_names: set = field(default_factory=set)

# Set by act_exec when a macro action returns "OK:"
# Read by act_on_action + act_page_ready before cooldown check
```

Audit: locked_out invocations 3 → 1, perf_glitch 3 → 1.
Aggregate Δ: +59.7% → **+32.1%** (27 pp improvement).
Per-fixture: locked_out +227% → +137%, perf_glitch +311% → +154%.

Wins stayed (login -43.9%, infinite_scroll -25.8%).

## G3 (`f07f32f`) — relaxed mining params, null result

Hypothesis: lower min_len 3→2 + min_segment_len 2→1 would
mine more atomic macros, raising coverage past 6/12.

Result: +1 candidate emitted (`click_button_and_wait`), but
live-validate **dropped it** (TIMEOUT — generic 2-step macro
without page-grounded selectors can't bind reliably). Aggregate
Δ unchanged.

Honest finding: relaxing thresholds alone doesn't lift
coverage. Atomic 2-step macros are too underspecified — their
(verb, role) tuples match anywhere, but their selectors aren't
grounded enough to replay deterministically. Real coverage
growth needs more captures, per-fixture mining, or fuzzy match
relaxation in the online detector — none are quick wins.

## G4 (`07e51c3`) — SYSTEM_PROMPT documents `macro` verb

Suggest-mode hadn't been saving tokens because the LLM didn't
know the macro invocation syntax. SYSTEM_PROMPT didn't list
`macro` as a DSL verb — agents saw `[MACRO HINT]` lines as
English context and didn't know to emit them as actions.

Fix: SYSTEM_PROMPT entry for `macro <name> [k=v]...` with
example + explicit "copy the suggested invocation" guidance.

Audit:

| fixture | warmup | suggest | suggest Δ% | auto | auto Δ% |
|---|---|---|---|---|---|
| real_herokuapp_login | 24375 | 18341 | **-24.8%** | 5804 | **-76.2%** |
| real_herokuapp_infinite_scroll | 6342 | 6342 | 0.0% | 4777 | -24.7% |
| real_saucedemo_addcart | 14964 | 15027 | +0.4% | 12186 | **-18.6%** |
| real_saucedemo_locked_out | 9185 | 9122 | -0.7% | 21019 | +128.8% |
| real_saucedemo_perf_glitch | 16979 | 18634 | +9.7% | 29405 | +73.2% |

Aggregate: warmup 9107 → auto **+1.5%** (was +59.7% at G1).

Suggestions actually accepted by LLM (matches=N, suggestions=N
both > 0 on multiple fixtures). Suggest mode now produces real
savings (login -24.8%) without the worst-case blowups that
auto mode shows on wrong-context fixtures.

# Production-grade recommendation (end of G4)

```
default mode = suggest                  # safe, ~25% win on tight matches
opt-in       = QA_AUTO_MACRO=1           # bigger wins (-76% login),
                                         # risky on wrong-context (+128%
                                         # locked_out, +73% perf_glitch)
```

Suggest mode is now operationalisable. Auto mode requires
operator-curated macro library + trust per task before wide
deployment.

# Open R&D directions (after G4)

1. **Per-task example selection** — auto-invoke picks creds from
   first matching url_template; locked_out fixture's task says
   "use locked_out_user" but auto picks `standard_user`. LLM
   curator could hint which example matches which task semantics,
   or task-text grep for username overrides.
2. **Detection coverage** — only 2 macros installed across 12
   diverse fixtures. Mining from more captures (across multiple
   bench iterations / real production runs) would surface more
   patterns. Per-fixture mining as alternate strategy.
3. **Wrong-context auto-invoke gating** — when LLM has typed
   different creds than the auto-invoke's example, success-lock
   doesn't help. Could detect "page didn't navigate after macro"
   (struct_hash unchanged, url unchanged) and treat as
   unsuccessful → don't lock + maybe roll back.
4. **APTED / fuzzy Aho** — when patterns differ slightly across
   sites (login button vs sign-in link), exact matching misses.
   Out of scope for short-term.
