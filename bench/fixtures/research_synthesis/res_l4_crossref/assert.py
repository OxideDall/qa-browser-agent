"""Require all three founding years + ascending order + DeepMind as oldest.

DeepMind (2010, London) < OpenAI (Dec 2015, San Francisco) < Anthropic
(Jan 2021, San Francisco).
"""

from __future__ import annotations

import re


_Y_DM  = re.compile(r"\b2010\b")
_Y_OAI = re.compile(r"\b2015\b")
_Y_AN  = re.compile(r"\b2021\b")

# "DeepMind, OpenAI, Anthropic" in that order, flexible separators.
_ORDER = re.compile(
    r"\bDeepMind\b[^.]{0,80}\bOpenAI\b[^.]{0,80}\bAnthropic\b",
    re.IGNORECASE,
)

_OLDEST_MARK = re.compile(
    r"\b(?:oldest|earliest|first|earlier|ранее|старше)\b",
    re.IGNORECASE,
)


def check(run_log: dict) -> tuple[bool, str]:
    status = run_log.get("status")
    desc = run_log.get("description", "") or ""
    if status != "PASS":
        return False, f"agent status was {status!r}, not PASS"
    if not _Y_DM.search(desc):
        return False, f"missing DeepMind's year (2010): {desc!r}"
    if not _Y_OAI.search(desc):
        return False, f"missing OpenAI's year (2015): {desc!r}"
    if not _Y_AN.search(desc):
        return False, f"missing Anthropic's year (2021): {desc!r}"
    if not _ORDER.search(desc):
        return False, (
            f"description must list the labs in ascending order "
            f"(DeepMind, OpenAI, Anthropic). Got: {desc!r}"
        )
    if not _OLDEST_MARK.search(desc):
        return False, (
            f"description must mark DeepMind as the oldest/earliest/first. "
            f"Got: {desc!r}"
        )
    return True, "all three years + ascending order + oldest mark cited"
