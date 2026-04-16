"""MetaMask popup recognition."""

# RU + EN keywords that mark a MetaMask popup as *actionable*
# (user has to press something). Used to discriminate a real approval
# popup from an empty/transitional MM page.
MM_ACTION_KEYWORDS = [
    "Разблокировать", "Unlock", "Подключить", "Connect",
    "Подтвердить", "Confirm", "Approve", "Sign",
    "Отмена", "Cancel", "Далее", "Next",
    "хочет", "wants to",
]


def has_mm_action(body_text: str) -> bool:
    """True if the popup body contains any actionable keyword."""
    return any(kw in body_text for kw in MM_ACTION_KEYWORDS)
