# Macros pipeline real-world benchmark — 2026-05-07 06:11:57Z

- Fixtures: 12 (`real_fail_impossible_text, real_fail_search_no_result, real_fail_tight_steps, real_herokuapp_dynamic_loading, real_herokuapp_infinite_scroll, real_herokuapp_js_alerts, real_herokuapp_login, real_herokuapp_status_500, real_saucedemo_addcart, real_saucedemo_locked_out, real_saucedemo_perf_glitch, real_wikipedia_search`)
- Warmup runs: 24 (2 per fixture)
- Post-install runs: 12 suggest + 12 auto
- Mining yield: 3 candidates emitted
- Live-validate verdict: 2 kept / 1 dropped
- Wallclock: 749.0s
- Captures dir: `/tmp/qa_bench_a1b_caps`
- Macros out: `/tmp/qa_bench_a1b_macros`

## Per-fixture summary (warmup phase)

| fixture | runs | pass_rate | steps̄ | wall̄ (s) | tok_in̄ | tok_out̄ | conf̄ on PASS | conf̄ on FAIL |
|---|---|---|---|---|---|---|---|---|
| real_fail_impossible_text | 2 | 0.000 | 2 | 8.723 | 3204 | 288 | 0.000 | 0.350 |
| real_fail_search_no_result | 2 | 0.000 | 3 | 12.478 | 7053 | 261 | 0.000 | 0.350 |
| real_fail_tight_steps | 2 | 0.000 | 2 | 10.760 | 3083 | 296 | 0.000 | 0.400 |
| real_herokuapp_dynamic_loading | 2 | 1.000 | 3 | 15.206 | 4696 | 23 | 0.950 | 0.000 |
| real_herokuapp_infinite_scroll | 2 | 1.000 | 4 | 12.902 | 6340 | 175 | 0.913 | 0.000 |
| real_herokuapp_js_alerts | 2 | 1.000 | 2 | 7.148 | 3265 | 24 | 0.950 | 0.000 |
| real_herokuapp_login | 2 | 1.000 | 11 | 33.308 | 31311 | 152 | 0.913 | 0.000 |
| real_herokuapp_status_500 | 2 | 1.000 | 1 | 7.017 | 3375 | 21 | 1.000 | 0.000 |
| real_saucedemo_addcart | 2 | 1.000 | 6 | 19.204 | 15137 | 89 | 0.800 | 0.000 |
| real_saucedemo_locked_out | 2 | 1.000 | 4 | 12.369 | 9122 | 98 | 1.000 | 0.000 |
| real_saucedemo_perf_glitch | 2 | 1.000 | 6.500 | 24.271 | 18914 | 131 | 0.800 | 0.000 |
| real_wikipedia_search | 2 | 1.000 | 4 | 14.488 | 12870 | 139 | 0.925 | 0.000 |


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
| click_button_and_wait | ✗ | 0.000 | 1 | 6.571 | TIMEOUT: Locator.click: Timeout 5000ms exceeded.
Call log:
  - waiting for get_b |
| login_with_credentials | ✓ | 1.000 | - | 4.495 | - |
| scroll_and_count_loaded_items | ✓ | 1.000 | - | 3.811 | - |


## Detection coverage — suggest mode

| fixture | loaded | matches | suggestions | auto_invokes | assert_ok | tok_in | tok_out | wall (s) |
|---|---|---|---|---|---|---|---|---|
| real_fail_impossible_text | 2 | 0 | 0 | 0 | ✗ | 3259 | 343 | 9.607 |
| real_fail_search_no_result | 2 | 0 | 0 | 0 | ✗ | 7053 | 233 | 12.289 |
| real_fail_tight_steps | 2 | 1 | 1 | 0 | ✗ | 3083 | 279 | 10.802 |
| real_herokuapp_dynamic_loading | 2 | 0 | 0 | 0 | ✓ | 4696 | 23 | 14.284 |
| real_herokuapp_infinite_scroll | 2 | 2 | 1 | 0 | ✓ | 6342 | 176 | 12.910 |
| real_herokuapp_js_alerts | 2 | 0 | 0 | 0 | ✓ | 3265 | 24 | 7.512 |
| real_herokuapp_login | 2 | 2 | 2 | 0 | ✓ | 18680 | 220 | 23.600 |
| real_herokuapp_status_500 | 2 | 0 | 0 | 0 | ✓ | 3375 | 21 | 6.291 |
| real_saucedemo_addcart | 2 | 1 | 1 | 0 | ✓ | 14901 | 89 | 16.232 |
| real_saucedemo_locked_out | 2 | 1 | 1 | 0 | ✓ | 9122 | 98 | 15.071 |
| real_saucedemo_perf_glitch | 2 | 1 | 1 | 0 | ✓ | 18655 | 151 | 24.960 |
| real_wikipedia_search | 2 | 0 | 0 | 0 | ✓ | 12771 | 60 | 12.327 |


