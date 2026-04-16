"""Accept any mention of Dario Amodei (the current CEO).

Lenient because Wikipedia phrasing shifts and the agent might report
"Dario Amodei (CEO, co-founder)" or similar. All we require is that the
proper noun "Dario Amodei" appears in the done-PASS description.
"""

from __future__ import annotations

import re


_NAME = re.compile(r"Dario\s+Amodei", re.IGNORECASE)


def check(run_log: dict) -> tuple[bool, str]:
    status = run_log.get("status")
    desc = run_log.get("description", "") or ""
    if status != "PASS":
        return False, f"agent status was {status!r}, not PASS"
    if not _NAME.search(desc):
        return False, f"description lacks 'Dario Amodei': {desc!r}"
    return True, f"CEO name cited: {_NAME.search(desc).group()!r}"
