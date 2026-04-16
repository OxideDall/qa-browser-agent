"""Accept any ruble price: digits (optional thin space) + ₽ / руб.

Matches "299 ₽", "1 499 ₽", "2\u00a0999 руб.", "от 450 ₽".
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
        return False, f"no ruble-price-shaped token in description: {desc!r}"
    return True, f"price cited: {m.group()!r}"
