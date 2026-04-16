"""Detect click targets whose label implies an on-chain write action.

If a click hits a button whose label contains one of these words, the
agent is about to initiate a transaction. The main loop uses the return
value to arm a one-shot post-verification nudge before the next
`done PASS` is accepted.
"""

import re

TX_TRIGGER_WORDS = (
    "supply", "borrow", "repay", "withdraw", "swap", "stake", "unstake",
    "send", "deposit", "claim", "mint", "bridge", "approve", "sign",
    "confirm", "execute", "transfer",
)


def is_tx_trigger(element_label: str | None) -> str | None:
    """Return the matched trigger word, or None."""
    if not element_label:
        return None
    low = element_label.lower()
    for kw in TX_TRIGGER_WORDS:
        if re.search(rf"\b{kw}\b", low):
            return kw
    return None
