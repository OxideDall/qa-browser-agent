# bench/

Benchmark suite for the QA agent. 45 browser fixtures across 9 categories
(plus on-device Android fixtures under [`bench/android/`](android/README.md)).
See [`taxonomy.md`](taxonomy.md) for the original category design.

## Quick start

```bash
# Static-only fixtures (no internet required)
python -m bench.runner --category static_ui

# Single fixture
python -m bench.runner static_l1_confirm

# Aggregate latest results
python -m bench.analyze

# A/B two prompts on the static suite
python -m bench.ab promptA.txt promptB.txt --category static_ui
```

Or via Makefile from `bench/`:

```bash
make bench-static
make analyze
make ab A=../qa_agent/agent_v1.txt B=../qa_agent/agent_v2.txt
```

## Architecture

```
bench/
  taxonomy.md           # spec — 8 categories, 6-8 levels, 52 fixtures
  fixtures/<cat>/<id>/  # one dir per fixture, see taxonomy.md for layout
  runner/
    runner.py           # CLI: load → run → assert → record
    loader.py           # config.toml + assert.json/py loader
    server.py           # local HTTP server for static fixtures
    asserts.py          # declarative DOM/URL/localStorage checks
    recorder.py         # JSONL writer (per-step + final + assert)
    judge.py            # Sonnet LLM judge for L6 open-ended fixtures
    web3_assert.py      # web3.py helpers for on-chain checks
  results/runs/         # JSONL run logs (gitignored)
  analyze.py            # aggregator — flat table + per-category averages
  ab.py                 # A/B prompt harness with regression diff
  Makefile              # convenience targets
```

## Run log schema

Each run produces `results/runs/<fixture_id>__<iso_ts>.jsonl`:

- `{"t": "start", ...}` — fixture metadata
- `{"t": "step", "step": N, "action": ..., "args": ..., "result": ...,
   "in_tokens": ..., "out_tokens": ..., "page_url": ..., "loop_hit": ...,
   "blocked": ..., "done_reasked": ..., "evidence_present": ...,
   "vision": ..., "latency_ms": ..., "screenshot": "<post-path>",
   "screenshot_pre": "<pre-path>", "console": [...], "network": [...],
   "flicker": [...], "vision_hallucinated": {...}?}` —
   one per loop iteration. `screenshot` (post-action) and
   `screenshot_pre` (pre-action, only on `act_exec` steps) are paths to
   per-step JPEG (browser, full_page) / PNG (android). `console`,
   `network`, `flicker` are slices of the per-run diagnostic streams
   that arose during this step only. `vision_hallucinated` appears
   only when the vision cross-check rejected a fabricated id.
- `{"t": "result", "status": ..., "description": ..., "steps_used": ...,
   "wall_seconds": ..., "total_in": ..., "total_out": ...,
   "screenshots": [paths], "screenshots_dir": "...",
   "console_errors": N, "network_errors": N, "flicker_events": N,
   "done_reasks_log": [{step, description, reason, verdict}, ...],
   "console_log_path": "...", "network_log_path": "...",
   "flicker_log_path": "...", "done_reasks_log_path": "..."}`
- `{"t": "assert", "ok": bool, "msg": ..., "details": {...}}`

## Adding a new fixture

1. `mkdir -p bench/fixtures/<category>/<fixture_id>/site` (omit `site/` if
   the fixture targets a live URL).
2. `bench/fixtures/<category>/<fixture_id>/task.txt` — plain instructions
   the agent will receive verbatim.
3. `bench/fixtures/<category>/<fixture_id>/config.toml` — see existing fixtures
   or `taxonomy.md` for the full schema.
4. Either `assert.json` (declarative DOM/URL/storage checks) or `assert.py`
   (programmatic — `def check(run_log) -> tuple[bool, str]`).
5. Update `taxonomy.md`'s matrix table to reflect the new entry.

## Web3 fixtures

Web3 fixtures need a funded testnet wallet. Address derived from
`BENCH_SEED` in `.env`:

```bash
make balances    # show balances across all 5 testnets
```

Funding targets (rough):

| Network          | Min for full L1–L8 |
|------------------|--------------------|
| Sepolia          | 50 ETH             |
| Base Sepolia     | 25 ETH             |
| Arbitrum Sepolia | 12 ETH             |
| Optimism Sepolia | 12 ETH             |
| Polygon Amoy     | 1000 MATIC         |
