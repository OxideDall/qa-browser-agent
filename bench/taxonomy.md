# QA Agent Bench — Taxonomy

Living spec for the benchmark suite. Update this file whenever a fixture is
added, retired, or its assert changes.

## Design

- **8 categories** covering distinct interaction modalities.
- **6 standard levels** L1–L6 per category, plus **L7–L8** extension for
  `web3_defi` and `search_retrieval` where the failure modes are richer.
- Total: **52 fixtures** (8×6 + 2×2).
- Every fixture is reproducible and has a programmatic OR LLM-judge assert.
- Web3 fixtures run on testnets only; native gas comes from the bench wallet
  (`BENCH_ADDRESS_0` in `.env`).

## Categories

| # | id                  | What it stresses                                                       |
|---|---------------------|------------------------------------------------------------------------|
| 1 | `static_ui`         | Plain DOM, forms, no SPA state. Smoke + parser sanity.                 |
| 2 | `spa_dynamic`       | React/Vue, lazy load, modals, virtualized lists, route changes.        |
| 3 | `search_retrieval`  | Search engines, query refinement, niche/obscure queries (L1–L8).       |
| 4 | `ecommerce_compare` | Carts, configurators, cross-store comparison, filters.                 |
| 5 | `research_synthesis`| Multi-source fact-gathering, contradiction resolution, timelines.      |
| 6 | `social_interactive`| Messengers, chat-bots, forums, multi-turn negotiation.                 |
| 7 | `web3_defi`         | Wallet flows, swaps, lending, bridging, NFT, governance (L1–L8).       |
| 8 | `long_horizon`      | Multi-tab, mid-flow resume, multi-day orchestration.                   |

## Levels

| Lvl | Code        | Definition                                                            |
|-----|-------------|-----------------------------------------------------------------------|
| L1  | `smoke`     | 1–3 actions, deterministic, single page.                              |
| L2  | `linear`    | 5–10 actions, single path, single screen or shallow nav.              |
| L3  | `branching` | Pick best option from 2–3 alternatives by stated criterion.           |
| L4  | `stateful`  | Carry a value or selection across multiple pages, verify end-state.   |
| L5  | `recovery`  | Intentional flake / disappearing element / changing UI; agent adapts. |
| L6  | `open`      | No fixed solution path; LLM judge scores outcome quality.             |
| L7  | `cross`     | Multiple domains / protocols / engines in one task.                   |
| L8  | `adversary` | Anti-bot, honeypot, rate-limit, AI-spam in results.                   |

## Full matrix (52 fixtures)

### 1. `static_ui` (L1–L6)

| L | id                         | Task summary                                       | Assert         |
|---|----------------------------|----------------------------------------------------|----------------|
| 1 | `static_l1_confirm`        | Click Confirm, verify toast text.                  | DOM text       |
| 2 | `static_l2_register`       | Fill 6-field registration form, submit.            | URL = /success |
| 3 | `static_l3_pricing`        | Pick "Pro" plan from 3 ≤ $50, fill billing.        | data-selected  |
| 4 | `static_l4_wizard`         | 4-step wizard; review screen must echo inputs.     | Field equality |
| 5 | `static_l5_flaky_save`     | Save button no-ops on first click; retry/different.| Success ≤ 3 try|
| 6 | `static_l6_freeform`       | Arbitrary HTML doc, "fill out everything sane".    | LLM judge      |

### 2. `spa_dynamic` (L1–L6)

| L | id                         | Task summary                                       | Assert            |
|---|----------------------------|----------------------------------------------------|-------------------|
| 1 | `spa_l1_todomvc`           | TodoMVC: add 3, complete 2nd, verify counts.       | localStorage      |
| 2 | `spa_l2_github_issue`      | gh-clone: search repo, open issue, comment.        | Comment exists    |
| 3 | `spa_l3_notion_doc`        | Notion-clone: create doc, 3 nested items, format.  | DOM structure     |
| 4 | `spa_l4_trello_drag`       | Trello-clone: drag card ToDo→Done.                 | Column count Δ    |
| 5 | `spa_l5_gmail_skeleton`    | Gmail-clone w/ 3–7 s skeleton; archive 2nd email.  | Inbox count -1    |
| 6 | `spa_l6_freeform_spa`      | Unknown SPA: discover main feature, demo it.       | LLM judge         |

### 3. `search_retrieval` (L1–L8)

