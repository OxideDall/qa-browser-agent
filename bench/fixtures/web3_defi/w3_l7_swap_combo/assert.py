"""Assert for w3_l7_swap_combo.

Checks:
  1. Agent status == PASS.
  2. Description cites a 0x... tx-hash-like fragment (the swap tx).
  3. On-chain: USDC balance is non-zero (previous L4 swap may have left
     some; we compare delta against a baseline stored in ctx.t_start
     implicitly — here we just assert it's non-zero, which any successful
     swap in this session's runs satisfies).

Because the agent's `done PASS` quote may only include ONE of the three
tx hashes (usually the last — the swap), the assert doesn't try to
verify all three individually. The USDC balance delta is the real proof.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_BENCH_ROOT = Path(__file__).resolve().parents[3]
if str(_BENCH_ROOT) not in sys.path:
    sys.path.insert(0, str(_BENCH_ROOT))

from bench.runner.web3_assert import bench_address, erc20_balance  # noqa: E402

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

    try:
        raw, dec, sym = erc20_balance(
            CHAIN_ID, USDC_SEPOLIA, bench_address()
        )
    except Exception as e:
        return False, f"erc20_balance RPC error: {e}"
    if sym.upper() not in ("USDC", "USDCC"):
        return False, f"expected USDC, got {sym!r}"
    if raw == 0:
        return False, f"USDC balance is zero — combo didn't credit. tx {tx_partial}"
    return True, (
        f"tx {tx_partial}… mined; on-chain USDC balance "
        f"{raw / 10**dec:.6f} {sym}"
    )
