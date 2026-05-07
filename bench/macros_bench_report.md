# Macros pipeline real-world benchmark — 2026-05-07 01:22:22Z

- Fixtures: 5 (`real_herokuapp_dynamic_loading, real_herokuapp_login, real_herokuapp_status_500, real_saucedemo_addcart, real_wikipedia_search`)
- Warmup runs: 15 (3 per fixture)
- Post-install runs: 5
- Mining yield: 2 candidates emitted
- Live-validate verdict: 1 kept / 1 dropped
- Wallclock: 283.2s
- Captures dir: `/tmp/qa_bench_a2_caps`
- Macros out: `/tmp/qa_bench_a2_macros`

## Per-fixture summary (warmup phase)

| fixture | runs | pass_rate | steps̄ | wall̄ (s) | tok_in̄ | tok_out̄ | conf̄ on PASS | conf̄ on FAIL |
|---|---|---|---|---|---|---|---|---|
| real_herokuapp_dynamic_loading | 3 | 1.000 | 3 | 14.847 | 4255 | 76 | 0.950 | 0.000 |
| real_herokuapp_login | 3 | 1.000 | 4 | 14.295 | 9350 | 48 | 0.900 | 0.000 |
| real_herokuapp_status_500 | 3 | 1.000 | 1 | 6.446 | 3051 | 21 | 1.000 | 0.000 |
| real_saucedemo_addcart | 3 | 1.000 | 5 | 16.849 | 10917 | 79 | 1.000 | 0.000 |
| real_wikipedia_search | 3 | 1.000 | 4 | 13.962 | 12100 | 60 | 0.933 | 0.000 |


## Confidence ↔ assert_ok correlation

- mean confidence on assert_ok=True : **0.957** (n=15)
- mean confidence on assert_ok=False: **0.000** (n=0)

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
| login_with_credentials | 3 | 4 | 0 |
| search_and_verify_aho_corasick | 3 | 3 | 0 |


## Live-validate verdicts

| name | passed | score | failed step | elapsed (s) | failure |
|---|---|---|---|---|---|
| login_with_credentials | ✓ | 1.000 | - | 3.413 | - |
| search_and_verify_aho_corasick | ✗ | 0.500 | 2 | 8.404 | TIMEOUT: Locator.click: Timeout 5000ms exceeded.
Call log:
  - waiting for locat |


## Detection coverage (post-install runs)

| fixture | loaded | matches | suggestions | auto_invokes | assert_ok | tok_in | tok_out |
|---|---|---|---|---|---|---|---|
| real_herokuapp_dynamic_loading | 1 | 0 | 0 | 0 | ✓ | 4268 | 81 |
| real_herokuapp_login | 1 | 0 | 0 | 0 | ✓ | 9350 | 48 |
| real_herokuapp_status_500 | 1 | 0 | 0 | 0 | ✓ | 3051 | 21 |
| real_saucedemo_addcart | 1 | 0 | 0 | 0 | ✓ | 10749 | 79 |
| real_wikipedia_search | 1 | 0 | 0 | 0 | ✓ | 12099 | 60 |


## Token deltas — warmup vs post-install

| fixture | warmup tok_in̄ | post-install tok_in̄ | delta | delta % |
|---|---|---|---|---|
| real_herokuapp_dynamic_loading | 4255 | 4268 | 13 | +0.3% |
| real_herokuapp_login | 9350 | 9350 | 0 | +0.0% |
| real_herokuapp_status_500 | 3051 | 3051 | 0 | +0.0% |
| real_saucedemo_addcart | 10917 | 10749 | -168 | -1.5% |
| real_wikipedia_search | 12100 | 12099 | -1 | -0.0% |


## Raw appendix

- Per-run JSONL captures live under `/tmp/qa_bench_a2_caps`
- Emitted macros under `/tmp/qa_bench_a2_macros`
