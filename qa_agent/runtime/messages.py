"""Canned messages the agent loop injects back into the LLM conversation."""

# Sent when a `done PASS` is rejected because the description has no
# concrete evidence. Shared between the main dispatch and the vision
# re-dispatch so they speak with one voice.
DONE_REASK_MSG = (
    "REJECTED: `done PASS` requires CONCRETE evidence in its description. "
    "Quote the exact UI text you saw in inner quotes (e.g. "
    "`done PASS 'toast: \"Supply successful\"'`), OR cite a transaction "
    "hash like `0xabc123...`. Generic words like 'successful', "
    "'completed', 'done', 'works' WITHOUT a quoted source are NOT "
    "accepted. Use `look` to observe the real UI state, then retry "
    "`done PASS` with real evidence quoted, or call `done FAIL` if the "
    "action did not actually complete."
)