| L | id                         | Task summary                                       | Assert            |
|---|----------------------------|----------------------------------------------------|-------------------|
| 1 | `search_l1_weather`        | "погода в Москве сейчас"                          | Number+°C         |
| 2 | `search_l2_lib`            | Python lib for X, >5k stars, active 6 mo.          | repo URL match    |
| 3 | `search_l3_refine`         | Article 2024, topic Y, NOT medium.com.             | URL+title         |
| 4 | `search_l4_attribution`    | Verify quote attribution to original source.       | Source URL+verbatim|
| 5 | `search_l5_obscure`        | Default timeout in `requests` 2.31 (number+ref).   | Exact value       |
| 6 | `search_l6_open_facts`     | "3 интересных факта про X"                        | LLM judge         |
| 7 | `search_l7_cross_engine`   | Same query in Google + DDG + Reddit, consensus.    | Cross-source check|
| 8 | `search_l8_adversarial`    | Query that triggers AI-overview spam; dig past.    | Non-AI src found  |

### 4. `ecommerce_compare` (L1–L6)

| L | id                         | Task summary                                       | Assert            |
|---|----------------------------|----------------------------------------------------|-------------------|
| 1 | `ecom_l1_wb_lookup`        | WB: search USB-C cable, top result, return price.  | Number + currency |
| 2 | `ecom_l2_wb_cart`          | WB: cart 3 items, each >2000₽.                    | Total >6000₽      |
| 3 | `ecom_l3_laptop_config`    | WB laptop filter (16GB/SSD/14"), top-rated.        | Filters + selected|
| 4 | `ecom_l4_cross_store`      | Same headphones WB vs Ozon vs YM, cheapest+ETA<3d. | dict[3]+winner    |
| 5 | `ecom_l5_price_alert`      | Subscribe to price drop, verify saved.             | Watchlist entry   |
| 6 | `ecom_l6_gift_basket`      | Подарок 25-летней к 8 марта, бюджет 5000₽.        | LLM judge         |

### 5. `research_synthesis` (L1–L6)

| L | id                         | Task summary                                       | Assert            |
|---|----------------------------|----------------------------------------------------|-------------------|
| 1 | `res_l1_ceo`               | CEO of company X.                                  | Name match        |
| 2 | `res_l2_spac_caps`         | Top-5 SPAC market caps 2024.                       | 5-row dict        |
| 3 | `res_l3_saas_matrix`       | Compare 3 SaaS products feature-by-feature.        | Matrix structure  |
| 4 | `res_l4_factcheck`         | Verify a claim, verdict + 3 citations.             | Verdict + URLs    |
| 5 | `res_l5_timeline`          | Reconstruct event chronology from 5+ sources.      | Timeline list     |
| 6 | `res_l6_lit_review`        | 5 papers on topic X, summarize differences.        | LLM judge         |

### 6. `social_interactive` (L1–L6)

| L | id                         | Task summary                                       | Assert            |
|---|----------------------------|----------------------------------------------------|-------------------|
| 1 | `soc_l1_discord_msg`       | Discord (init_script seed): post in #test.         | Message exists    |
| 2 | `soc_l2_tg_echobot`        | TG Web: @ExampleBot, 3 echoes.                     | Echo received     |
| 3 | `soc_l3_devto_comment`     | dev.to: comment with markdown formatting.          | Comment HTML match|
| 4 | `soc_l4_haggle_bot`        | Multi-turn negotiation w/ price-haggle bot.        | Final price ≤ X   |
| 5 | `soc_l5_email_verify`      | Onboarding flow w/ mailtrap email click-through.   | Account active    |
| 6 | `soc_l6_support_chat`      | Support bot: describe fake bug, get fix path.      | LLM judge         |

### 7. `web3_defi` (L1–L8) — primary focus

| L | id                         | Network              | Protocol            | Assert                    |
|---|----------------------------|----------------------|---------------------|---------------------------|
| 1 | `w3_l1_connect_sign`       | Sepolia              | test dApp           | Signature valid           |
| 2 | `w3_l2_balances`           | Sepolia + Base Sep.  | native + ERC-20     | Numbers returned          |
| 3 | `w3_l3_swap_uniswap`       | Sepolia              | Uniswap v3          | tx receipt + balance Δ    |
| 4 | `w3_l4_aave_supply_borrow` | Base Sepolia         | Aave v3             | aToken mint + debt mint   |
| 5 | `w3_l5_bridge_eth`         | Sepolia → Base Sep.  | Base official bridge| Dest balance after wait   |
| 6 | `w3_l6_nft_mint_list`      | Sepolia              | OpenSea testnet     | Listing API confirms      |
| 7 | `w3_l7_combo`              | Sep → Base + Aave    | LayerZero/Stargate+ | End-state matches plan    |
| 8 | `w3_l8_governance`         | Sepolia              | Tally / Snapshot    | On-chain vote tx          |

### 8. `long_horizon` (L1–L6)

| L | id                         | Task summary                                       | Assert            |
|---|----------------------------|----------------------------------------------------|-------------------|
| 1 | `lh_l1_three_tabs`         | 3 tabs, 1 fact each, summarize.                    | 3 facts in output |
| 2 | `lh_l2_resume`             | Given saved state mid-flow, resume to completion.  | Final state       |
| 3 | `lh_l3_calendar_event`     | Research a free slot, create G-Cal event.          | Event exists      |
| 4 | `lh_l4_hotel_dryrun`       | Booking flow up to (but not incl.) payment.        | Form filled       |
| 5 | `lh_l5_trip_plan`          | Flight + hotel + activity → itinerary.             | Itinerary struct  |
| 6 | `lh_l6_weekly`             | 7 simulated days; daily check + EOW report.        | Report 7 events   |

## Fixture file conventions

Each fixture lives at `bench/fixtures/<category>/<id>/`:

```
<id>/
  task.txt          # plain-text task description fed verbatim to the agent
  config.toml       # network / protocol / start_url / headless / max_steps
  assert.py         # programmatic check (importable: def check(run_log) -> bool, str)
  assert.json       # OR: declarative assert (preferred when sufficient)
  site/             # OPTIONAL: self-hosted HTML/JS for static fixtures
  init.js           # OPTIONAL: pre-seed localStorage etc. (see --init-script)
  expected.toml     # budget: max_steps, max_tokens, max_wall_seconds
```

`config.toml` schema:

```toml
[fixture]
id              = "static_l1_confirm"
category        = "static_ui"
level           = 1
title           = "Click Confirm and verify the toast"

[run]
url             = "http://localhost:8765/static/l1_confirm/"   # or live URL
headless        = true
max_steps       = 5
extensions      = []                                           # ["metamask"] for web3
init_script     = "init.js"                                    # OPTIONAL

[budget]
max_steps       = 5
max_tokens      = 4000
max_wall_seconds = 30

[network]                                                      # web3 only
chain_id        = 11155111
rpc             = "default"                                    # MM-supplied
required_balance_eth = 0.1
```

## Run log JSONL schema

`bench/results/runs/<fixture_id>__<iso_ts>.jsonl`. One line per step + one
final line.

```jsonc
// Per step
{"t": "step", "step": 1, "action": "click", "args": ["5"],
 "el_label": "[5] btn 'Confirm'", "result": "Clicked [5] btn 'Confirm'",
 "latency_ms": 1240, "in_tokens": 387, "out_tokens": 12,
 "snapshot_size": 17, "page_url": "http://localhost:8765/static/l1_confirm/",
 "mm_active": false, "evidence_present": false, "loop_hit": null,
 "done_reasked": false}

// Final
{"t": "result", "fixture_id": "static_l1_confirm", "status": "PASS",
 "description": "toast text matched", "steps_used": 3, "wall_seconds": 4.2,
 "total_in": 1140, "total_out": 38,
 "asserts": {"toast_text": {"expected": "Confirmed!", "got": "Confirmed!", "ok": true}}}
```

## Infrastructure per category

| Category            | Network needed | External deps                          |
|---------------------|----------------|----------------------------------------|
| `static_ui`         | none           | local HTTP server                      |
| `spa_dynamic`       | none           | vendored SPA bundles + local server    |
| `search_retrieval`  | internet       | Google/DDG/Reddit/Kagi access          |
| `ecommerce_compare` | internet       | WB/Ozon/YM availability                |
| `research_synthesis`| internet       | open web                               |
| `social_interactive`| internet       | Discord/TG/dev.to test accounts        |
| `web3_defi`         | internet+RPC   | testnet ETH/MATIC, MM extension        |
| `long_horizon`      | internet       | varies                                 |

## Testnet inventory (for `web3_defi`)

| Network          | Chain ID | Faucet (manual fallback)                | Bench balance target |
|------------------|----------|-----------------------------------------|----------------------|
| Sepolia          | 11155111 | sepoliafaucet.com / Alchemy             | 50 ETH               |
| Base Sepolia     | 84532    | superchain faucet / Coinbase            | 25 ETH               |
| Arbitrum Sepolia | 421614   | Alchemy + bridge from Sepolia           | 12 ETH               |
| Optimism Sepolia | 11155420 | superchain faucet                       | 12 ETH               |
| Polygon Amoy     | 80002    | faucet.polygon.technology               | 1000 MATIC           |

Stables (USDC/USDT/DAI testnet) come from in-protocol faucets (e.g. Aave's
Base Sepolia faucet) at fixture setup time.

## Run conventions

- Every fixture must be runnable in isolation: `python -m bench.runner <id>`
- Full suite: `python -m bench.runner --all` (parallelism per category caps).
- Web3 suite skipped automatically when on-chain balance < required.
- Results always written; failed fixtures keep their run log + last screenshot.
