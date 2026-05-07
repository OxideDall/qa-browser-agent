# Macros pipeline real-world benchmark — 2026-05-07 04:42:34Z

- Fixtures: 12 (`real_fail_impossible_text, real_fail_search_no_result, real_fail_tight_steps, real_herokuapp_dynamic_loading, real_herokuapp_infinite_scroll, real_herokuapp_js_alerts, real_herokuapp_login, real_herokuapp_status_500, real_saucedemo_addcart, real_saucedemo_locked_out, real_saucedemo_perf_glitch, real_wikipedia_search`)
- Warmup runs: 24 (2 per fixture)
- Post-install runs: 12 suggest + 12 auto
- Mining yield: 2 candidates emitted
- Live-validate verdict: 2 kept / 0 dropped
- Wallclock: 706.2s
- Captures dir: `/tmp/qa_bench_g1b_caps`
- Macros out: `/tmp/qa_bench_g1b_macros`

## Per-fixture summary (warmup phase)

| fixture | runs | pass_rate | steps̄ | wall̄ (s) | tok_in̄ | tok_out̄ | conf̄ on PASS | conf̄ on FAIL |
|---|---|---|---|---|---|---|---|---|
| real_fail_impossible_text | 2 | 0.000 | 2 | 9.924 | 2937 | 349 | 0.000 | 0.350 |
| real_fail_search_no_result | 2 | 0.000 | 3 | 13.229 | 6567 | 252 | 0.000 | 0.350 |
| real_fail_tight_steps | 2 | 0.000 | 2 | 10.257 | 2647 | 138 | 0.000 | 0.300 |
| real_herokuapp_dynamic_loading | 2 | 1.000 | 3 | 16.518 | 4276 | 89 | 0.975 | 0.000 |
| real_herokuapp_infinite_scroll | 2 | 1.000 | 4 | 13.144 | 5694 | 167 | 0.925 | 0.000 |
| real_herokuapp_js_alerts | 2 | 1.000 | 2 | 7.408 | 2941 | 24 | 0.950 | 0.000 |
| real_herokuapp_login | 2 | 1.000 | 4 | 13.704 | 9350 | 48 | 0.900 | 0.000 |
| real_herokuapp_status_500 | 2 | 1.000 | 1 | 6.592 | 3051 | 21 | 1.000 | 0.000 |
| real_saucedemo_addcart | 2 | 1.000 | 5 | 14.918 | 10749 | 79 | 1.000 | 0.000 |
| real_saucedemo_locked_out | 2 | 1.000 | 4 | 13.108 | 8312 | 98 | 1.000 | 0.000 |
| real_saucedemo_perf_glitch | 2 | 1.000 | 5 | 20.671 | 10687 | 61 | 1.000 | 0.000 |
| real_wikipedia_search | 2 | 1.000 | 4 | 13.228 | 12110 | 60 | 0.925 | 0.000 |


## Confidence ↔ assert_ok correlation

- mean confidence on assert_ok=True : **0.964** (n=18)
- mean confidence on assert_ok=False: **0.333** (n=6)
- delta (PASS−FAIL): **+0.631** — positive ⇒ confidence does discriminate

## Aggregate uncertainty signals (warmup)

| signal | total occurrences |
|---|---|
| done_reasks | 0 |
| hallucinated_ids | 0 |
| soft_loops | 0 |
| vision_repeats | 0 |
| parse_errors | 0 |
| flicker | 21 |

## Mining yield (LLM curator on)

| name | support | length | params |
|---|---|---|---|
| login_with_credentials | 8 | 3 | 2 |
| scroll_and_count_loaded_items | 2 | 3 | 0 |


## Live-validate verdicts

| name | passed | score | failed step | elapsed (s) | failure |
|---|---|---|---|---|---|
| login_with_credentials | ✓ | 1.000 | - | 4.641 | - |
| scroll_and_count_loaded_items | ✓ | 1.000 | - | 3.792 | - |


## Detection coverage — suggest mode

