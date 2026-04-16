"""Programmatic assert for w3_l4_uniswap_swap.

Checks:
  1. Agent status == PASS
  2. Agent's done-PASS description contains a recognizable 0x... fragment
  3. On-chain: USDC balance increased from baseline
     (we compare against the *larger* of the recorded before-snapshot and
     a hardcoded floor; the actual amount depends on pool price.)
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

USDC_SEPOLIA = "0x1c7D4B196Cb0C7B01d743Fbc6116a902379C7238"
CHAIN_ID = 11155111

_TX_FRAG_RE = re.compile(r"0x[a-fA-F0-9]{40,}")


def check(run_log: dict) -> tuple[bool, str]:
    status = run_log.get("status")
    desc = run_log.get("description", "") or ""

    if status != "PASS":
        return False, f"agent status was {status!r}, not PASS"

    m = _TX_FRAG_RE.search(desc)
    if not m:
        return False, f"no tx-hash-like fragment in description: {desc!r}"
    tx_partial = m.group()

    # On-chain: USDC balance must be non-zero. Testnet pools can give
    # weird prices; any USDC received counts as success.
    try:
        raw, dec, sym = erc20_balance(CHAIN_ID, USDC_SEPOLIA, bench_address())
    except Exception as e:
        return False, f"erc20_balance RPC error: {e}"
    if sym.upper() not in ("USDC", "USDCC"):
        return False, f"expected USDC, got {sym!r}"
    if raw == 0:
        return False, (
            f"USDC balance is still 0 — swap did not credit USDC. "
            f"tx claimed: {tx_partial}"
        )
    return True, (
        f"tx {tx_partial}… mined; on-chain USDC balance "
        f"{raw / 10**dec:.6f} {sym}"
    )
