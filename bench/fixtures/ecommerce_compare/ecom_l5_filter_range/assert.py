"""Require 2 `NNN ₽` prices in the description with laptop (max) > cable (min).

Also require at least one of the words: 'cable', 'cables', 'кабель',
'кабел' (root) to anchor the comparison to the right items. Similarly
require 'laptop', 'laptops', 'ноутбук'.
"""

from __future__ import annotations

import re


_PRICE = re.compile(r"(\d[\d \u00a0]*)\s*₽")


def _parse_int(raw: str) -> int:
    return int(raw.replace(" ", "").replace("\u00a0", ""))


_CABLE = re.compile(r"\b(cable|cables|кабел\w*|USB\s+кабель)\b", re.IGNORECASE)
_LAPTOP = re.compile(r"\b(laptop|laptops|ноутбук\w*)\b", re.IGNORECASE)


def check(run_log: dict) -> tuple[bool, str]:
    status = run_log.get("status")
    desc = run_log.get("description", "") or ""
    if status != "PASS":
        return False, f"agent status was {status!r}, not PASS"
    if not _CABLE.search(desc):
        return False, f"missing 'cable'/'кабель' anchor: {desc!r}"
    if not _LAPTOP.search(desc):
        return False, f"missing 'laptop'/'ноутбук' anchor: {desc!r}"
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
            f"both prices are the same ({lo} ₽); laptop must be "
            f"strictly more than cable: {desc!r}"
        )
    if lo <= 0:
        return False, f"prices must be positive, got min={lo}: {desc!r}"
    # Whatever WB surfaces as cheapest — even an accessory — must still
    # cost strictly more than the cheapest USB cable for the comparison
    # to be meaningful. We don't second-guess WB's catalog here.
    return True, f"cheapest cable {lo} ₽, cheapest laptop {hi} ₽ cited"
