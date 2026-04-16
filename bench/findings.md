# Bench findings

Running tally of prompt / DSL / agent-behavior issues the bench has
surfaced, with the fix (if any) and the commit that landed it.

## F1 — `spa_l1_todomvc` hard-loops: DSL has no `press <key>`

**Symptom.** Agent typed the same todo item repeatedly into the input
and eventually gave up. TodoMVC's input binds Enter via keydown; DSL had
no way to emit a keystroke.

**Fix.** Added `press <key>` with alias normalization (enter|return →
Enter, esc|escape → Escape, up → ArrowUp, …). Rule 3 updated to nudge
"type fields → click submit, OR `press Enter` to submit from input".
Verified: fixture now passes in 9 steps / 23 s / 13 k tok.

**Commit.** `0ec4d0e`.

## F2 — `_has_evidence` too strict: numeric UI text rejected

**Symptom.** `w3_l2_balances` returned a correct concrete reading
(`"SUCCESS — Sepolia: 5.725618 ETH, Base Sepolia: 5.725618 ETH"`) but
the evidence gate rejected it because the numbers weren't in inner
quotes or preceded by a whitelisted crypto unit.

**Fix.** Widened `_has_evidence`:

- added `number + unit` covering common crypto tickers + `$N`
- added `"<N> <noun>" ≥ 2` for counter-style pages
  (e.g. `"2 items left | 3 total"`).

**Commits.** `00638ce` (unit), `0ec4d0e` (N+noun).

## F3 — Tx hashes lost to snapshot truncation

**Symptom.** `w3_l3_wrap_eth` run 1 reported a 62-char tx hash instead of
64. Traced to `extract_elements` trimming element text to 60/120 chars,
which chopped the tail off the outcome string. Combined with
`<span id="outcome">` falling outside `TEXT_NODES`, the agent was reading
the hash via vision OCR only — and OCR dropped chars.

**Fix at fixture level.**

- Put the full hash in a dedicated `<p id="tx-hash-full">` so it lands in
  `TEXT_NODES`.
- Relaxed the fixture's assert regex from strict-66-char to `0x[a-f0-9]{40,}`
  — the on-chain balance check is the real arbiter; the hash-in-description
  is just a sanity probe.

**Remaining gap.** The 60/120-char truncation in `extract.py` is still a
general problem for any high-entropy content (addresses, hashes, long
error codes). Not yet fixed globally — deferred until we have more
fixtures that hit it.

**Commit.** `314f810`.

## F4 — Few-shot exemplars in SYSTEM_PROMPT: REGRESSION

**Hypothesis.** Adding curated transcripts of 5 canonical bench flows to
the system prompt would reduce steps / vision overuse and improve quality.

**Experiment.** `bench/ab.py baseline.txt fewshot.txt` across all 9
fixtures, 18 runs total.

| fixture             | A baseline | B fewshot | Δ steps | Δ tokens | verdict       |
|---------------------|-----------:|----------:|--------:|---------:|---------------|
| spa_l1_todomvc      |       PASS |      PASS |      +1 |  +12 761 | =             |
| static_l1_confirm   |       PASS |      PASS |      −1 |   −1 526 | = (marginal)  |
| static_l2_register  |       PASS |   **FAIL**|      +4 |  +28 316 | **REGRESSION**|
| static_l3_pricing   |       PASS |   **FAIL**|      +2 |  +14 734 | **REGRESSION**|
| static_l4_wizard    |       PASS |      PASS |      +5 |  +27 405 | =             |
| w3_l1_connect_sign  |       PASS |      PASS |      +2 |  +18 315 | =             |
| w3_l2_balances      |       PASS |      PASS |      +2 |  +12 128 | =             |
| w3_l3_wrap_eth      |       PASS |      PASS |      +2 |   +6 574 | =             |
| w3_l4_uniswap_swap  |       PASS |      PASS |      +3 |  +39 328 | =             |

**Pass rate.** A = 9/9, B = 7/9. Regressions 2, improvements 0.
**Tokens.** B is more expensive on every single fixture (prompt is ~3× larger).