| fixture | loaded | matches | suggestions | auto_invokes | assert_ok | tok_in | tok_out | wall (s) |
|---|---|---|---|---|---|---|---|---|
| real_fail_impossible_text | 2 | 0 | 0 | 0 | ✗ | 2880 | 287 | 10.308 |
| real_fail_search_no_result | 2 | 0 | 0 | 0 | ✗ | 6567 | 248 | 13.152 |
| real_fail_tight_steps | 2 | 1 | 1 | 0 | ✗ | 2640 | 148 | 8.602 |
| real_herokuapp_dynamic_loading | 2 | 0 | 0 | 0 | ✓ | 4267 | 80 | 15.039 |
| real_herokuapp_infinite_scroll | 2 | 2 | 1 | 0 | ✓ | 5694 | 167 | 12.962 |
| real_herokuapp_js_alerts | 2 | 0 | 0 | 0 | ✓ | 2941 | 24 | 7.127 |
| real_herokuapp_login | 2 | 2 | 1 | 0 | ✓ | 9350 | 48 | 14.216 |
| real_herokuapp_status_500 | 2 | 0 | 0 | 0 | ✓ | 3051 | 21 | 7.066 |
| real_saucedemo_addcart | 2 | 1 | 1 | 0 | ✓ | 10749 | 79 | 15.168 |
| real_saucedemo_locked_out | 2 | 1 | 1 | 0 | ✓ | 8312 | 98 | 14.087 |
| real_saucedemo_perf_glitch | 2 | 1 | 1 | 0 | ✓ | 13677 | 70 | 21.668 |
| real_wikipedia_search | 2 | 0 | 0 | 0 | ✓ | 12114 | 60 | 13.015 |


## Detection coverage — auto mode

| fixture | loaded | matches | suggestions | auto_invokes | assert_ok | tok_in | tok_out | wall (s) |
|---|---|---|---|---|---|---|---|---|
| real_fail_impossible_text | 2 | 0 | 0 | 0 | ✗ | 2921 | 326 | 9.465 |
| real_fail_search_no_result | 2 | 0 | 0 | 0 | ✗ | 6567 | 240 | 12.569 |
| real_fail_tight_steps | 2 | 1 | 0 | 1 | ✗ | 2987 | 157 | 9.642 |
| real_herokuapp_dynamic_loading | 2 | 0 | 0 | 0 | ✓ | 4263 | 76 | 14.561 |
| real_herokuapp_infinite_scroll | 2 | 1 | 0 | 1 | ✓ | 4224 | 136 | 10.642 |
| real_herokuapp_js_alerts | 2 | 0 | 0 | 0 | ✓ | 2941 | 24 | 6.948 |
| real_herokuapp_login | 2 | 1 | 0 | 1 | ✓ | 5247 | 29 | 10.417 |
| real_herokuapp_status_500 | 2 | 0 | 0 | 0 | ✓ | 3051 | 21 | 6.855 |
| real_saucedemo_addcart | 2 | 1 | 0 | 1 | ✗ | 11288 | 287 | 15.859 |
| real_saucedemo_locked_out | 2 | 3 | 0 | 3 | ✗ | 27193 | 448 | 28.841 |
| real_saucedemo_perf_glitch | 2 | 3 | 0 | 3 | ✓ | 43919 | 443 | 40.519 |
| real_wikipedia_search | 2 | 0 | 0 | 0 | ✓ | 12114 | 60 | 13.480 |


## Token deltas — warmup vs post-install (suggest, auto)

| fixture | warmup tok_in̄ | suggest tok_in̄ | suggest Δ% | auto tok_in̄ | auto Δ% |
|---|---|---|---|---|---|
| real_fail_impossible_text | 2937 | 2880 | -1.9% | 2921 | -0.5% |
| real_fail_search_no_result | 6567 | 6567 | +0.0% | 6567 | +0.0% |
| real_fail_tight_steps | 2647 | 2640 | -0.3% | 2987 | +12.8% |
| real_herokuapp_dynamic_loading | 4276 | 4267 | -0.2% | 4263 | -0.3% |
| real_herokuapp_infinite_scroll | 5694 | 5694 | +0.0% | 4224 | -25.8% |
| real_herokuapp_js_alerts | 2941 | 2941 | +0.0% | 2941 | +0.0% |
| real_herokuapp_login | 9350 | 9350 | +0.0% | 5247 | -43.9% |
| real_herokuapp_status_500 | 3051 | 3051 | +0.0% | 3051 | +0.0% |
| real_saucedemo_addcart | 10749 | 10749 | +0.0% | 11288 | +5.0% |
| real_saucedemo_locked_out | 8312 | 8312 | +0.0% | 27193 | +227.2% |
| real_saucedemo_perf_glitch | 10687 | 13677 | +28.0% | 43919 | +311.0% |
| real_wikipedia_search | 12110 | 12114 | +0.0% | 12114 | +0.0% |


### Auto-mode aggregate

- Auto-invocations fired: **10** across 12 runs
- Mean tok_in: warmup=6610 → auto=10560 (+59.7%)

## Raw appendix

- Per-run JSONL captures live under `/tmp/qa_bench_g1b_caps`
- Emitted macros under `/tmp/qa_bench_g1b_macros`
