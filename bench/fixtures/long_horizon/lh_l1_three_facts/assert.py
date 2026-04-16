"""Require all three fact-keywords in the done-PASS description.

Lenient per-fact: any of a small set of synonyms counts, so the agent
has some phrasing leeway.
"""

from __future__ import annotations

import re


_GEO = re.compile(r"\bparis\b", re.IGNORECASE)
_TECH = re.compile(r"\b(?:python|guido\s+van\s+rossum)\b", re.IGNORECASE)
_PHYS = re.compile(r"299[\s,.]?792|light|speed\s+of\s+light", re.IGNORECASE)


def check(run_log: dict) -> tuple[bool, str]:
    status = run_log.get("status")
    desc = run_log.get("description", "") or ""
    if status != "PASS":
        return False, f"agent status was {status!r}, not PASS"
    missing = []
    if not _GEO.search(desc):
        missing.append("geography (Paris)")
    if not _TECH.search(desc):
        missing.append("programming (Python / Guido van Rossum)")
    if not _PHYS.search(desc):
        missing.append("physics (speed of light / 299792458)")
    if missing:
        return False, (
            f"description missing {missing!r}. Got: {desc!r}"
        )
    return True, "all three facts cited"
