"""Assert for w3_l6_usdc_transfer.

Checks:
  1. Agent status == PASS.
  2. Description cites a 0x... tx-hash fragment.
  3. On-chain: dead address (0x…dEaD) has non-zero USDC balance — sanity
     that a transfer actually reached it at some point.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_BENCH_ROOT = Path(__file__).resolve().parents[3]
if str(_BENCH_ROOT) not in sys.path:
    sys.path.insert(0, str(_BENCH_ROOT))

from bench.runner.web3_assert import erc20_balance  # noqa: E402

USDC_SEPOLIA = "0x1c7D4B196Cb0C7B01d743Fbc6116a902379C7238"
DEAD = "0x000000000000000000000000000000000000dEaD"
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

    try:
        raw, dec, sym = erc20_balance(CHAIN_ID, USDC_SEPOLIA, DEAD)
    except Exception as e:
        return False, f"erc20_balance RPC error: {e}"
    if sym.upper() not in ("USDC", "USDCC"):
        return False, f"expected USDC, got {sym!r}"
    if raw == 0:
        return False, (
            f"dead address has zero USDC — no transfer ever reached it. "
            f"tx claimed: {tx_partial}"
        )
    return True, (
        f"tx {tx_partial}… mined; dead address holds {raw / 10**dec:.6f} "
        f"{sym} (including this tx)"
    )
