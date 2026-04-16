"""Oscillation detection in an action history.

The agent sometimes gets stuck flipping between two actions (open modal →
close modal → open modal → ...). We detect this as an ABAB... pattern over
an even window in the tail of the history.

Parameters:
  - `window=4` — soft detection (3rd ABAB hit); triggers a forced vision
    re-dispatch in the main loop.
  - `window=6` — hard detection (ABABAB); triggers a forced FAIL.
"""


def is_oscillating(history: list[str], window: int) -> bool:
    """ABAB... of exactly two distinct actions in the last `window` entries."""
    if len(history) < window or window < 4 or window % 2:
        return False
    tail = history[-window:]
    a, b = tail[0], tail[1]
    if a == b:
        return False
    return (all(tail[i] == a for i in range(0, window, 2)) and
            all(tail[i] == b for i in range(1, window, 2)))
