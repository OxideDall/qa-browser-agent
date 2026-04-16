"""Require both years (2015, 2021) + the earlier-founded company name.

OpenAI (Dec 2015) is earlier than Anthropic (Jan 2021).
"""

from __future__ import annotations

import re


_Y_OPENAI = re.compile(r"\b2015\b")
_Y_ANTHROPIC = re.compile(r"\b2021\b")
_EARLIER = re.compile(r"\bOpenAI\b.*\b(?:first|earlier|before|ранее)\b"
                      r"|\b(?:first|earlier|before|ранее)\b.*\bOpenAI\b",
                      re.IGNORECASE)


def check(run_log: dict) -> tuple[bool, str]:
    status = run_log.get("status")
    desc = run_log.get("description", "") or ""
    if status != "PASS":
        return False, f"agent status was {status!r}, not PASS"
    if not _Y_OPENAI.search(desc):
        return False, f"missing OpenAI's year (2015): {desc!r}"
    if not _Y_ANTHROPIC.search(desc):
        return False, f"missing Anthropic's year (2021): {desc!r}"
    if not _EARLIER.search(desc):
        return False, (
            f"description must state that OpenAI was founded first / "
            f"earlier / before Anthropic. Got: {desc!r}"
        )
    return True, "both years + correct earlier-founder cited"
