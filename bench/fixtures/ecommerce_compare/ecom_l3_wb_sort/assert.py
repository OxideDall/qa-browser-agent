"""Accept any ruble price (the cheapest on a sort=priceup page ought to
be small, <5000₽ for a power bank, but we don't hardcode the exact
number since prices move).
"""

from __future__ import annotations

import re


_PRICE = re.compile(
    r"\d{1,3}(?:[ \u00a0\u202f]?\d{3})*(?:[.,]\d+)?\s*(?:₽|руб(?:\.|лей|ля|ль)?)",
    re.IGNORECASE,
)


def check(run_log: dict) -> tuple[bool, str]:
    status = run_log.get("status")
    desc = run_log.get("description", "") or ""
    if status != "PASS":
        return False, f"agent status was {status!r}, not PASS"
    m = _PRICE.search(desc)
    if not m:
        return False, f"no ruble price in description: {desc!r}"
    return True, f"cheapest price cited: {m.group()!r}"
