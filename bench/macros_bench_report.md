# Macros pipeline real-world benchmark — 2026-05-07 01:33:44Z

- Fixtures: 5 (`real_herokuapp_dynamic_loading, real_herokuapp_login, real_herokuapp_status_500, real_saucedemo_addcart, real_wikipedia_search`)
- Warmup runs: 15 (3 per fixture)
- Post-install runs: 5 suggest + 5 auto
- Mining yield: 2 candidates emitted
- Live-validate verdict: 1 kept / 1 dropped
- Wallclock: 341.0s
- Captures dir: `/tmp/qa_bench_b_caps`
- Macros out: `/tmp/qa_bench_b_macros`

## Per-fixture summary (warmup phase)

| fixture | runs | pass_rate | steps̄ | wall̄ (s) | tok_in̄ | tok_out̄ | conf̄ on PASS | conf̄ on FAIL |
|---|---|---|---|---|---|---|---|---|
| real_herokuapp_dynamic_loading | 3 | 1.000 | 3 | 14.644 | 4276 | 89 | 0.950 | 0.000 |
| real_herokuapp_login | 3 | 1.000 | 4 | 13.411 | 9350 | 48 | 0.900 | 0.000 |
| real_herokuapp_status_500 | 3 | 1.000 | 1 | 6.392 | 3051 | 21 | 1.000 | 0.000 |
| real_saucedemo_addcart | 3 | 1.000 | 5 | 16.306 | 10833 | 79 | 1.000 | 0.000 |
| real_wikipedia_search | 3 | 1.000 | 3.667 | 13.426 | 10536 | 55 | 0.925 | 0.000 |


## Confidence ↔ assert_ok correlation

- mean confidence on assert_ok=True : **0.955** (n=15)
- mean confidence on assert_ok=False: **0.000** (n=0)

## Aggregate uncertainty signals (warmup)

| signal | total occurrences |
|---|---|
| done_reasks | 0 |
| hallucinated_ids | 0 |
| soft_loops | 0 |
| vision_repeats | 0 |
| parse_errors | 0 |
| flicker | 18 |

## Mining yield (LLM curator on)

| name | support | length | params |
|---|---|---|---|
| login_with_credentials | 3 | 4 | 0 |
| search_and_verify_aho_corasick | 2 | 3 | 0 |


## Live-validate verdicts

| name | passed | score | failed step | elapsed (s) | failure |
|---|---|---|---|---|---|
| login_with_credentials | ✓ | 1.000 | - | 3.249 | - |
| search_and_verify_aho_corasick | ✗ | 0.500 | 2 | 8.537 | TIMEOUT: Locator.click: Timeout 5000ms exceeded.
Call log:
  - waiting for locat |


## Detection coverage — suggest mode

| fixture | loaded | matches | suggestions | auto_invokes | assert_ok | tok_in | tok_out | wall (s) |
|---|---|---|---|---|---|---|---|---|
| real_herokuapp_dynamic_loading | 1 | 0 | 0 | 0 | ✓ | 4281 | 94 | 15.318 |
| real_herokuapp_login | 1 | 0 | 0 | 0 | ✓ | 9350 | 48 | 13.217 |
| real_herokuapp_status_500 | 1 | 0 | 0 | 0 | ✓ | 3051 | 21 | 6.341 |
| real_saucedemo_addcart | 1 | 0 | 0 | 0 | ✓ | 10749 | 79 | 15.491 |
| real_wikipedia_search | 1 | 0 | 0 | 0 | ✓ | 12070 | 61 | 13.397 |


## Detection coverage — auto mode

| fixture | loaded | matches | suggestions | auto_invokes | assert_ok | tok_in | tok_out | wall (s) |
|---|---|---|---|---|---|---|---|---|
| real_herokuapp_dynamic_loading | 1 | 0 | 0 | 0 | ✓ | 4267 | 80 | 14.146 |
| real_herokuapp_login | 1 | 0 | 0 | 0 | ✓ | 9350 | 48 | 13.526 |
| real_herokuapp_status_500 | 1 | 0 | 0 | 0 | ✓ | 3051 | 21 | 6.336 |
| real_saucedemo_addcart | 1 | 0 | 0 | 0 | ✓ | 10749 | 79 | 16.046 |
| real_wikipedia_search | 1 | 0 | 0 | 0 | ✓ | 12054 | 60 | 12.390 |


## Token deltas — warmup vs post-install (suggest, auto)

| fixture | warmup tok_in̄ | suggest tok_in̄ | suggest Δ% | auto tok_in̄ | auto Δ% |
|---|---|---|---|---|---|
| real_herokuapp_dynamic_loading | 4276 | 4281 | +0.1% | 4267 | -0.2% |
| real_herokuapp_login | 9350 | 9350 | +0.0% | 9350 | +0.0% |
| real_herokuapp_status_500 | 3051 | 3051 | +0.0% | 3051 | +0.0% |
| real_saucedemo_addcart | 10833 | 10749 | -0.8% | 10749 | -0.8% |
| real_wikipedia_search | 10536 | 12070 | +14.6% | 12054 | +14.4% |


### Auto-mode aggregate

- Auto-invocations fired: **0** across 5 runs
- Mean tok_in: warmup=7609 → auto=7894 (+3.7%)

## Raw appendix

- Per-run JSONL captures live under `/tmp/qa_bench_b_caps`
- Emitted macros under `/tmp/qa_bench_b_macros`
