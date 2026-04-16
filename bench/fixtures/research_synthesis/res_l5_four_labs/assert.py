"""Require:
- all 4 founding years (2010, 2015, 2019, 2021)
- ascending order: DeepMind → OpenAI → Stability → Anthropic
- UK marker for DeepMind AND Stability (both HQ'd in London)

Ground truth:
  DeepMind     2010 London UK
  OpenAI       2015 San Francisco USA
  Stability AI 2019 London UK
  Anthropic    2021 San Francisco USA
"""

from __future__ import annotations

import re


_YEARS = [re.compile(r"\b" + y + r"\b") for y in ("2010", "2015", "2019", "2021")]

_ORDER = re.compile(
    r"\bDeepMind\b[^.]{0,120}\bOpenAI\b[^.]{0,120}\bStability\b[^.]{0,120}\bAnthropic\b",
    re.IGNORECASE,
)

_UK = re.compile(
    r"\b(UK|United\s+Kingdom|Britain|England|London)\b",
    re.IGNORECASE,
)

# Names of the two UK labs must both appear somewhere in a "UK labs" clause,
# but to be forgiving we just check each is mentioned together with a UK mark.
_DEEPMIND_UK = re.compile(
    r"\bDeepMind\b[^.]{0,60}\b(UK|United\s+Kingdom|London|Britain|England)\b"
    r"|\b(UK|United\s+Kingdom|London|Britain|England)\b[^.]{0,60}\bDeepMind\b",
    re.IGNORECASE,
)
_STABILITY_UK = re.compile(
    r"\bStability(?:\s+AI)?\b[^.]{0,60}\b(UK|United\s+Kingdom|London|Britain|England)\b"
    r"|\b(UK|United\s+Kingdom|London|Britain|England)\b[^.]{0,60}\bStability(?:\s+AI)?\b",
    re.IGNORECASE,
)


def check(run_log: dict) -> tuple[bool, str]:
    status = run_log.get("status")
    desc = run_log.get("description", "") or ""
    if status != "PASS":
        return False, f"agent status was {status!r}, not PASS"
    for rx in _YEARS:
        if not rx.search(desc):
            return False, f"missing year pattern {rx.pattern!r}: {desc!r}"
    if not _UK.search(desc):
        return False, f"no UK marker found anywhere in description: {desc!r}"
    if not _ORDER.search(desc):
        return False, (
            f"labs must be listed in ascending order "
            f"(DeepMind → OpenAI → Stability → Anthropic): {desc!r}"
        )
    if not _DEEPMIND_UK.search(desc):
        return False, f"DeepMind must be linked to UK in description: {desc!r}"
    if not _STABILITY_UK.search(desc):
        return False, (
            f"Stability AI must be linked to UK in description: {desc!r}"
        )
    return True, "4 years + order + DeepMind/Stability UK all cited"
