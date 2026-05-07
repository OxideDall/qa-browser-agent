# Macros pipeline real-world benchmark — 2026-05-07 04:56:24Z

- Fixtures: 12 (`real_fail_impossible_text, real_fail_search_no_result, real_fail_tight_steps, real_herokuapp_dynamic_loading, real_herokuapp_infinite_scroll, real_herokuapp_js_alerts, real_herokuapp_login, real_herokuapp_status_500, real_saucedemo_addcart, real_saucedemo_locked_out, real_saucedemo_perf_glitch, real_wikipedia_search`)
- Warmup runs: 24 (2 per fixture)
- Post-install runs: 12 suggest + 12 auto
- Mining yield: 2 candidates emitted
- Live-validate verdict: 2 kept / 0 dropped
- Wallclock: 645.6s
- Captures dir: `/tmp/qa_bench_g2_caps`
- Macros out: `/tmp/qa_bench_g2_macros`

## Per-fixture summary (warmup phase)

| fixture | runs | pass_rate | steps̄ | wall̄ (s) | tok_in̄ | tok_out̄ | conf̄ on PASS | conf̄ on FAIL |
|---|---|---|---|---|---|---|---|---|
| real_fail_impossible_text | 2 | 0.000 | 2 | 10.502 | 3010 | 474 | 0.000 | 0.350 |
| real_fail_search_no_result | 2 | 0.000 | 3 | 12.792 | 6567 | 246 | 0.000 | 0.350 |
| real_fail_tight_steps | 2 | 0.000 | 2 | 9.514 | 2647 | 140 | 0.000 | 0.300 |
| real_herokuapp_dynamic_loading | 2 | 1.000 | 3.500 | 15.953 | 5149 | 95 | 0.950 | 0.000 |
| real_herokuapp_infinite_scroll | 2 | 1.000 | 4 | 12.654 | 5694 | 167 | 0.925 | 0.000 |
| real_herokuapp_js_alerts | 2 | 1.000 | 2 | 6.744 | 2941 | 24 | 0.938 | 0.000 |
| real_herokuapp_login | 2 | 1.000 | 4 | 14.526 | 9350 | 48 | 0.887 | 0.000 |
| real_herokuapp_status_500 | 2 | 1.000 | 1 | 6.552 | 3051 | 21 | 1.000 | 0.000 |
| real_saucedemo_addcart | 2 | 1.000 | 5 | 15.729 | 10812 | 79 | 1.000 | 0.000 |
| real_saucedemo_locked_out | 2 | 1.000 | 4 | 14.232 | 8312 | 98 | 1.000 | 0.000 |
| real_saucedemo_perf_glitch | 2 | 1.000 | 5 | 20.473 | 10687 | 59 | 1.000 | 0.000 |
| real_wikipedia_search | 2 | 1.000 | 3.500 | 12.633 | 9708 | 53 | 0.925 | 0.000 |


## Confidence ↔ assert_ok correlation

- mean confidence on assert_ok=True : **0.958** (n=18)
- mean confidence on assert_ok=False: **0.333** (n=6)
- delta (PASS−FAIL): **+0.625** — positive ⇒ confidence does discriminate

## Aggregate uncertainty signals (warmup)

| signal | total occurrences |
|---|---|
| done_reasks | 0 |
| hallucinated_ids | 0 |
| soft_loops | 0 |
| vision_repeats | 0 |
| parse_errors | 0 |
| flicker | 24 |

## Mining yield (LLM curator on)

| name | support | length | params |
|---|---|---|---|
| login_with_credentials | 8 | 3 | 2 |
| scroll_and_count_loaded_items | 2 | 3 | 0 |


## Live-validate verdicts

| name | passed | score | failed step | elapsed (s) | failure |
|---|---|---|---|---|---|
| login_with_credentials | ✓ | 1.000 | - | 4.464 | - |
| scroll_and_count_loaded_items | ✓ | 1.000 | - | 3.752 | - |


## Detection coverage — suggest mode

