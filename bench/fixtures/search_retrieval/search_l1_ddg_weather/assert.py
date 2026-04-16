"""Accept a signed integer followed by a temperature unit.

Matches e.g. "14°C", "−3°C", "57°F", "−3 °C", "12 degrees", "30 градусов".
The agent just has to cite a temperature-shaped number.
"""

from __future__ import annotations

import re


_TEMP = re.compile(
    # Explicit unit
    r"[-−+]?\s?\d+(?:[.,]\d+)?\s*(?:°\s*[CFКcfk]|° |deg(?:rees)?|градус(?:а|ов)?)"
    # …or a signed number 1-3 digits not followed by another digit
    # (weather widgets like DDG's "Сейчас +9")
    r"|[-−+]\s?\d{1,3}(?!\d)",
    re.IGNORECASE,
)


def check(run_log: dict) -> tuple[bool, str]:
    status = run_log.get("status")
    desc = run_log.get("description", "") or ""
    if status != "PASS":
        return False, f"agent status was {status!r}, not PASS"
    m = _TEMP.search(desc)
    if not m:
        return False, f"no temperature-shaped value in description: {desc!r}"
    return True, f"temperature cited: {m.group()!r}"