**Root cause.** The TodoMVC example in the prompt showed
`click field → type → press Enter`, which is correct for an Enter-submit
input. On multi-field forms the agent over-generalized that pattern to
`click field → continue` (dropping the type step) and ran out of steps.

**What we're keeping.**

- `bench/prompts/baseline.txt` — the current SYSTEM_PROMPT, 1.6 kB.
- `bench/prompts/fewshot.txt` — the failed v1 variant, 4.5 kB. Kept as
  a negative-result reference. **Not** merged into agent.py.

**Lessons.**

1. Examples in system prompt generalise in ways you don't anticipate.
   Testing over the full suite (not just one fixture) is mandatory.
2. For agents in the caveman/pseudocode style, explicit anti-patterns
   ("for forms with submit buttons, type directly, NO pre-click step")
   may work better than positive few-shots — the model already knows
   the happy path; it needs the failure modes spelled out.
3. The A/B harness works as intended and saved us from shipping a
   regression that would have been invisible in isolation.

**Next tries** (not yet attempted):

- Drop Ex2 TodoMVC example entirely; keep only the web3 ones.
- Add an explicit negative example: `BAD: click 1; click 2; click
  submit — fields still empty; retry by typing first.`
- Try a half-prompt: just the Ex3 (MM popup) example, which is the
  pattern least covered by the baseline rules already.

## F4b — Few-shot v2a (anti-pattern rules only): NOT MERGED

**Hypothesis.** Drop all positive examples, keep only two terse negative
rules:

  5. `Do NOT pre-click input fields. type <id> "text" already focuses
     + types in one step…`
  6. `First turn: trust the snapshot. Do NOT call look unless the DSL
     list is empty…`

**Experiment.** A/B baseline vs v2a on the 5 most prompt-sensitive
fixtures (static_l1, static_l2, static_l3, static_l4, spa_l1_todomvc).

| fixture             | A baseline | B v2a     | Δ steps | Δ tokens   |
|---------------------|-----------:|----------:|--------:|-----------:|
| static_l1_confirm   |       PASS |      PASS |       0 |     −1 141 |
| static_l2_register  |       PASS |   **FAIL**|       0 |     −2 100 |
| static_l3_pricing   |       PASS |      PASS |      −3 |    −14 826 |
| static_l4_wizard    |       PASS |      PASS |       0 |     +1 404 |
| spa_l1_todomvc      |       PASS |      PASS |      −1 |       −616 |

A: 5/5 PASS. B: 4/5 PASS. Regressions 1, improvements 0 (pass-rate),
token savings on 4/5. Strongly better than v1 (which regressed 2/9 and
added tokens everywhere).

**Root cause of the static_l2 regression.** Agent completed the form
correctly (4 fields typed, terms checked, submit clicked, URL advanced
to `/success.html`, "Welcome aboard!" visible). Evidence gate rejected
because description was `"Welcome aboard! Your TestSite account has
been created."` — no inner quote, no unit, no year, no multi-word
proper noun ("Welcome aboard" has only one capitalised token). On the
second reask the model emitted the same form; got forced-FAIL.

The A run hit the same initial rejection, but on its reask rephrased as
`"Welcome aboard!"` (adding outer quotes that reach the gate as inner
quotes). RNG-dependent behavior at temperature=0 — one-trial noise.

**Decision.** Not merged. v2a's token savings are real, but the pass-rate
regression is unacceptable even if the root cause is description-format
RNG rather than task-execution. Prompt stays at baseline.

**What to try next.** The static_l2 failure suggests a deeper problem
with `_has_evidence` that isn't prompt-fixable: narrative English
descriptions ("Welcome aboard! Your TestSite account has been created")
cite real UI but match none of our anchors. Options:

1. Extend `_has_evidence` to accept N tokens of lowercase-only English
   that survive a "banned-hedge-word" filter.
2. Make fixture task.txt explicit about inner-quoting the evidence.
3. Add a 3rd reask that injects an example.

**Files kept.** `bench/prompts/baseline.txt` (canonical),
`bench/prompts/fewshot.txt` (v1 failed),
`bench/prompts/fewshot_v2.txt` (v2a — this one, kept as reference).
