# Macros pipeline real-world benchmark — 2026-05-07 05:21:12Z

- Fixtures: 12 (`real_fail_impossible_text, real_fail_search_no_result, real_fail_tight_steps, real_herokuapp_dynamic_loading, real_herokuapp_infinite_scroll, real_herokuapp_js_alerts, real_herokuapp_login, real_herokuapp_status_500, real_saucedemo_addcart, real_saucedemo_locked_out, real_saucedemo_perf_glitch, real_wikipedia_search`)
- Warmup runs: 24 (2 per fixture)
- Post-install runs: 12 suggest + 12 auto
- Mining yield: 3 candidates emitted
- Live-validate verdict: 2 kept / 1 dropped
- Wallclock: 758.7s
- Captures dir: `/tmp/qa_bench_g4_caps`
- Macros out: `/tmp/qa_bench_g4_macros`

## Per-fixture summary (warmup phase)

| fixture | runs | pass_rate | steps̄ | wall̄ (s) | tok_in̄ | tok_out̄ | conf̄ on PASS | conf̄ on FAIL |
|---|---|---|---|---|---|---|---|---|
| real_fail_impossible_text | 2 | 0.000 | 2 | 9.764 | 3231 | 315 | 0.000 | 0.350 |
| real_fail_search_no_result | 2 | 0.000 | 3 | 13.396 | 7053 | 221 | 0.000 | 0.350 |
| real_fail_tight_steps | 2 | 0.000 | 2 | 11.081 | 3075 | 280 | 0.000 | 0.400 |
| real_herokuapp_dynamic_loading | 2 | 1.000 | 3 | 14.284 | 4696 | 23 | 0.938 | 0.000 |
| real_herokuapp_infinite_scroll | 2 | 1.000 | 4 | 14.541 | 6342 | 176 | 0.938 | 0.000 |
| real_herokuapp_js_alerts | 2 | 1.000 | 2 | 7.119 | 3265 | 24 | 0.950 | 0.000 |
| real_herokuapp_login | 2 | 1.000 | 9 | 30.514 | 24375 | 140 | 0.900 | 0.000 |
| real_herokuapp_status_500 | 2 | 1.000 | 1 | 7.270 | 3375 | 21 | 1.000 | 0.000 |
| real_saucedemo_addcart | 2 | 1.000 | 6 | 17.531 | 14964 | 89 | 0.800 | 0.000 |
| real_saucedemo_locked_out | 2 | 1.000 | 4 | 15.190 | 9185 | 98 | 1.000 | 0.000 |
| real_saucedemo_perf_glitch | 2 | 1.000 | 6.500 | 26.174 | 16979 | 170 | 0.800 | 0.000 |
| real_wikipedia_search | 2 | 1.000 | 4 | 15.899 | 12739 | 60 | 0.925 | 0.000 |


## Confidence ↔ assert_ok correlation

- mean confidence on assert_ok=True : **0.917** (n=18)
- mean confidence on assert_ok=False: **0.367** (n=6)
- delta (PASS−FAIL): **+0.550** — positive ⇒ confidence does discriminate

## Aggregate uncertainty signals (warmup)

| signal | total occurrences |
|---|---|
| done_reasks | 4 |
| hallucinated_ids | 0 |
| soft_loops | 0 |
| vision_repeats | 0 |
| parse_errors | 0 |
| flicker | 22 |

## Mining yield (LLM curator on)

| name | support | length | params |
|---|---|---|---|
| login_with_credentials | 8 | 3 | 2 |
| scroll_and_count_loaded_items | 2 | 3 | 0 |
| click_button_and_wait | 2 | 2 | 0 |


## Live-validate verdicts

| name | passed | score | failed step | elapsed (s) | failure |
|---|---|---|---|---|---|
| click_button_and_wait | ✗ | 0.000 | 1 | 6.688 | TIMEOUT: Locator.click: Timeout 5000ms exceeded.
Call log:
  - waiting for get_b |
| login_with_credentials | ✓ | 1.000 | - | 8.345 | - |
| scroll_and_count_loaded_items | ✓ | 1.000 | - | 3.856 | - |


## Detection coverage — suggest mode

