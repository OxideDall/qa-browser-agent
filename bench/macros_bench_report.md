# Macros pipeline real-world benchmark — 2026-05-07 02:28:25Z

- Fixtures: 8 (`real_fail_impossible_text, real_fail_search_no_result, real_fail_tight_steps, real_herokuapp_dynamic_loading, real_herokuapp_login, real_herokuapp_status_500, real_saucedemo_addcart, real_wikipedia_search`)
- Warmup runs: 16 (2 per fixture)
- Post-install runs: 8 suggest + 8 auto
- Mining yield: 2 candidates emitted
- Live-validate verdict: 1 kept / 1 dropped
- Wallclock: 406.4s
- Captures dir: `/tmp/qa_bench_d2_caps`
- Macros out: `/tmp/qa_bench_d2_macros`

## Per-fixture summary (warmup phase)

| fixture | runs | pass_rate | steps̄ | wall̄ (s) | tok_in̄ | tok_out̄ | conf̄ on PASS | conf̄ on FAIL |
|---|---|---|---|---|---|---|---|---|
| real_fail_impossible_text | 2 | 0.000 | 2 | 9.683 | 2937 | 373 | 0.000 | 0.350 |
| real_fail_search_no_result | 2 | 0.000 | 3 | 13.074 | 6695 | 239 | 0.000 | 0.338 |
| real_fail_tight_steps | 2 | 0.000 | 1 | 5.957 | 1320 | 71 | 0.000 | 0.400 |
| real_herokuapp_dynamic_loading | 2 | 1.000 | 3 | 15.758 | 4264 | 77 | 0.950 | 0.000 |
| real_herokuapp_login | 2 | 1.000 | 4 | 15.016 | 9350 | 48 | 0.900 | 0.000 |
| real_herokuapp_status_500 | 2 | 1.000 | 1 | 6.350 | 3051 | 21 | 1.000 | 0.000 |
| real_saucedemo_addcart | 2 | 1.000 | 5 | 15.588 | 10782 | 79 | 1.000 | 0.000 |
| real_wikipedia_search | 2 | 1.000 | 4 | 12.346 | 12091 | 60 | 0.925 | 0.000 |


## Confidence ↔ assert_ok correlation

- mean confidence on assert_ok=True : **0.955** (n=10)
- mean confidence on assert_ok=False: **0.355** (n=5)
- delta (PASS−FAIL): **+0.600** — positive ⇒ confidence does discriminate

## Aggregate uncertainty signals (warmup)

| signal | total occurrences |
|---|---|
| done_reasks | 0 |
| hallucinated_ids | 0 |
| soft_loops | 0 |
| vision_repeats | 0 |
| parse_errors | 0 |
| flicker | 17 |

## Mining yield (LLM curator on)

| name | support | length | params |
|---|---|---|---|
| login_with_credentials | 4 | 3 | 2 |
| search_and_verify_aho_corasick | 2 | 3 | 0 |


## Live-validate verdicts

| name | passed | score | failed step | elapsed (s) | failure |
|---|---|---|---|---|---|
| login_with_credentials | ✓ | 1.000 | - | 4.471 | - |
| search_and_verify_aho_corasick | ✗ | 0.000 | 1 | 7.655 | TIMEOUT: Locator.click: Timeout 5000ms exceeded.
Call log:
  - waiting for get_b |


## Detection coverage — suggest mode

| fixture | loaded | matches | suggestions | auto_invokes | assert_ok | tok_in | tok_out | wall (s) |
|---|---|---|---|---|---|---|---|---|
| real_fail_impossible_text | 1 | 0 | 0 | 0 | ✗ | 2964 | 405 | 9.694 |
| real_fail_search_no_result | 1 | 0 | 0 | 0 | ✗ | 6567 | 232 | 16.408 |
| real_fail_tight_steps | 1 | 0 | 0 | 0 | ✗ | 2645 | 122 | 8.667 |
| real_herokuapp_dynamic_loading | 1 | 0 | 0 | 0 | ✓ | 4284 | 97 | 14.625 |
| real_herokuapp_login | 1 | 0 | 0 | 0 | ✓ | 9350 | 48 | 16.846 |
| real_herokuapp_status_500 | 1 | 0 | 0 | 0 | ✓ | 3051 | 21 | 6.355 |
| real_saucedemo_addcart | 1 | 0 | 0 | 0 | ✓ | 10875 | 79 | 15.422 |
| real_wikipedia_search | 1 | 0 | 0 | 0 | ✓ | 12114 | 60 | 12.892 |


## Detection coverage — auto mode

| fixture | loaded | matches | suggestions | auto_invokes | assert_ok | tok_in | tok_out | wall (s) |
|---|---|---|---|---|---|---|---|---|
| real_fail_impossible_text | 1 | 0 | 0 | 0 | ✗ | 2994 | 481 | 10.605 |
| real_fail_search_no_result | 1 | 0 | 0 | 0 | ✗ | 6567 | 247 | 14.354 |
| real_fail_tight_steps | 1 | 0 | 0 | 0 | ✗ | 2653 | 139 | 9.423 |
| real_herokuapp_dynamic_loading | 1 | 0 | 0 | 0 | ✓ | 4268 | 81 | 14.145 |
| real_herokuapp_login | 1 | 0 | 0 | 0 | ✓ | 9350 | 48 | 12.950 |
| real_herokuapp_status_500 | 1 | 0 | 0 | 0 | ✓ | 3051 | 21 | 7.292 |
| real_saucedemo_addcart | 1 | 0 | 0 | 0 | ✓ | 10749 | 79 | 14.030 |
| real_wikipedia_search | 1 | 0 | 0 | 0 | ✓ | 12118 | 60 | 12.132 |


## Token deltas — warmup vs post-install (suggest, auto)

| fixture | warmup tok_in̄ | suggest tok_in̄ | suggest Δ% | auto tok_in̄ | auto Δ% |
|---|---|---|---|---|---|
| real_fail_impossible_text | 2937 | 2964 | +0.9% | 2994 | +1.9% |
| real_fail_search_no_result | 6695 | 6567 | -1.9% | 6567 | -1.9% |
| real_fail_tight_steps | 1320 | 2645 | +100.4% | 2653 | +101.0% |
| real_herokuapp_dynamic_loading | 4264 | 4284 | +0.5% | 4268 | +0.1% |
| real_herokuapp_login | 9350 | 9350 | +0.0% | 9350 | +0.0% |
| real_herokuapp_status_500 | 3051 | 3051 | +0.0% | 3051 | +0.0% |
| real_saucedemo_addcart | 10782 | 10875 | +0.9% | 10749 | -0.3% |
| real_wikipedia_search | 12091 | 12114 | +0.2% | 12118 | +0.2% |


### Auto-mode aggregate

- Auto-invocations fired: **0** across 8 runs
- Mean tok_in: warmup=6311 → auto=6469 (+2.5%)

## Raw appendix

- Per-run JSONL captures live under `/tmp/qa_bench_d2_caps`
- Emitted macros under `/tmp/qa_bench_d2_macros`
