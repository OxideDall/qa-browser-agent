# Macros pipeline real-world benchmark — 2026-05-07 02:38:18Z

- Fixtures: 12 (`real_fail_impossible_text, real_fail_search_no_result, real_fail_tight_steps, real_herokuapp_dynamic_loading, real_herokuapp_infinite_scroll, real_herokuapp_js_alerts, real_herokuapp_login, real_herokuapp_status_500, real_saucedemo_addcart, real_saucedemo_locked_out, real_saucedemo_perf_glitch, real_wikipedia_search`)
- Warmup runs: 24 (2 per fixture)
- Post-install runs: 12 suggest + 12 auto
- Mining yield: 2 candidates emitted
- Live-validate verdict: 2 kept / 0 dropped
- Wallclock: 642.3s
- Captures dir: `/tmp/qa_bench_e_caps`
- Macros out: `/tmp/qa_bench_e_macros`

## Per-fixture summary (warmup phase)

| fixture | runs | pass_rate | steps̄ | wall̄ (s) | tok_in̄ | tok_out̄ | conf̄ on PASS | conf̄ on FAIL |
|---|---|---|---|---|---|---|---|---|
| real_fail_impossible_text | 2 | 0.000 | 2 | 9.280 | 2921 | 328 | 0.000 | 0.350 |
| real_fail_search_no_result | 2 | 0.000 | 3 | 13.052 | 6567 | 247 | 0.000 | 0.350 |
| real_fail_tight_steps | 2 | 0.000 | 2 | 8.506 | 2641 | 136 | 0.000 | 0.400 |
| real_herokuapp_dynamic_loading | 2 | 1.000 | 3 | 14.350 | 4284 | 108 | 0.950 | 0.000 |
| real_herokuapp_infinite_scroll | 2 | 1.000 | 4 | 13.345 | 5694 | 167 | 0.925 | 0.000 |
| real_herokuapp_js_alerts | 2 | 1.000 | 2 | 10.217 | 2941 | 24 | 0.950 | 0.000 |
| real_herokuapp_login | 2 | 1.000 | 4 | 13.328 | 9350 | 48 | 0.887 | 0.000 |
| real_herokuapp_status_500 | 2 | 1.000 | 1 | 6.221 | 3051 | 21 | 1.000 | 0.000 |
| real_saucedemo_addcart | 2 | 1.000 | 5 | 18.221 | 10875 | 79 | 1.000 | 0.000 |
| real_saucedemo_locked_out | 2 | 1.000 | 4 | 15.813 | 8312 | 98 | 1.000 | 0.000 |
| real_saucedemo_perf_glitch | 2 | 1.000 | 5 | 20.102 | 10687 | 63 | 1.000 | 0.000 |
| real_wikipedia_search | 2 | 1.000 | 3.500 | 11.910 | 9697 | 53 | 0.925 | 0.000 |


## Confidence ↔ assert_ok correlation

- mean confidence on assert_ok=True : **0.960** (n=18)
- mean confidence on assert_ok=False: **0.367** (n=6)
- delta (PASS−FAIL): **+0.593** — positive ⇒ confidence does discriminate

## Aggregate uncertainty signals (warmup)

| signal | total occurrences |
|---|---|
| done_reasks | 0 |
| hallucinated_ids | 0 |
| soft_loops | 0 |
| vision_repeats | 0 |
| parse_errors | 0 |
| flicker | 23 |

## Mining yield (LLM curator on)

| name | support | length | params |
|---|---|---|---|
| login_with_credentials | 8 | 3 | 2 |
| scroll_and_count_loaded_items | 2 | 3 | 0 |


## Live-validate verdicts

| name | passed | score | failed step | elapsed (s) | failure |
|---|---|---|---|---|---|
| login_with_credentials | ✓ | 1.000 | - | 4.490 | - |
| scroll_and_count_loaded_items | ✓ | 1.000 | - | 3.746 | - |


## Detection coverage — suggest mode

