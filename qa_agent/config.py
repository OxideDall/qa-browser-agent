"""Shared constants and configuration.

LLM model / provider / auth are NOT here — they live in
`qa_agent.providers` and are driven by env vars (LLM_PROVIDER, LLM_MODEL,
ANTHROPIC_API_KEY, OPENROUTER_API_KEY). See README.
"""

from pathlib import Path

# ── Default model suggestion (kept for CLI --model override) ─────────
# Providers look at LLM_MODEL env first; this only ships as the default
# if neither the CLI nor env sets one.
MODEL = "claude-haiku-4-5"

# ── Agent loop ────────────────────────────────────────────────
STEP_TIMEOUT = 10_000
NAV_TIMEOUT = 15_000
HISTORY_WINDOW = 10
DEFAULT_MAX_STEPS = 30

# ── Paths ─────────────────────────────────────────────────────
SCREENSHOT_DIR = Path("qa_screenshots")
PROFILE_DIR = Path.home() / ".config" / "qa_agent" / "browser_profile"
METAMASK_EXT = Path.home() / "extensions" / "metamask"

# ── Browser stealth (WebGL/WASM for DeFi SPAs) ────────────────
BROWSER_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--use-angle=gl",
    "--disable-dev-shm-usage",
    "--no-sandbox",
]
STEALTH_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
STEALTH_INIT_SCRIPT = 'Object.defineProperty(navigator,"webdriver",{get:()=>undefined})'

# ── MetaMask test wallet (publicly known Hardhat seed — DO NOT FUND) ──
# This is the well-known Hardhat default mnemonic, safe to check in.
# It derives deterministic addresses on every EVM chain so anyone can
# reproduce local-fork tests. The paired password is only used to
# unlock the MetaMask UI inside the bench browser profile.
TEST_SEED = "test test test test test test test test test test test junk"
TEST_PASSWORD = "Testpassword1!"
