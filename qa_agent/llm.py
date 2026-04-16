"""Backwards-compatible `ask_llm` — dispatches to qa_agent.providers.

Kept as a named helper so the callers in `runtime/*` don't need to
import from providers directly. The `access_token` parameter is
accepted for signature compatibility but no longer used — each
provider handles its own auth via env vars.
"""

from __future__ import annotations

from .providers import get_provider


def ask_llm(access_token: str, messages: list[dict], system: str,
            image_b64: str | None = None,
            model: str | None = None,
            max_tokens: int | None = None) -> tuple[str, int, int]:
    """Send a chat completion request to the configured LLM provider.

    Returns (text, input_tokens, output_tokens). Raises
    `providers.LLMError` on failure — callers that want to retry on 401
    can still detect the `"401"` / `"403"` substring in the message.

    `access_token` is ignored; provider auth comes from env.
    """
    del access_token  # unused
    return get_provider().chat(
        messages, system, image_b64=image_b64,
        model=model, max_tokens=max_tokens,
    )
