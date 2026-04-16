"""Require the cross-referenced identity:
- full first name "Karin" (NOT "Kurt" — that's the decoy)
- surname "Müller"
- employer "Halcyon Data"
- marker of two-source agreement ("confirm"/"cross-reference"/"both"/"two")
"""

from __future__ import annotations

import re


_KARIN = re.compile(r"\bKarin\b")
_MULLER = re.compile(r"\bM[üu]ller\b", re.IGNORECASE)
_EMPLOYER = re.compile(r"\bHalcyon\s+Data\b", re.IGNORECASE)
_DECOY = re.compile(r"\bKurt\s+M[üu]ller\b", re.IGNORECASE)
_AGREEMENT = re.compile(
    r"\b(confirm\w*|cross[- ]?reference\w*|both\s+sources|two\s+sources|подтвержд\w*)\b",
    re.IGNORECASE,
)


def check(run_log: dict) -> tuple[bool, str]:
    status = run_log.get("status")
    desc = run_log.get("description", "") or ""
    if status != "PASS":
        return False, f"agent status was {status!r}, not PASS"
    if _DECOY.search(desc):
        return False, (
            f"description names the decoy 'Kurt Müller' — must point "
            f"at Karin instead: {desc!r}"
        )
    if not _KARIN.search(desc):
        return False, f"missing full first name 'Karin': {desc!r}"
    if not _MULLER.search(desc):
        return False, f"missing surname 'Müller': {desc!r}"
    if not _EMPLOYER.search(desc):
        return False, f"missing employer 'Halcyon Data': {desc!r}"
    if not _AGREEMENT.search(desc):
        return False, (
            f"description must indicate two-source agreement (e.g. "
            f"'confirmed', 'cross-reference', 'both sources'): {desc!r}"
        )
    return True, "Karin Müller @ Halcyon Data + cross-reference marker cited"
