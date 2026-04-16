"""Accept if description mentions one of the canonical async HTTP libs.

`httpx` and `aiohttp` are both well-known async clients. We also accept
`trio-http` / `curio` / `httpcore` as less-common valid answers. We
REJECT `requests` (sync-only), `urllib3` (transport), `urllib` (stdlib
sync) — these are anti-matches.
"""

from __future__ import annotations

import re


_MATCH = re.compile(r"\b(?:httpx|aiohttp|httpcore|trio-http|curio)\b", re.IGNORECASE)
_ANTI = re.compile(r"\b(?:urllib3?|requests|http\.client)\b", re.IGNORECASE)


def check(run_log: dict) -> tuple[bool, str]:
    status = run_log.get("status")
    desc = run_log.get("description", "") or ""
    if status != "PASS":
        return False, f"agent status was {status!r}, not PASS"
    m = _MATCH.search(desc)
    if not m:
        if _ANTI.search(desc):
            a = _ANTI.search(desc).group()
            return False, (
                f"description cites {a!r} but the criteria rule it out "
                f"(sync-only / lower-level): {desc!r}"
            )
        return False, f"no canonical async-HTTP library cited: {desc!r}"
    return True, f"library cited: {m.group()!r}"
