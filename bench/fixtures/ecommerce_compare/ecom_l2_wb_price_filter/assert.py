"""Accept if description contains at least 3 distinct ruble prices.

We match \d[ \u00a0\u202f]?\d*…\s*₽|руб and collect unique prices.
"""

from __future__ import annotations

import re


_PRICE = re.compile(
    r"\d{1,3}(?:[ \u00a0\u202f]?\d{3})*(?:[.,]\d+)?\s*(?:₽|руб(?:\.|лей|ля|ль)?)",
    re.IGNORECASE,
)


def _normalize(p: str) -> str:
    # collapse internal whitespace so "1 450 ₽" and "1\u00a0450 ₽" are equal
    return re.sub(r"\s+", " ", p).strip()


def check(run_log: dict) -> tuple[bool, str]:
    status = run_log.get("status")
    desc = run_log.get("description", "") or ""
    if status != "PASS":
        return False, f"agent status was {status!r}, not PASS"
    hits = [_normalize(p) for p in _PRICE.findall(desc)]
    unique = list(dict.fromkeys(hits))
    if len(unique) < 3:
        return False, (
            f"expected ≥3 distinct ruble prices, got {len(unique)}: "
            f"{unique!r} in description {desc!r}"
        )
    return True, f"3 distinct prices cited: {unique[:3]!r}"
