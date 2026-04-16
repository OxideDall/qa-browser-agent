"""Accept if description mentions PEP 498 (the right answer).

We reject 701 (PEP 701 clarified f-string grammar in 3.12 but didn't
"introduce" them) and any other 3-digit PEP that isn't 498.
"""

from __future__ import annotations

import re


_PEP498 = re.compile(r"\b(?:pep\s*[-#]?\s*)?498\b", re.IGNORECASE)
_WRONG_PEP = re.compile(r"\bPEP\s*[-#]?\s*701\b", re.IGNORECASE)


def check(run_log: dict) -> tuple[bool, str]:
    status = run_log.get("status")
    desc = run_log.get("description", "") or ""
    if status != "PASS":
        return False, f"agent status was {status!r}, not PASS"
    if not _PEP498.search(desc):
        return False, f"description does not cite PEP 498: {desc!r}"
    if _WRONG_PEP.search(desc) and not re.search(
        r"\b(?:not\s*701|but\s*498)\b", desc, re.IGNORECASE
    ):
        return False, (
            f"description cites PEP 701 (grammar clarification, not "
            f"introduction). The question asks for the PEP that INTRODUCED "
            f"f-strings (PEP 498). Got: {desc!r}"
        )
    return True, "PEP 498 cited"
