# QA Agent — browser + Android, LLM-driven

A test agent that drives a real browser (Playwright) or a real Android phone
(uiautomator2) through a finite-state machine, using any vision-capable LLM as
the step-level planner.

```
CLI / MCP / bench
      │
      ▼
┌──────────┐  table-driven FSM  ┌────────────────────────┐
│   agent  │ ─────────────────► │ runtime/ (states,      │
│  loop    │                    │  transitions, fsm)     │
└─────┬────┘                    └────────────┬───────────┘
      │                                      │
      ▼ snapshot + action                    ▼ one event per action
┌──────────┐                         ┌───────────────┐
│ driver   │   browser: Playwright   │ LLM provider  │
│  (click, │   android: uiautomator2 │ (anthropic /  │
│   type,  │─────────────────────────│  openrouter)  │
│   etc.)  │                         │               │
└──────────┘                         └───────────────┘
```

## Why

Classical browser automation (Selenium, Cypress, Playwright tests) breaks the
moment the UI moves — every refactor invalidates a wall of CSS selectors, and
someone has to go patch them. Vision-only LLM agents (computer-use, Operator,
Manus) solve the brittleness but cost ~$0.03/step and take 4–5 s/step because
every turn ships a 1 MPix screenshot to a big model.

This agent takes a middle path: the page's DOM is compressed into a
~300-token DSL snapshot on every step, and a small LLM (Haiku class) picks
**one action** — `click 5`, `type 3 "…"`, `done PASS "…"`. A table-driven
FSM enforces the loop: one snapshot → one LLM call → one action → repeat, with
loop-detection and an evidence gate on `done PASS`. Screenshots are only used
as a `look` fallback when the DSL is ambiguous.

Cost per step is dominated by a single Haiku call on ~300 input tokens,
which is about an order of magnitude cheaper than screenshot-first agents
and free of selector maintenance. The same pipeline drives three surfaces —
a browser, a browser extension (MetaMask, including real on-chain Sepolia
transactions), and a physical Android phone — because only the driver layer
changes; the LLM, the DSL, the FSM, the evidence gate, and the bench
harness are shared.

## Quick start

```bash
pip install playwright uiautomator2 Pillow
playwright install chromium

export ANTHROPIC_API_KEY=sk-...          # default provider
python -m qa_agent "verify signup at http://localhost:3000"
```

Alternative provider — OpenRouter (any model):

```bash
export LLM_PROVIDER=openrouter
export OPENROUTER_API_KEY=...
export LLM_MODEL="anthropic/claude-3.5-haiku"    # or openai/gpt-4o-mini, etc.
```

Model requirements: any text model works for the DSL step loop; the `look`
action uses vision, so keep a vision-capable model if you want the
screenshot fallback. Defaults (`claude-haiku-4-5`, `claude-3.5-haiku`) already
support both.

## Providers

| env `LLM_PROVIDER` | auth env           | notes                                         |
|--------------------|--------------------|-----------------------------------------------|
| `anthropic` (def.) | `ANTHROPIC_API_KEY` | Standard Anthropic Messages API.              |
| `openrouter`       | `OPENROUTER_API_KEY` | Any model OpenRouter exposes; set `LLM_MODEL`. |

Override the model globally with `LLM_MODEL=...`, or the per-run default in
`qa_agent/config.py` (`MODEL`).

## What it can do

45 browser fixtures + 1 Android fixture across 10 categories — all PASS on
the default `claude-haiku-4-5`. Levels (L1 → L7) encode rough difficulty:
L1 is a single click, L7 is a long multi-branch workflow.

| category              | levels           | n | example fixture               |
|-----------------------|------------------|---|-------------------------------|
| `static_ui`           | L1–L7            | 7 | `static_l7_wizard_cond`       |
| `spa_dynamic`         | L1–L5            | 5 | `spa_l5_cart_checkout`        |
| `research_synthesis`  | L1–L5            | 5 | `res_l5_four_labs`            |
| `search_retrieval`    | L1–L5            | 5 | `search_l5_bdfl_chain`        |
| `ecommerce_compare`   | L1–L5            | 5 | `ecom_l5_filter_range`        |
| `long_horizon`        | L1–L5            | 5 | `lh_l5_booking_modify`        |
| `social_interactive`  | L1–L3            | 3 | `soc_l3_moderation`           |
| `osint`               | L1–L3            | 3 | `osint_l3_domain_trail`       |
| `web3_defi` (Sepolia) | L1–L7            | 7 | `w3_l7_swap_combo`            |
| `android` (on-device) | L1               | 1 | `android_aliexpress_l1_search` |

Bench harness:

```bash
python -m bench.runner --all               # browser suite
python -m bench.runner static_l3_pricing   # single fixture
python -m bench.analyze                    # per-category p50/p95 cost + pass rate

ANDROID_SERIAL=<ip>:5555 \
  python -m bench.android.runner android_aliexpress_l1_search    # on-device run
```

See [`bench/README.md`](bench/README.md) for fixture structure and
[`bench/android/README.md`](bench/android/README.md) for the phone setup.

## Action DSL (both drivers)

| action              | what it does                                      |
|---------------------|---------------------------------------------------|
| `click <id>`        | click element #id                                 |
| `type <id> "text"`  | focus + type into input/EditText                  |
| `scroll up\|down`   | half-viewport swipe / wheel                       |
| `wait <ms>`         | sleep                                             |
| `press <key>`       | `Enter`, `Tab`, `Backspace`, `back`, `home`, …    |
| `look`              | annotated screenshot (vision re-ask)              |
| `done PASS\|FAIL "…"` | terminate with evidence                        |

Browser-only: `goto <url>`, `tab <n>`, `select <id> "option"`, `hover <id>`.
Android-only: `press back` for back-navigation (no `goto`, no `tab`).

## MCP server

```bash
pip install mcp
```

The repo ships `.mcp.json` for Claude Code. Tools: `qa_run`,
`qa_setup_metamask`, `qa_status`. For global user-scope install:

```bash
claude mcp add qa-browser -s user -- /usr/bin/python3 /path/to/qa-browser-agent/mcp_server.py
```

## MetaMask (web3 fixtures)

```bash
mkdir -p ~/extensions && cd ~/extensions
wget https://github.com/MetaMask/metamask-extension/releases/download/v13.24.0/metamask-chrome-13.24.0.zip
unzip metamask-chrome-13.24.0.zip -d metamask
```

Then provide your testnet seed + password via `.env` (see `.env.example`) and
run `python -m qa_agent --setup-metamask` to bootstrap the bench profile.
**Use a testnet-only seed.** The well-known Hardhat mnemonic in
`config.TEST_SEED` is safe to check in but **must not be funded on mainnet**.

## Project layout

```
qa_agent/
├── agent.py            run_task (browser), run_android_task (phone)
├── providers.py        Anthropic API / OpenRouter
├── llm.py              thin ask_llm dispatcher
├── browser.py          Playwright launcher + stealth args
├── android.py          uiautomator2 driver (extract + execute + vision)
├── extract.py          browser DOM extractor + LavaMoat fallback
├── actions.py          DSL parser + Playwright action executor
├── vision.py           annotated-screenshot (browser)
├── metamask.py         MetaMask onboarding automation
├── cli.py              argparse + dispatch
├── config.py           constants, paths, test-wallet seed
└── runtime/            state machine — FSM, states, transitions, actions

bench/
├── runner/             browser fixture runner + declarative asserts
├── android/            phone fixture runner (parallel tree)
├── fixtures/           9 categories × levels
└── *.md                design docs, recap, audit

mcp_server.py           FastMCP wrapper (stdio)
```

## License

MIT
