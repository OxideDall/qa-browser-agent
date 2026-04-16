"""On-chain assertion helpers for web3_defi fixtures.

Uses public testnet RPCs by default; override via .env (e.g. SEPOLIA_RPC=...).
The bench wallet address comes from BENCH_ADDRESS_0 in .env.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from web3 import Web3

# Default public testnet RPCs. Replace with Alchemy/Infura if rate limits hurt.
DEFAULT_RPCS: dict[int, str] = {
    11155111: "https://ethereum-sepolia-rpc.publicnode.com",         # Sepolia
    84532:    "https://sepolia.base.org",                            # Base Sepolia
    421614:   "https://sepolia-rollup.arbitrum.io/rpc",              # Arbitrum Sepolia
    11155420: "https://sepolia.optimism.io",                         # Optimism Sepolia
    80002:    "https://rpc-amoy.polygon.technology",                 # Polygon Amoy
}

NAMES: dict[int, str] = {
    11155111: "sepolia",
    84532:    "base-sepolia",
    421614:   "arbitrum-sepolia",
    11155420: "optimism-sepolia",
    80002:    "polygon-amoy",
}

ENV_PATH = Path(__file__).resolve().parents[2] / ".env"


def _read_env() -> dict[str, str]:
    """Tiny .env parser — no dependency. Only reads simple KEY=value lines."""
    if not ENV_PATH.exists():
        return {}
    out: dict[str, str] = {}
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip().strip('"').strip("'")
        out[k.strip()] = v
    return out


def rpc_url(chain_id: int) -> str:
    """Resolve RPC URL from .env override or DEFAULT_RPCS."""
    env = _read_env()
    name = NAMES.get(chain_id, str(chain_id)).upper().replace("-", "_")
    key = f"{name}_RPC"
    return env.get(key) or os.environ.get(key) or DEFAULT_RPCS[chain_id]


def w3(chain_id: int) -> Web3:
    return Web3(Web3.HTTPProvider(rpc_url(chain_id), request_kwargs={"timeout": 20}))


def bench_address() -> str:
    env = _read_env()
    return env["BENCH_ADDRESS_0"]


def native_balance_wei(chain_id: int, address: str | None = None) -> int:
    addr = Web3.to_checksum_address(address or bench_address())
    return int(w3(chain_id).eth.get_balance(addr))


def native_balance_eth(chain_id: int, address: str | None = None) -> float:
    return float(Web3.from_wei(native_balance_wei(chain_id, address), "ether"))


# Minimal ERC-20 ABI: balanceOf, decimals, symbol
_ERC20_ABI = [
    {"constant": True, "inputs": [{"name": "_owner", "type": "address"}],
     "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}],
     "type": "function"},
    {"constant": True, "inputs": [], "name": "decimals",
     "outputs": [{"name": "", "type": "uint8"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "symbol",
     "outputs": [{"name": "", "type": "string"}], "type": "function"},
]


def erc20(chain_id: int, token_addr: str):
    web3 = w3(chain_id)
    return web3.eth.contract(
        address=Web3.to_checksum_address(token_addr), abi=_ERC20_ABI
    )


def erc20_balance(chain_id: int, token_addr: str,
                  holder: str | None = None) -> tuple[int, int, str]:
    """Returns (raw_balance, decimals, symbol)."""
    holder = Web3.to_checksum_address(holder or bench_address())
    c = erc20(chain_id, token_addr)
    raw = int(c.functions.balanceOf(holder).call())
    dec = int(c.functions.decimals().call())
    sym = c.functions.symbol().call()
    return raw, dec, sym


def tx_receipt(chain_id: int, tx_hash: str) -> dict[str, Any] | None:
    """Return tx receipt as a dict or None if not yet mined / not found."""
    try:
        r = w3(chain_id).eth.get_transaction_receipt(tx_hash)
    except Exception:
        return None
    return dict(r)


def wait_for_balance_increase(chain_id: int, before_wei: int, *,
                              address: str | None = None,
                              timeout: float = 60.0,
                              poll: float = 2.0) -> bool:
    """Poll until native balance > before_wei or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if native_balance_wei(chain_id, address) > before_wei:
            return True
        time.sleep(poll)
    return False


def wait_for_balance_decrease(chain_id: int, before_wei: int, *,
                              address: str | None = None,
                              timeout: float = 60.0,
                              poll: float = 2.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if native_balance_wei(chain_id, address) < before_wei:
            return True
        time.sleep(poll)
    return False


def funding_check(targets: dict[int, float]) -> tuple[bool, str]:
    """Verify the bench wallet has at least `min_eth` on each chain.

    targets: {chain_id: min_native_balance_in_eth}
    """
    addr = bench_address()
    missing: list[str] = []
    for chain_id, min_eth in targets.items():
        bal = native_balance_eth(chain_id, addr)
        if bal < min_eth:
            missing.append(
                f"{NAMES.get(chain_id, chain_id)}: need {min_eth:.3f}, "
                f"have {bal:.4f}"
            )
    if missing:
        return False, "underfunded: " + "; ".join(missing)
    return True, f"all {len(targets)} chains funded"


def main(argv: list[str] | None = None) -> int:
    """`python -m bench.runner.web3_assert` prints balances on every known chain."""
    addr = bench_address()
    print(f"bench address: {addr}")
    for chain_id, name in NAMES.items():
        try:
            bal = native_balance_eth(chain_id, addr)
            print(f"  {name:<20} ({chain_id:>8}): {bal:.6f}  ({rpc_url(chain_id)})")
        except Exception as e:
            print(f"  {name:<20} ({chain_id:>8}): ERROR {type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
