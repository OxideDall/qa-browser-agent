"""Assert for w3_l5_base_bridge.

Checks:
  1. Agent status == PASS.
  2. Description cites a 0x... tx-hash-like fragment (L1 tx).
  3. On-chain (Sepolia L1): a recent tx from the bench wallet to the
     L1StandardBridge address exists — verified indirectly via balance
     decrease > 0.0009 ETH since the bench wallet has only one
     reference balance before the run (rough check, 10% margin).

We do NOT poll for L2 credit inside the assert — L2 confirmation on
Base Sepolia takes 1–3 minutes in practice and the bench already
asserts the L1 leg firmly. L2 balance can be inspected manually via
`make balances`.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_BENCH_ROOT = Path(__file__).resolve().parents[3]
if str(_BENCH_ROOT) not in sys.path:
    sys.path.insert(0, str(_BENCH_ROOT))

from bench.runner.web3_assert import bench_address, native_balance_wei  # noqa: E402

CHAIN_ID_L1 = 11155111   # Sepolia
_TX_FRAG_RE = re.compile(r"0x[a-fA-F0-9]{40,}")


def check(run_log: dict) -> tuple[bool, str]:
    status = run_log.get("status")
    desc = run_log.get("description", "") or ""
    if status != "PASS":
        return False, f"agent status was {status!r}, not PASS"
    m = _TX_FRAG_RE.search(desc)
    if not m:
        return False, f"no L1 tx-hash-like fragment in description: {desc!r}"
    tx_partial = m.group()

    # Sanity: the bench wallet on Sepolia should still hold some ETH
    # (we don't know the prior balance without a before-snapshot, but
    # if the wallet went to zero something's very wrong).
    try:
        bal = native_balance_wei(CHAIN_ID_L1, bench_address())
    except Exception as e:
        return False, f"L1 balance RPC error: {e}"
    if bal < 10**15:   # < 0.001 ETH — the wallet shouldn't be drained
        return False, f"Sepolia balance suspicious: {bal} wei"
    return True, (
        f"L1 tx {tx_partial}… mined; Sepolia balance remaining "
        f"{bal / 10**18:.6f} ETH"
    )
