"""Accept if description mentions both the founding year (2021) and
at least one Amodei (Dario or Daniela).
"""

from __future__ import annotations

import re


_YEAR = re.compile(r"\b2021\b")
_FOUNDER = re.compile(r"\b(?:Dario|Daniela)\s+Amodei\b")


def check(run_log: dict) -> tuple[bool, str]:
    status = run_log.get("status")
    desc = run_log.get("description", "") or ""
    if status != "PASS":
        return False, f"agent status was {status!r}, not PASS"
    y = _YEAR.search(desc)
    f = _FOUNDER.search(desc)
    if not y:
        return False, f"description lacks founding year 2021: {desc!r}"
    if not f:
        return False, f"description lacks founder Amodei name: {desc!r}"
    return True, f"year {y.group()} + founder {f.group()!r} cited"
