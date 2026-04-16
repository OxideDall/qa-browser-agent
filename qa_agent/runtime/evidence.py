"""Evidence gate for `done PASS` descriptions.

The agent's `done PASS` reason must be anchored in something the dApp /
page actually rendered. We accept, in priority order:

  1. An **inner-quoted string** of >=5 chars, e.g. `'toast: "Supply OK"'`.
  2. A **0x hex fragment** of >=6 chars — tx hashes, addresses.
  3. A **number + unit** pair: crypto tickers, currency symbols, temperature.
  4. A **plausible 4-digit year** (1800–2099) — concrete citation common
     in research tasks ("founded in 2021", "since 1995").
  5. A **multi-word proper noun** (2–4 capitalized words in a row) —
     names like "Dario Amodei", "New York University".
  6. Two or more `"<digit> <noun>"` anchors in one description, e.g.
     `"2 items left | 3 total"` — pages with counter / state UI.
  7. **Narrative fallback**: 4+ distinct "content words" (≥3 chars) that
     aren't in a small banned-hedge-word list. Catches descriptions like
     `"Welcome aboard! Your TestSite account has been created"` which
     have no anchor regex but cite real UI prose.

Everything else is considered generic success-fluff ("completed",
"works") and fails the gate.
"""

import re

EVIDENCE_QUOTE = re.compile(r'["\'][^"\']{5,}["\']')
EVIDENCE_TXHASH = re.compile(r"0x[a-fA-F0-9]{6,}")
EVIDENCE_UNIT = re.compile(
    # crypto tickers
    r"\d+(?:[.,]\d+)?\s*(?:ETH|WETH|stETH|sETH|USDC|USDT|DAI|BNB|MATIC|POL|"
    r"SOL|BTC|wBTC|ARB|OP|BASE|ST(?:ETH|MATIC)|ATOM|ADA|DOGE|LINK|UNI|AAVE|"
    r"CRV|COMP|LDO|RPL|SHIB|PEPE|TON|XRP|NFT)\b"
    # currency symbols
    r"|[\$€£¥₽₴₺]\s?\d+(?:[.,]\d+)?"
    r"|\d+(?:[.,]\d+)?\s?[\$€£¥₽₴₺]"
    r"|\d+(?:[.,]\d+)?\s*(?:руб(?:\.|ля|лей|ль)?|eur|usd|gbp)\b"
    # temperatures
    r"|[-−+]?\s?\d+(?:[.,]\d+)?\s*(?:°\s*[CFК]|градус(?:а|ов)?|deg(?:rees)?)\b"
    # bare "+N" / "-N" temperatures (weather widgets that omit °C)
    r"|[-−+]\s?\d{1,3}(?!\S)",
    re.IGNORECASE,
)
EVIDENCE_NUM_NOUN = re.compile(
    r"\d+\s+[A-Za-zА-Яа-я][A-Za-zА-Яа-я-]{2,}",
)
EVIDENCE_YEAR = re.compile(r"\b(?:1[89]\d{2}|20\d{2})\b")
# Two or more capitalized words in a row (Latin or Cyrillic) — proper nouns
# like "Dario Amodei", "Kaspersky Lab", "Сан-Франциско" are strong anchors
# for research-style answers that don't contain quotes or numbers.
EVIDENCE_PROPER_NOUN = re.compile(
    r"\b[A-ZА-ЯЁ][a-zа-яё]{2,}"
    r"(?:\s+[A-ZА-ЯЁ][a-zа-яё]{2,}){1,3}\b"
)

# Narrative-fallback constants (rule 7 in the module docstring).
_WORD_RE = re.compile(r"\b[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё-]{2,}\b")
# Tokens that indicate "success" but cite nothing specific. If a description
# consists mostly of these, it fails the gate. Kept tight on purpose — we
# want to reject pure fluff, not every hedge word in the language.
_HEDGE_WORDS = frozenset([
    # English generics
    "success", "successful", "successfully", "complete", "completed",
    "completion", "completing", "done", "works", "worked", "working",
    "okay", "fine", "finished", "passed", "achieved", "accomplished",
    # English weak-signal fillers (common in LLM descriptions)
    "task", "action", "result", "seems", "appears", "probably",
    "maybe", "likely",
    # Russian
    "успех", "успешно", "успешный", "готово", "завершено", "завершён",
    "работает", "выполнено", "выполнил", "кажется", "возможно",
    "вероятно",
])


def _content_words_count(description: str) -> int:
    """Distinct ≥3-char tokens that aren't hedge-fluff."""
    words = set()
    for m in _WORD_RE.findall(description.lower()):
        if m not in _HEDGE_WORDS:
            words.add(m)
    return len(words)


def has_evidence(description: str) -> bool:
    if not description:
        return False
    if EVIDENCE_QUOTE.search(description):
        return True
    if EVIDENCE_TXHASH.search(description):
        return True
    if EVIDENCE_UNIT.search(description):
        return True
    if EVIDENCE_YEAR.search(description):
        return True
    if EVIDENCE_PROPER_NOUN.search(description):
        return True
    # Two or more "<N> <noun>" hits anchor the claim in rendered numbers.
    if len(EVIDENCE_NUM_NOUN.findall(description)) >= 2:
        return True
    # Narrative fallback: real prose cites real UI.
    return _content_words_count(description) >= 4
