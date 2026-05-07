# Macros pipeline real-world benchmark — 2026-05-07 03:49:26Z

- Fixtures: 12 (`real_fail_impossible_text, real_fail_search_no_result, real_fail_tight_steps, real_herokuapp_dynamic_loading, real_herokuapp_infinite_scroll, real_herokuapp_js_alerts, real_herokuapp_login, real_herokuapp_status_500, real_saucedemo_addcart, real_saucedemo_locked_out, real_saucedemo_perf_glitch, real_wikipedia_search`)
- Warmup runs: 24 (2 per fixture)
- Post-install runs: 12 suggest + 12 auto
- Mining yield: 2 candidates emitted
- Live-validate verdict: 2 kept / 0 dropped
- Wallclock: 682.7s
- Captures dir: `/tmp/qa_bench_r1_caps`
- Macros out: `/tmp/qa_bench_r1_macros`

## Per-fixture summary (warmup phase)

| fixture | runs | pass_rate | steps̄ | wall̄ (s) | tok_in̄ | tok_out̄ | conf̄ on PASS | conf̄ on FAIL |
|---|---|---|---|---|---|---|---|---|
| real_fail_impossible_text | 2 | 0.000 | 2 | 10.506 | 2880 | 287 | 0.000 | 0.350 |
| real_fail_search_no_result | 2 | 0.000 | 3 | 13.063 | 6567 | 246 | 0.000 | 0.350 |
| real_fail_tight_steps | 2 | 0.000 | 2 | 9.256 | 2640 | 145 | 0.000 | 0.400 |
| real_herokuapp_dynamic_loading | 2 | 1.000 | 3 | 14.742 | 4276 | 89 | 0.950 | 0.000 |
| real_herokuapp_infinite_scroll | 2 | 1.000 | 4 | 16.087 | 5694 | 167 | 0.925 | 0.000 |
| real_herokuapp_js_alerts | 2 | 1.000 | 2 | 7.481 | 2941 | 24 | 0.950 | 0.000 |
| real_herokuapp_login | 2 | 1.000 | 4 | 15.739 | 9350 | 48 | 0.900 | 0.000 |
| real_herokuapp_status_500 | 2 | 1.000 | 1 | 6.564 | 3051 | 21 | 1.000 | 0.000 |
| real_saucedemo_addcart | 2 | 1.000 | 5 | 15.849 | 10875 | 79 | 1.000 | 0.000 |
| real_saucedemo_locked_out | 2 | 1.000 | 4 | 14.474 | 8375 | 98 | 1.000 | 0.000 |
| real_saucedemo_perf_glitch | 2 | 1.000 | 5 | 21.922 | 10687 | 59 | 1.000 | 0.000 |
| real_wikipedia_search | 2 | 1.000 | 4 | 20.533 | 12090 | 60 | 0.938 | 0.000 |


## Confidence ↔ assert_ok correlation

- mean confidence on assert_ok=True : **0.963** (n=18)
- mean confidence on assert_ok=False: **0.367** (n=6)
- delta (PASS−FAIL): **+0.596** — positive ⇒ confidence does discriminate

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
| login_with_credentials | ✓ | 1.000 | - | 4.505 | - |
| scroll_and_count_loaded_items | ✓ | 1.000 | - | 3.815 | - |


## Detection coverage — suggest mode

| fixture | loaded | matches | suggestions | auto_invokes | assert_ok | tok_in | tok_out | wall (s) |
|---|---|---|---|---|---|---|---|---|
| real_fail_impossible_text | 2 | 0 | 0 | 0 | ✗ | 3004 | 455 | 10.000 |
| real_fail_search_no_result | 2 | 0 | 0 | 0 | ✗ | 6567 | 240 | 18.033 |
| real_fail_tight_steps | 2 | 0 | 0 | 0 | ✗ | 2645 | 191 | 13.825 |
| real_herokuapp_dynamic_loading | 2 | 0 | 0 | 0 | ✓ | 4278 | 91 | 14.906 |
| real_herokuapp_infinite_scroll | 2 | 1 | 1 | 0 | ✓ | 5753 | 178 | 14.061 |
| real_herokuapp_js_alerts | 2 | 0 | 0 | 0 | ✓ | 2941 | 24 | 6.909 |
| real_herokuapp_login | 2 | 0 | 0 | 0 | ✓ | 9350 | 48 | 14.163 |
| real_herokuapp_status_500 | 2 | 0 | 0 | 0 | ✓ | 3051 | 21 | 7.538 |
| real_saucedemo_addcart | 2 | 0 | 0 | 0 | ✓ | 10875 | 79 | 21.708 |
| real_saucedemo_locked_out | 2 | 0 | 0 | 0 | ✓ | 8312 | 98 | 14.784 |
| real_saucedemo_perf_glitch | 2 | 0 | 0 | 0 | ✓ | 10763 | 63 | 22.423 |
| real_wikipedia_search | 2 | 0 | 0 | 0 | ✓ | 12114 | 60 | 16.260 |


