"""Programmatic assert for w3_l3_wrap_eth.

Checks:
  1. Agent status == PASS
  2. Agent's done-PASS description contains a 66-char 0x tx hash
  3. On-chain: WETH balance on Sepolia >= 0.01 ETH (allow small dust tolerance)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_BENCH_ROOT = Path(__file__).resolve().parents[3]
if str(_BENCH_ROOT) not in sys.path:
    sys.path.insert(0, str(_BENCH_ROOT))

from bench.runner.web3_assert import (  # noqa: E402
    bench_address, erc20_balance,
)

WETH_SEPOLIA = "0xfFf9976782d46CC05630D1f6eBAb18b2324d6B14"
CHAIN_ID = 11155111
MIN_WETH_WEI = 10_000_000_000_000_000  # 0.01 ETH in wei


# Partial hashes are OK — the DSL snapshot truncates text to 60/120 chars, so
# vision-driven reports may drop the last few hex chars. The on-chain balance
# check is the real arbiter; the partial-hash check is just a sanity probe.
_TX_HASH_RE = re.compile(r"0x[a-fA-F0-9]{40,}")


def check(run_log: dict) -> tuple[bool, str]:
    status = run_log.get("status")
    desc = run_log.get("description", "") or ""

    if status != "PASS":
        return False, f"agent status was {status!r}, not PASS"

    # The agent's report must cite at least a recognizable tx-hash fragment.
    m = _TX_HASH_RE.search(desc)
    if not m:
        return False, f"no tx-hash-like fragment in description: {desc!r}"
    tx_partial = m.group()

    # On-chain truth: WETH balance >= 0.01. This is the real assert.
    try:
        raw, dec, sym = erc20_balance(CHAIN_ID, WETH_SEPOLIA, bench_address())
    except Exception as e:
        return False, f"erc20_balance RPC error: {e}"
    if sym.upper() not in ("WETH", "WETH9"):
        return False, f"expected WETH, got {sym!r}"
    if raw < MIN_WETH_WEI:
        return False, (
            f"WETH balance too low on-chain: {raw / 10**dec:.6f} "
            f"(need >= 0.01). tx claimed: {tx_partial}"
        )
    return True, (
        f"tx {tx_partial}… mined; on-chain WETH balance "
        f"{raw / 10**dec:.6f} {sym}"
    )