| fixture | loaded | matches | suggestions | auto_invokes | assert_ok | tok_in | tok_out | wall (s) |
|---|---|---|---|---|---|---|---|---|
| real_fail_impossible_text | 2 | 0 | 0 | 0 | ✗ | 2880 | 269 | 9.361 |
| real_fail_search_no_result | 2 | 0 | 0 | 0 | ✗ | 6567 | 232 | 12.806 |
| real_fail_tight_steps | 2 | 0 | 0 | 0 | ✗ | 2640 | 143 | 8.682 |
| real_herokuapp_dynamic_loading | 2 | 0 | 0 | 0 | ✓ | 4289 | 102 | 17.885 |
| real_herokuapp_infinite_scroll | 2 | 1 | 1 | 0 | ✓ | 5756 | 169 | 14.386 |
| real_herokuapp_js_alerts | 2 | 0 | 0 | 0 | ✓ | 2941 | 24 | 7.646 |
| real_herokuapp_login | 2 | 0 | 0 | 0 | ✓ | 9350 | 48 | 15.984 |
| real_herokuapp_status_500 | 2 | 0 | 0 | 0 | ✓ | 3051 | 21 | 10.492 |
| real_saucedemo_addcart | 2 | 0 | 0 | 0 | ✓ | 10749 | 79 | 14.571 |
| real_saucedemo_locked_out | 2 | 0 | 0 | 0 | ✓ | 8312 | 98 | 12.834 |
| real_saucedemo_perf_glitch | 2 | 0 | 0 | 0 | ✓ | 10687 | 63 | 21.249 |
| real_wikipedia_search | 2 | 0 | 0 | 0 | ✓ | 12088 | 61 | 13.024 |


## Detection coverage — auto mode

| fixture | loaded | matches | suggestions | auto_invokes | assert_ok | tok_in | tok_out | wall (s) |
|---|---|---|---|---|---|---|---|---|
| real_fail_impossible_text | 2 | 0 | 0 | 0 | ✗ | 2994 | 425 | 10.677 |
| real_fail_search_no_result | 2 | 0 | 0 | 0 | ✗ | 6567 | 248 | 13.471 |
| real_fail_tight_steps | 2 | 0 | 0 | 0 | ✗ | 2653 | 148 | 9.345 |
| real_herokuapp_dynamic_loading | 2 | 0 | 0 | 0 | ✓ | 4278 | 91 | 14.140 |
| real_herokuapp_infinite_scroll | 2 | 1 | 0 | 1 | ✓ | 7391 | 194 | 13.485 |
| real_herokuapp_js_alerts | 2 | 0 | 0 | 0 | ✓ | 2941 | 24 | 6.409 |
| real_herokuapp_login | 2 | 0 | 0 | 0 | ✓ | 9350 | 48 | 16.282 |
| real_herokuapp_status_500 | 2 | 0 | 0 | 0 | ✓ | 3051 | 21 | 6.600 |
| real_saucedemo_addcart | 2 | 0 | 0 | 0 | ✓ | 10749 | 79 | 14.314 |
| real_saucedemo_locked_out | 2 | 0 | 0 | 0 | ✓ | 8312 | 98 | 15.735 |
| real_saucedemo_perf_glitch | 2 | 0 | 0 | 0 | ✓ | 17072 | 110 | 24.213 |
| real_wikipedia_search | 2 | 0 | 0 | 0 | ✓ | 12069 | 60 | 12.735 |


## Token deltas — warmup vs post-install (suggest, auto)

| fixture | warmup tok_in̄ | suggest tok_in̄ | suggest Δ% | auto tok_in̄ | auto Δ% |
|---|---|---|---|---|---|
| real_fail_impossible_text | 2921 | 2880 | -1.4% | 2994 | +2.5% |
| real_fail_search_no_result | 6567 | 6567 | +0.0% | 6567 | +0.0% |
| real_fail_tight_steps | 2641 | 2640 | -0.0% | 2653 | +0.5% |
| real_herokuapp_dynamic_loading | 4284 | 4289 | +0.1% | 4278 | -0.1% |
| real_herokuapp_infinite_scroll | 5694 | 5756 | +1.1% | 7391 | +29.8% |
| real_herokuapp_js_alerts | 2941 | 2941 | +0.0% | 2941 | +0.0% |
| real_herokuapp_login | 9350 | 9350 | +0.0% | 9350 | +0.0% |
| real_herokuapp_status_500 | 3051 | 3051 | +0.0% | 3051 | +0.0% |
| real_saucedemo_addcart | 10875 | 10749 | -1.2% | 10749 | -1.2% |
| real_saucedemo_locked_out | 8312 | 8312 | +0.0% | 8312 | +0.0% |
| real_saucedemo_perf_glitch | 10687 | 10687 | +0.0% | 17072 | +59.7% |
| real_wikipedia_search | 9697 | 12088 | +24.7% | 12069 | +24.5% |


### Auto-mode aggregate

- Auto-invocations fired: **1** across 12 runs
- Mean tok_in: warmup=6418 → auto=7286 (+13.5%)

## Raw appendix

- Per-run JSONL captures live under `/tmp/qa_bench_e_caps`
- Emitted macros under `/tmp/qa_bench_e_macros`
