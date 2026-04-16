"""Require PEP number 634 + its Status (Final, as of Python 3.10)."""

from __future__ import annotations

import re


_PEP = re.compile(r"\bPEP\s*0*634\b", re.IGNORECASE)
_FINAL = re.compile(r"\bFinal\b", re.IGNORECASE)


def check(run_log: dict) -> tuple[bool, str]:
    status = run_log.get("status")
    desc = run_log.get("description", "") or ""
    if status != "PASS":
        return False, f"agent status was {status!r}, not PASS"
    if not _PEP.search(desc):
        return False, f"missing PEP 634 reference: {desc!r}"
    if not _FINAL.search(desc):
        return False, (
            f"missing PEP Status (expected 'Final' for PEP 634): {desc!r}"
        )
    return True, "PEP 634 + Status Final cited"
