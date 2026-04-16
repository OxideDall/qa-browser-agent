"""Require all 4 facts in the description:

  F1. "3" (product count)
  F2. "12 499" (Nebula Cam price in roubles, spaces/NBSP allowed)
  F3. "2018" (founding year)
  F4. "Anna Volkova" (team lead)
"""

from __future__ import annotations

import re


_F1 = re.compile(r"\b3\b")
# Match "12499", "12 499", "12\u00a0499".
_F2 = re.compile(r"12[ \u00a0]?499")
_F3 = re.compile(r"\b2018\b")
_F4 = re.compile(r"\bAnna\s+Volkova\b", re.IGNORECASE)


def check(run_log: dict) -> tuple[bool, str]:
    status = run_log.get("status")
    desc = run_log.get("description", "") or ""
    if status != "PASS":
        return False, f"agent status was {status!r}, not PASS"
    if not _F1.search(desc):
        return False, f"missing F1 (product count '3'): {desc!r}"
    if not _F2.search(desc):
        return False, f"missing F2 (Nebula Cam price '12 499'): {desc!r}"
    if not _F3.search(desc):
        return False, f"missing F3 (founding year '2018'): {desc!r}"
    if not _F4.search(desc):
        return False, f"missing F4 (team lead 'Anna Volkova'): {desc!r}"
    return True, "all four facts cited"
