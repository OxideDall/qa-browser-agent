"""Require the 3-source chain facts: domain, registrant org, GitHub org
handle, and public-repo count (5).
"""

from __future__ import annotations

import re


_DOMAIN = re.compile(r"\bhalcyon-data\.io\b", re.IGNORECASE)
_REG = re.compile(r"\bHalcyon\s+Data\s+Ltd\b", re.IGNORECASE)
_GH = re.compile(r"\bhalcyon-data\b")  # gh handle; also in domain — that's fine
_COUNT = re.compile(r"\b5\b")
_REPOS = re.compile(r"\brepositor(?:y|ies)\b|\brepos?\b", re.IGNORECASE)


def check(run_log: dict) -> tuple[bool, str]:
    status = run_log.get("status")
    desc = run_log.get("description", "") or ""
    if status != "PASS":
        return False, f"agent status was {status!r}, not PASS"
    if not _DOMAIN.search(desc):
        return False, f"missing domain 'halcyon-data.io': {desc!r}"
    if not _REG.search(desc):
        return False, f"missing registrant 'Halcyon Data Ltd': {desc!r}"
    if not _GH.search(desc):
        return False, f"missing GitHub org handle 'halcyon-data': {desc!r}"
    if not _COUNT.search(desc):
        return False, f"missing repo count '5': {desc!r}"
    if not _REPOS.search(desc):
        return False, (
            f"count must be framed as repositories/repos (to disambiguate "
            f"from other 5's): {desc!r}"
        )
    return True, "domain + registrant + gh handle + 5 repos all cited"
