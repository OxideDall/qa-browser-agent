"""Require two prices (cheapest + most-expensive) with ₽ symbol, min < max.

Parses all `NNN ₽` price tokens from the description. At least two
distinct numeric values must appear, and the numeric min must be
strictly less than the numeric max.
"""

from __future__ import annotations

import re


# Match "1 234 ₽" / "93 ₽" / "12\u00a0933\u00a0₽" etc.
# Captures digits with optional spaces between groups (NBSP included).
_PRICE = re.compile(r"(\d[\d \u00a0]*)\s*₽")


def _parse_int(raw: str) -> int:
    return int(raw.replace(" ", "").replace("\u00a0", ""))


def check(run_log: dict) -> tuple[bool, str]:
    status = run_log.get("status")
    desc = run_log.get("description", "") or ""
    if status != "PASS":
        return False, f"agent status was {status!r}, not PASS"
    tokens = _PRICE.findall(desc)
    if len(tokens) < 2:
        return False, (
            f"expected at least 2 '… ₽' prices in description, "
            f"got {len(tokens)}: {desc!r}"
        )
    values = [_parse_int(t) for t in tokens]
    lo, hi = min(values), max(values)
    if lo == hi:
        return False, (
            f"cheapest and most-expensive cited as the same value ({lo} ₽): "
            f"{desc!r}"
        )
    if lo <= 0:
        return False, f"cheapest price must be positive, got {lo}: {desc!r}"
    return True, f"cheapest {lo} ₽, most-expensive {hi} ₽ cited"
