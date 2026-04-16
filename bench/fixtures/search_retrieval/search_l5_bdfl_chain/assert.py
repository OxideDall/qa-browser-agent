"""Require PEP 572 + a python-dev mailing-list URL fragment `YYYY-Month` +
6-digit post number matching PEP 572's Resolution field.

PEP 572's Resolution is:
  https://mail.python.org/pipermail/python-dev/2018-July/154601.html
so the description must contain "572", "2018-July" (case-insensitive),
and the exact 6-digit post number "154601".
"""

from __future__ import annotations

import re


_PEP = re.compile(r"\bPEP\s*0*572\b", re.IGNORECASE)
_MONTH = re.compile(r"\b2018[-\s]+July\b", re.IGNORECASE)
_POSTNUM = re.compile(r"\b154601\b")


def check(run_log: dict) -> tuple[bool, str]:
    status = run_log.get("status")
    desc = run_log.get("description", "") or ""
    if status != "PASS":
        return False, f"agent status was {status!r}, not PASS"
    if not _PEP.search(desc):
        return False, f"missing PEP 572 reference: {desc!r}"
    if not _MONTH.search(desc):
        return False, (
            f"missing '2018-July' resolution-date token: {desc!r}"
        )
    if not _POSTNUM.search(desc):
        return False, (
            f"missing '154547' resolution post number: {desc!r}"
        )
    return True, "PEP 572 + 2018-July + 154601 all cited"