| fixture | loaded | matches | suggestions | auto_invokes | assert_ok | tok_in | tok_out | wall (s) |
|---|---|---|---|---|---|---|---|---|
| real_fail_impossible_text | 2 | 0 | 0 | 0 | ✗ | 3205 | 290 | 9.304 |
| real_fail_search_no_result | 2 | 0 | 0 | 0 | ✗ | 7053 | 233 | 14.043 |
| real_fail_tight_steps | 2 | 1 | 1 | 0 | ✗ | 3074 | 268 | 10.549 |
| real_herokuapp_dynamic_loading | 2 | 0 | 0 | 0 | ✓ | 4696 | 23 | 14.340 |
| real_herokuapp_infinite_scroll | 2 | 2 | 1 | 0 | ✓ | 6342 | 176 | 13.526 |
| real_herokuapp_js_alerts | 2 | 0 | 0 | 0 | ✓ | 3265 | 24 | 7.688 |
| real_herokuapp_login | 2 | 2 | 2 | 0 | ✓ | 18341 | 209 | 27.416 |
| real_herokuapp_status_500 | 2 | 0 | 0 | 0 | ✓ | 3375 | 21 | 7.092 |
| real_saucedemo_addcart | 2 | 1 | 1 | 0 | ✓ | 15027 | 89 | 19.229 |
| real_saucedemo_locked_out | 2 | 1 | 1 | 0 | ✓ | 9122 | 98 | 15.174 |
| real_saucedemo_perf_glitch | 2 | 1 | 1 | 0 | ✓ | 18634 | 148 | 26.534 |
| real_wikipedia_search | 2 | 0 | 0 | 0 | ✓ | 12783 | 60 | 13.516 |


## Detection coverage — auto mode

| fixture | loaded | matches | suggestions | auto_invokes | assert_ok | tok_in | tok_out | wall (s) |
|---|---|---|---|---|---|---|---|---|
| real_fail_impossible_text | 2 | 0 | 0 | 0 | ✗ | 3204 | 264 | 10.089 |
| real_fail_search_no_result | 2 | 0 | 0 | 0 | ✗ | 7053 | 233 | 14.102 |
| real_fail_tight_steps | 2 | 1 | 0 | 1 | ✗ | 3421 | 334 | 11.922 |
| real_herokuapp_dynamic_loading | 2 | 0 | 0 | 0 | ✓ | 4696 | 23 | 14.308 |
| real_herokuapp_infinite_scroll | 2 | 1 | 0 | 1 | ✓ | 4777 | 182 | 12.323 |
| real_herokuapp_js_alerts | 2 | 0 | 0 | 0 | ✓ | 3265 | 24 | 7.054 |
| real_herokuapp_login | 2 | 1 | 0 | 1 | ✓ | 5804 | 85 | 11.874 |
| real_herokuapp_status_500 | 2 | 0 | 0 | 0 | ✓ | 3375 | 21 | 7.385 |
| real_saucedemo_addcart | 2 | 1 | 0 | 1 | ✓ | 12186 | 290 | 17.832 |
| real_saucedemo_locked_out | 2 | 2 | 0 | 1 | ✓ | 21019 | 317 | 24.633 |
| real_saucedemo_perf_glitch | 2 | 2 | 0 | 1 | ✓ | 29405 | 424 | 34.380 |
| real_wikipedia_search | 2 | 0 | 0 | 0 | ✓ | 12759 | 60 | 13.690 |


## Token deltas — warmup vs post-install (suggest, auto)

| fixture | warmup tok_in̄ | suggest tok_in̄ | suggest Δ% | auto tok_in̄ | auto Δ% |
|---|---|---|---|---|---|
| real_fail_impossible_text | 3231 | 3205 | -0.8% | 3204 | -0.8% |
| real_fail_search_no_result | 7053 | 7053 | +0.0% | 7053 | +0.0% |
| real_fail_tight_steps | 3075 | 3074 | -0.0% | 3421 | +11.3% |
| real_herokuapp_dynamic_loading | 4696 | 4696 | +0.0% | 4696 | +0.0% |
| real_herokuapp_infinite_scroll | 6342 | 6342 | +0.0% | 4777 | -24.7% |
| real_herokuapp_js_alerts | 3265 | 3265 | +0.0% | 3265 | +0.0% |
| real_herokuapp_login | 24375 | 18341 | -24.8% | 5804 | -76.2% |
| real_herokuapp_status_500 | 3375 | 3375 | +0.0% | 3375 | +0.0% |
| real_saucedemo_addcart | 14964 | 15027 | +0.4% | 12186 | -18.6% |
| real_saucedemo_locked_out | 9185 | 9122 | -0.7% | 21019 | +128.8% |
| real_saucedemo_perf_glitch | 16979 | 18634 | +9.7% | 29405 | +73.2% |
| real_wikipedia_search | 12739 | 12783 | +0.3% | 12759 | +0.2% |


### Auto-mode aggregate

- Auto-invocations fired: **6** across 12 runs
- Mean tok_in: warmup=9107 → auto=9247 (+1.5%)

## Raw appendix

- Per-run JSONL captures live under `/tmp/qa_bench_g4_caps`
- Emitted macros under `/tmp/qa_bench_g4_macros`