## Detection coverage — auto mode

| fixture | loaded | matches | suggestions | auto_invokes | assert_ok | tok_in | tok_out | wall (s) |
|---|---|---|---|---|---|---|---|---|
| real_fail_impossible_text | 2 | 0 | 0 | 0 | ✗ | 3204 | 288 | 8.913 |
| real_fail_search_no_result | 2 | 0 | 0 | 0 | ✗ | 7053 | 232 | 12.369 |
| real_fail_tight_steps | 2 | 1 | 0 | 1 | ✗ | 3338 | 245 | 11.612 |
| real_herokuapp_dynamic_loading | 2 | 0 | 0 | 0 | ✓ | 4696 | 23 | 13.376 |
| real_herokuapp_infinite_scroll | 2 | 1 | 0 | 1 | ✓ | 4790 | 183 | 12.686 |
| real_herokuapp_js_alerts | 2 | 0 | 0 | 0 | ✓ | 3265 | 24 | 8.111 |
| real_herokuapp_login | 2 | 1 | 0 | 1 | ✓ | 5769 | 48 | 14.938 |
| real_herokuapp_status_500 | 2 | 0 | 0 | 0 | ✓ | 3375 | 21 | 7.707 |
| real_saucedemo_addcart | 2 | 1 | 0 | 1 | ✓ | 12186 | 290 | 20.849 |
| real_saucedemo_locked_out | 2 | 1 | 0 | 1 | ✓ | 5728 | 153 | 10.939 |
| real_saucedemo_perf_glitch | 2 | 2 | 0 | 1 | ✓ | 28705 | 274 | 33.653 |
| real_wikipedia_search | 2 | 0 | 0 | 0 | ✓ | 12759 | 60 | 12.283 |


## Token deltas — warmup vs post-install (suggest, auto)

| fixture | warmup tok_in̄ | suggest tok_in̄ | suggest Δ% | auto tok_in̄ | auto Δ% |
|---|---|---|---|---|---|
| real_fail_impossible_text | 3204 | 3259 | +1.7% | 3204 | +0.0% |
| real_fail_search_no_result | 7053 | 7053 | +0.0% | 7053 | +0.0% |
| real_fail_tight_steps | 3083 | 3083 | +0.0% | 3338 | +8.3% |
| real_herokuapp_dynamic_loading | 4696 | 4696 | +0.0% | 4696 | +0.0% |
| real_herokuapp_infinite_scroll | 6340 | 6342 | +0.0% | 4790 | -24.4% |
| real_herokuapp_js_alerts | 3265 | 3265 | +0.0% | 3265 | +0.0% |
| real_herokuapp_login | 31311 | 18680 | -40.3% | 5769 | -81.6% |
| real_herokuapp_status_500 | 3375 | 3375 | +0.0% | 3375 | +0.0% |
| real_saucedemo_addcart | 15137 | 14901 | -1.6% | 12186 | -19.5% |
| real_saucedemo_locked_out | 9122 | 9122 | +0.0% | 5728 | -37.2% |
| real_saucedemo_perf_glitch | 18914 | 18655 | -1.4% | 28705 | +51.8% |
| real_wikipedia_search | 12870 | 12771 | -0.8% | 12759 | -0.9% |


### Auto-mode aggregate

- Auto-invocations fired: **6** across 12 runs
- Mean tok_in: warmup=9864 → auto=7906 (-19.9%)

## Raw appendix

- Per-run JSONL captures live under `/tmp/qa_bench_a1b_caps`
- Emitted macros under `/tmp/qa_bench_a1b_macros`
