# Macros pipeline real-world benchmark — 2026-05-07 05:08:53Z

- Fixtures: 12 (`real_fail_impossible_text, real_fail_search_no_result, real_fail_tight_steps, real_herokuapp_dynamic_loading, real_herokuapp_infinite_scroll, real_herokuapp_js_alerts, real_herokuapp_login, real_herokuapp_status_500, real_saucedemo_addcart, real_saucedemo_locked_out, real_saucedemo_perf_glitch, real_wikipedia_search`)
- Warmup runs: 24 (2 per fixture)
- Post-install runs: 12 suggest + 12 auto
- Mining yield: 3 candidates emitted
- Live-validate verdict: 2 kept / 1 dropped
- Wallclock: 648.5s
- Captures dir: `/tmp/qa_bench_g3_caps`
- Macros out: `/tmp/qa_bench_g3_macros`

## Per-fixture summary (warmup phase)

| fixture | runs | pass_rate | steps̄ | wall̄ (s) | tok_in̄ | tok_out̄ | conf̄ on PASS | conf̄ on FAIL |
|---|---|---|---|---|---|---|---|---|
| real_fail_impossible_text | 2 | 0.000 | 2 | 12.077 | 2957 | 404 | 0.000 | 0.338 |
| real_fail_search_no_result | 2 | 0.000 | 3 | 13.102 | 6567 | 239 | 0.000 | 0.350 |
| real_fail_tight_steps | 2 | 0.000 | 2 | 9.481 | 2649 | 169 | 0.000 | 0.300 |
| real_herokuapp_dynamic_loading | 2 | 1.000 | 3 | 14.583 | 4276 | 89 | 0.950 | 0.000 |
| real_herokuapp_infinite_scroll | 2 | 1.000 | 4 | 12.090 | 5694 | 167 | 0.925 | 0.000 |
| real_herokuapp_js_alerts | 2 | 1.000 | 2 | 8.253 | 2941 | 24 | 0.950 | 0.000 |
| real_herokuapp_login | 2 | 1.000 | 4 | 14.924 | 9350 | 48 | 0.900 | 0.000 |
| real_herokuapp_status_500 | 2 | 1.000 | 1 | 6.444 | 3051 | 21 | 1.000 | 0.000 |
| real_saucedemo_addcart | 2 | 1.000 | 5 | 14.300 | 10749 | 79 | 1.000 | 0.000 |
| real_saucedemo_locked_out | 2 | 1.000 | 4 | 13.061 | 8312 | 98 | 1.000 | 0.000 |
| real_saucedemo_perf_glitch | 2 | 1.000 | 5 | 19.818 | 10687 | 63 | 1.000 | 0.000 |
| real_wikipedia_search | 2 | 1.000 | 3 | 10.446 | 7389 | 47 | 0.925 | 0.000 |


## Confidence ↔ assert_ok correlation

- mean confidence on assert_ok=True : **0.961** (n=18)
- mean confidence on assert_ok=False: **0.329** (n=6)
- delta (PASS−FAIL): **+0.632** — positive ⇒ confidence does discriminate

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
| click_button_and_wait | 2 | 2 | 0 |


## Live-validate verdicts

| name | passed | score | failed step | elapsed (s) | failure |
|---|---|---|---|---|---|
| click_button_and_wait | ✗ | 0.000 | 1 | 6.749 | TIMEOUT: Locator.click: Timeout 5000ms exceeded.
Call log:
  - waiting for get_b |
| login_with_credentials | ✓ | 1.000 | - | 4.619 | - |
| scroll_and_count_loaded_items | ✓ | 1.000 | - | 3.811 | - |


## Detection coverage — suggest mode