| fixture | loaded | matches | suggestions | auto_invokes | assert_ok | tok_in | tok_out | wall (s) |
|---|---|---|---|---|---|---|---|---|
| real_fail_impossible_text | 2 | 0 | 0 | 0 | ✗ | 2880 | 269 | 9.016 |
| real_fail_search_no_result | 2 | 0 | 0 | 0 | ✗ | 6575 | 247 | 13.028 |
| real_fail_tight_steps | 2 | 1 | 1 | 0 | ✗ | 2640 | 136 | 9.311 |
| real_herokuapp_dynamic_loading | 2 | 0 | 0 | 0 | ✓ | 4281 | 94 | 14.089 |
| real_herokuapp_infinite_scroll | 2 | 2 | 1 | 0 | ✓ | 5694 | 167 | 12.318 |
| real_herokuapp_js_alerts | 2 | 0 | 0 | 0 | ✓ | 2941 | 24 | 7.767 |
| real_herokuapp_login | 2 | 2 | 1 | 0 | ✓ | 9350 | 48 | 13.887 |
| real_herokuapp_status_500 | 2 | 0 | 0 | 0 | ✓ | 3051 | 21 | 7.324 |
| real_saucedemo_addcart | 2 | 1 | 1 | 0 | ✓ | 10749 | 79 | 14.755 |
| real_saucedemo_locked_out | 2 | 1 | 1 | 0 | ✓ | 8312 | 98 | 12.516 |
| real_saucedemo_perf_glitch | 2 | 1 | 1 | 0 | ✓ | 17087 | 125 | 25.564 |
| real_wikipedia_search | 2 | 0 | 0 | 0 | ✓ | 12090 | 60 | 15.279 |


## Detection coverage — auto mode

| fixture | loaded | matches | suggestions | auto_invokes | assert_ok | tok_in | tok_out | wall (s) |
|---|---|---|---|---|---|---|---|---|
| real_fail_impossible_text | 2 | 0 | 0 | 0 | ✗ | 2921 | 326 | 9.904 |
| real_fail_search_no_result | 2 | 0 | 0 | 0 | ✗ | 6567 | 240 | 13.429 |
| real_fail_tight_steps | 2 | 1 | 0 | 1 | ✗ | 2982 | 214 | 10.328 |
| real_herokuapp_dynamic_loading | 2 | 0 | 0 | 0 | ✓ | 4285 | 98 | 15.482 |
| real_herokuapp_infinite_scroll | 2 | 1 | 0 | 1 | ✓ | 4224 | 136 | 11.226 |
| real_herokuapp_js_alerts | 2 | 0 | 0 | 0 | ✓ | 2941 | 24 | 6.929 |
| real_herokuapp_login | 2 | 1 | 0 | 1 | ✓ | 5247 | 29 | 10.269 |
| real_herokuapp_status_500 | 2 | 0 | 0 | 0 | ✓ | 3051 | 21 | 6.709 |
| real_saucedemo_addcart | 2 | 1 | 0 | 1 | ✓ | 11771 | 221 | 15.263 |
| real_saucedemo_locked_out | 2 | 2 | 0 | 1 | ✓ | 19681 | 293 | 23.133 |
| real_saucedemo_perf_glitch | 2 | 2 | 0 | 1 | ✓ | 27163 | 308 | 34.323 |
| real_wikipedia_search | 2 | 0 | 0 | 0 | ✓ | 12088 | 61 | 13.202 |


## Token deltas — warmup vs post-install (suggest, auto)

| fixture | warmup tok_in̄ | suggest tok_in̄ | suggest Δ% | auto tok_in̄ | auto Δ% |
|---|---|---|---|---|---|
| real_fail_impossible_text | 3010 | 2880 | -4.3% | 2921 | -3.0% |
| real_fail_search_no_result | 6567 | 6575 | +0.1% | 6567 | +0.0% |
| real_fail_tight_steps | 2647 | 2640 | -0.3% | 2982 | +12.7% |
| real_herokuapp_dynamic_loading | 5149 | 4281 | -16.9% | 4285 | -16.8% |
| real_herokuapp_infinite_scroll | 5694 | 5694 | +0.0% | 4224 | -25.8% |
| real_herokuapp_js_alerts | 2941 | 2941 | +0.0% | 2941 | +0.0% |
| real_herokuapp_login | 9350 | 9350 | +0.0% | 5247 | -43.9% |
| real_herokuapp_status_500 | 3051 | 3051 | +0.0% | 3051 | +0.0% |
| real_saucedemo_addcart | 10812 | 10749 | -0.6% | 11771 | +8.9% |
| real_saucedemo_locked_out | 8312 | 8312 | +0.0% | 19681 | +136.8% |
| real_saucedemo_perf_glitch | 10687 | 17087 | +59.9% | 27163 | +154.2% |
| real_wikipedia_search | 9708 | 12090 | +24.5% | 12088 | +24.5% |


### Auto-mode aggregate

- Auto-invocations fired: **6** across 12 runs
- Mean tok_in: warmup=6494 → auto=8577 (+32.1%)

## Raw appendix

- Per-run JSONL captures live under `/tmp/qa_bench_g2_caps`
- Emitted macros under `/tmp/qa_bench_g2_macros`
