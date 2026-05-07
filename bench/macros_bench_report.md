# Macros pipeline real-world benchmark — 2026-05-07 02:11:50Z

- Fixtures: 5 (`real_herokuapp_dynamic_loading, real_herokuapp_login, real_herokuapp_status_500, real_saucedemo_addcart, real_wikipedia_search`)
- Warmup runs: 15 (3 per fixture)
- Post-install runs: 5 suggest + 5 auto
- Mining yield: 2 candidates emitted
- Live-validate verdict: 1 kept / 1 dropped
- Wallclock: 343.8s
- Captures dir: `/tmp/qa_bench_c5_caps`
- Macros out: `/tmp/qa_bench_c5_macros`

## Per-fixture summary (warmup phase)

| fixture | runs | pass_rate | steps̄ | wall̄ (s) | tok_in̄ | tok_out̄ | conf̄ on PASS | conf̄ on FAIL |
|---|---|---|---|---|---|---|---|---|
| real_herokuapp_dynamic_loading | 3 | 1.000 | 3 | 14.558 | 4280 | 93 | 0.950 | 0.000 |
| real_herokuapp_login | 3 | 1.000 | 4 | 14.336 | 9350 | 48 | 0.900 | 0.000 |
| real_herokuapp_status_500 | 3 | 1.000 | 1 | 6.267 | 3051 | 21 | 1.000 | 0.000 |
| real_saucedemo_addcart | 3 | 1.000 | 5.667 | 17.075 | 12940 | 97 | 0.933 | 0.000 |
| real_wikipedia_search | 3 | 1.000 | 4 | 12.916 | 12111 | 60 | 0.925 | 0.000 |


## Confidence ↔ assert_ok correlation

- mean confidence on assert_ok=True : **0.942** (n=15)
- mean confidence on assert_ok=False: **0.000** (n=0)

## Aggregate uncertainty signals (warmup)

| signal | total occurrences |
|---|---|
| done_reasks | 1 |
| hallucinated_ids | 0 |
| soft_loops | 0 |
| vision_repeats | 0 |
| parse_errors | 0 |
| flicker | 18 |

## Mining yield (LLM curator on)

| name | support | length | params |
|---|---|---|---|
| login_with_credentials | 6 | 3 | 2 |
| search_wikipedia_and_evaluate | 3 | 3 | 1 |


## Live-validate verdicts

| name | passed | score | failed step | elapsed (s) | failure |
|---|---|---|---|---|---|
| login_with_credentials | ✓ | 1.000 | - | 4.481 | - |
| search_wikipedia_and_evaluate | ✗ | 0.000 | 1 | 7.507 | TIMEOUT: Locator.click: Timeout 5000ms exceeded.
Call log:
  - waiting for get_b |


## Detection coverage — suggest mode

| fixture | loaded | matches | suggestions | auto_invokes | assert_ok | tok_in | tok_out | wall (s) |
|---|---|---|---|---|---|---|---|---|
| real_herokuapp_dynamic_loading | 1 | 0 | 0 | 0 | ✓ | 4285 | 98 | 14.957 |
| real_herokuapp_login | 1 | 0 | 0 | 0 | ✓ | 9350 | 48 | 14.982 |
| real_herokuapp_status_500 | 1 | 0 | 0 | 0 | ✓ | 3051 | 21 | 6.563 |
| real_saucedemo_addcart | 1 | 0 | 0 | 0 | ✓ | 10749 | 79 | 15.440 |
| real_wikipedia_search | 1 | 0 | 0 | 0 | ✓ | 12111 | 60 | 12.527 |


## Detection coverage — auto mode

| fixture | loaded | matches | suggestions | auto_invokes | assert_ok | tok_in | tok_out | wall (s) |
|---|---|---|---|---|---|---|---|---|
| real_herokuapp_dynamic_loading | 1 | 0 | 0 | 0 | ✓ | 4267 | 80 | 14.585 |
| real_herokuapp_login | 1 | 0 | 0 | 0 | ✓ | 9350 | 48 | 13.995 |
| real_herokuapp_status_500 | 1 | 0 | 0 | 0 | ✓ | 3051 | 21 | 8.954 |
| real_saucedemo_addcart | 1 | 0 | 0 | 0 | ✓ | 10749 | 79 | 14.669 |
| real_wikipedia_search | 1 | 0 | 0 | 0 | ✓ | 12120 | 60 | 12.838 |


## Token deltas — warmup vs post-install (suggest, auto)

| fixture | warmup tok_in̄ | suggest tok_in̄ | suggest Δ% | auto tok_in̄ | auto Δ% |
|---|---|---|---|---|---|
| real_herokuapp_dynamic_loading | 4280 | 4285 | +0.1% | 4267 | -0.3% |
| real_herokuapp_login | 9350 | 9350 | +0.0% | 9350 | +0.0% |
| real_herokuapp_status_500 | 3051 | 3051 | +0.0% | 3051 | +0.0% |
| real_saucedemo_addcart | 12940 | 10749 | -16.9% | 10749 | -16.9% |
| real_wikipedia_search | 12111 | 12111 | +0.0% | 12120 | +0.1% |


### Auto-mode aggregate

- Auto-invocations fired: **0** across 5 runs
- Mean tok_in: warmup=8347 → auto=7907 (-5.3%)

## Raw appendix

- Per-run JSONL captures live under `/tmp/qa_bench_c5_caps`
- Emitted macros under `/tmp/qa_bench_c5_macros`