| fixture | loaded | matches | suggestions | auto_invokes | assert_ok | tok_in | tok_out | wall (s) |
|---|---|---|---|---|---|---|---|---|
| real_fail_impossible_text | 2 | 0 | 0 | 0 | ✗ | 2994 | 423 | 15.076 |
| real_fail_search_no_result | 2 | 0 | 0 | 0 | ✗ | 6567 | 248 | 12.552 |
| real_fail_tight_steps | 2 | 1 | 1 | 0 | ✗ | 2653 | 139 | 8.841 |
| real_herokuapp_dynamic_loading | 2 | 0 | 0 | 0 | ✓ | 4267 | 80 | 15.486 |
| real_herokuapp_infinite_scroll | 2 | 2 | 1 | 0 | ✓ | 5694 | 167 | 13.189 |
| real_herokuapp_js_alerts | 2 | 0 | 0 | 0 | ✓ | 2941 | 24 | 7.022 |
| real_herokuapp_login | 2 | 2 | 1 | 0 | ✓ | 9350 | 48 | 13.763 |
| real_herokuapp_status_500 | 2 | 0 | 0 | 0 | ✓ | 3051 | 21 | 6.595 |
| real_saucedemo_addcart | 2 | 1 | 1 | 0 | ✓ | 10749 | 79 | 14.098 |
| real_saucedemo_locked_out | 2 | 1 | 1 | 0 | ✓ | 8312 | 98 | 13.997 |
| real_saucedemo_perf_glitch | 2 | 1 | 1 | 0 | ✓ | 17034 | 77 | 32.274 |
| real_wikipedia_search | 2 | 0 | 0 | 0 | ✓ | 12103 | 60 | 12.790 |


## Detection coverage — auto mode

| fixture | loaded | matches | suggestions | auto_invokes | assert_ok | tok_in | tok_out | wall (s) |
|---|---|---|---|---|---|---|---|---|
| real_fail_impossible_text | 2 | 0 | 0 | 0 | ✗ | 2921 | 326 | 9.262 |
| real_fail_search_no_result | 2 | 0 | 0 | 0 | ✗ | 6567 | 240 | 12.033 |
| real_fail_tight_steps | 2 | 1 | 0 | 1 | ✗ | 2987 | 184 | 10.085 |
| real_herokuapp_dynamic_loading | 2 | 0 | 0 | 0 | ✓ | 6586 | 102 | 16.385 |
| real_herokuapp_infinite_scroll | 2 | 1 | 0 | 1 | ✓ | 4224 | 136 | 10.307 |
| real_herokuapp_js_alerts | 2 | 0 | 0 | 0 | ✓ | 2941 | 24 | 6.433 |
| real_herokuapp_login | 2 | 1 | 0 | 1 | ✓ | 5247 | 29 | 9.977 |
| real_herokuapp_status_500 | 2 | 0 | 0 | 0 | ✓ | 3051 | 21 | 6.339 |
| real_saucedemo_addcart | 2 | 1 | 0 | 1 | ✓ | 11760 | 213 | 15.468 |
| real_saucedemo_locked_out | 2 | 2 | 0 | 1 | ✓ | 19648 | 287 | 23.446 |
| real_saucedemo_perf_glitch | 2 | 2 | 0 | 1 | ✓ | 27102 | 317 | 30.285 |
| real_wikipedia_search | 2 | 0 | 0 | 0 | ✓ | 7281 | 47 | 11.224 |


## Token deltas — warmup vs post-install (suggest, auto)

| fixture | warmup tok_in̄ | suggest tok_in̄ | suggest Δ% | auto tok_in̄ | auto Δ% |
|---|---|---|---|---|---|
| real_fail_impossible_text | 2957 | 2994 | +1.3% | 2921 | -1.2% |
| real_fail_search_no_result | 6567 | 6567 | +0.0% | 6567 | +0.0% |
| real_fail_tight_steps | 2649 | 2653 | +0.2% | 2987 | +12.8% |
| real_herokuapp_dynamic_loading | 4276 | 4267 | -0.2% | 6586 | +54.0% |
| real_herokuapp_infinite_scroll | 5694 | 5694 | +0.0% | 4224 | -25.8% |
| real_herokuapp_js_alerts | 2941 | 2941 | +0.0% | 2941 | +0.0% |
| real_herokuapp_login | 9350 | 9350 | +0.0% | 5247 | -43.9% |
| real_herokuapp_status_500 | 3051 | 3051 | +0.0% | 3051 | +0.0% |
| real_saucedemo_addcart | 10749 | 10749 | +0.0% | 11760 | +9.4% |
| real_saucedemo_locked_out | 8312 | 8312 | +0.0% | 19648 | +136.4% |
| real_saucedemo_perf_glitch | 10687 | 17034 | +59.4% | 27102 | +153.6% |
| real_wikipedia_search | 7389 | 12103 | +63.8% | 7281 | -1.5% |


### Auto-mode aggregate

- Auto-invocations fired: **6** across 12 runs
- Mean tok_in: warmup=6219 → auto=8360 (+34.4%)

## Raw appendix

- Per-run JSONL captures live under `/tmp/qa_bench_g3_caps`
- Emitted macros under `/tmp/qa_bench_g3_macros`