## Detection coverage — auto mode

| fixture | loaded | matches | suggestions | auto_invokes | assert_ok | tok_in | tok_out | wall (s) |
|---|---|---|---|---|---|---|---|---|
| real_fail_impossible_text | 2 | 0 | 0 | 0 | ✗ | 2880 | 287 | 9.836 |
| real_fail_search_no_result | 2 | 0 | 0 | 0 | ✗ | 6567 | 259 | 13.213 |
| real_fail_tight_steps | 2 | 0 | 0 | 0 | ✗ | 2650 | 154 | 8.922 |
| real_herokuapp_dynamic_loading | 2 | 0 | 0 | 0 | ✓ | 4267 | 80 | 14.555 |
| real_herokuapp_infinite_scroll | 2 | 1 | 0 | 1 | ✓ | 7382 | 185 | 16.319 |
| real_herokuapp_js_alerts | 2 | 0 | 0 | 0 | ✓ | 2941 | 24 | 10.347 |
| real_herokuapp_login | 2 | 0 | 0 | 0 | ✓ | 9350 | 48 | 14.154 |
| real_herokuapp_status_500 | 2 | 0 | 0 | 0 | ✓ | 3051 | 21 | 6.609 |
| real_saucedemo_addcart | 2 | 0 | 0 | 0 | ✓ | 10917 | 79 | 17.310 |
| real_saucedemo_locked_out | 2 | 0 | 0 | 0 | ✓ | 8312 | 98 | 14.397 |
| real_saucedemo_perf_glitch | 2 | 0 | 0 | 0 | ✓ | 10687 | 63 | 21.496 |
| real_wikipedia_search | 2 | 0 | 0 | 0 | ✓ | 12087 | 60 | 12.430 |


## Token deltas — warmup vs post-install (suggest, auto)

| fixture | warmup tok_in̄ | suggest tok_in̄ | suggest Δ% | auto tok_in̄ | auto Δ% |
|---|---|---|---|---|---|
| real_fail_impossible_text | 2880 | 3004 | +4.3% | 2880 | +0.0% |
| real_fail_search_no_result | 6567 | 6567 | +0.0% | 6567 | +0.0% |
| real_fail_tight_steps | 2640 | 2645 | +0.2% | 2650 | +0.4% |
| real_herokuapp_dynamic_loading | 4276 | 4278 | +0.0% | 4267 | -0.2% |
| real_herokuapp_infinite_scroll | 5694 | 5753 | +1.0% | 7382 | +29.6% |
| real_herokuapp_js_alerts | 2941 | 2941 | +0.0% | 2941 | +0.0% |
| real_herokuapp_login | 9350 | 9350 | +0.0% | 9350 | +0.0% |
| real_herokuapp_status_500 | 3051 | 3051 | +0.0% | 3051 | +0.0% |
| real_saucedemo_addcart | 10875 | 10875 | +0.0% | 10917 | +0.4% |
| real_saucedemo_locked_out | 8375 | 8312 | -0.8% | 8312 | -0.8% |
| real_saucedemo_perf_glitch | 10687 | 10763 | +0.7% | 10687 | +0.0% |
| real_wikipedia_search | 12090 | 12114 | +0.2% | 12087 | -0.0% |


### Auto-mode aggregate

- Auto-invocations fired: **1** across 12 runs
- Mean tok_in: warmup=6619 → auto=6758 (+2.1%)

## Raw appendix

- Per-run JSONL captures live under `/tmp/qa_bench_r1_caps`
- Emitted macros under `/tmp/qa_bench_r1_macros`
