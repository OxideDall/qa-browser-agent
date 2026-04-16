"""LLM provider abstraction.

Select one via `LLM_PROVIDER` env (default: `anthropic`):

  anthropic   — official Anthropic API. Requires `ANTHROPIC_API_KEY`.
  openrouter  — OpenRouter gateway to many models. Requires
                `OPENROUTER_API_KEY` and (optionally) `LLM_MODEL`
                (default: `anthropic/claude-3.5-haiku`).

Extra env overrides that work for every provider:
  LLM_MODEL       — model id string (provider-specific)
  LLM_MAX_TOKENS  — int, default 1024

All providers expose the same contract:

    provider.chat(messages, system, image_b64=None,
                  model=None, max_tokens=None)
        -> (text: str, input_tokens: int, output_tokens: int)

`image_b64` is a raw base64-encoded JPEG. Providers each translate it
into their wire format (Anthropic `{type:image, source:base64}` vs.
OpenAI-style `{type:image_url, image_url:{url: "data:image/jpeg;..."}}`).

Model requirements:
  The agent's `look` action needs a vision-capable model.  All the
  defaults below qualify. If you swap to a text-only model, disable
  `look` in the system prompt or expect vision cycles to fail.
"""

from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request


class LLMError(RuntimeError):
    """Raised for any provider-level failure (network, auth, malformed)."""


def _ssl_ctx() -> ssl.SSLContext:
    return ssl.create_default_context()


def _http_post_json(url: str, headers: dict, body: dict,
                    *, timeout: float = 60.0) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers=headers, method="POST",
    )
    try:
        with urllib.request.urlopen(req, context=_ssl_ctx(), timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        err = ""
        try:
            err = e.read().decode()
        except Exception:
            pass
        raise LLMError(f"HTTP {e.code}: {err}") from e


def _inject_image_anthropic(messages: list[dict], image_b64: str | None) -> list[dict]:
    """Anthropic vision wire format — image block first, then text."""
    msgs = [dict(m) for m in messages]
    if not image_b64:
        return msgs
    for i in range(len(msgs) - 1, -1, -1):
        if msgs[i]["role"] == "user":
            text_content = msgs[i]["content"]
            msgs[i]["content"] = [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": image_b64,
                    },
                },
                {"type": "text", "text": text_content},
            ]
            break
    return msgs


def _inject_image_openai(messages: list[dict], image_b64: str | None) -> list[dict]:
    """OpenAI-compatible vision wire format — `image_url` part with data-URL."""
    msgs = [dict(m) for m in messages]
    if not image_b64:
        return msgs
    for i in range(len(msgs) - 1, -1, -1):
        if msgs[i]["role"] == "user":
            text_content = msgs[i]["content"]
            msgs[i]["content"] = [
                {"type": "text", "text": text_content},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{image_b64}",
                    },
                },
            ]
            break
    return msgs


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------

class AnthropicProvider:
    """Anthropic Messages API. Single required env: `ANTHROPIC_API_KEY`."""

    def __init__(self, model: str | None = None, max_tokens: int | None = None):
        self.api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not self.api_key:
            raise LLMError(
                "ANTHROPIC_API_KEY not set — export it, or choose another "
                "provider via LLM_PROVIDER=openrouter"
            )
        self.model = model or os.environ.get("LLM_MODEL", "claude-haiku-4-5")
        self.max_tokens = max_tokens or int(
            os.environ.get("LLM_MAX_TOKENS", "1024")
        )
        self.url = "https://api.anthropic.com/v1/messages"
        self.version = "2023-06-01"

    def chat(self, messages: list[dict], system: str,
             image_b64: str | None = None,
             model: str | None = None,
             max_tokens: int | None = None) -> tuple[str, int, int]:
        msgs = _inject_image_anthropic(messages, image_b64)
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": self.version,
            "Content-Type": "application/json",
        }
        body = {
            "model": model or self.model,
            "max_tokens": max_tokens or self.max_tokens,
            "temperature": 0.0,
            "system": system,
            "messages": msgs,
        }
        data = _http_post_json(self.url, headers, body)
        text = "".join(
            b.get("text", "") for b in data.get("content", [])
            if b.get("type") == "text"
        )
        u = data.get("usage", {})
        return text, u.get("input_tokens", 0), u.get("output_tokens", 0)


class OpenRouterProvider:
    """OpenRouter — any model, uniform OpenAI-style endpoint.

    Required env: `OPENROUTER_API_KEY`.
    Optional env: `LLM_MODEL` (e.g. `anthropic/claude-3.5-haiku`,
    `openai/gpt-4o-mini`, `google/gemini-2.0-flash-001`).
    """

    def __init__(self, model: str | None = None, max_tokens: int | None = None):
        self.api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
        if not self.api_key:
            raise LLMError(
                "OPENROUTER_API_KEY not set — export it, or choose another "
                "provider via LLM_PROVIDER=anthropic"
            )
        self.model = model or os.environ.get(
            "LLM_MODEL", "anthropic/claude-3.5-haiku",
        )
        self.max_tokens = max_tokens or int(
            os.environ.get("LLM_MAX_TOKENS", "1024")
        )
        self.url = "https://openrouter.ai/api/v1/chat/completions"

    def chat(self, messages: list[dict], system: str,
             image_b64: str | None = None,
             model: str | None = None,
             max_tokens: int | None = None) -> tuple[str, int, int]:
        msgs: list[dict] = [{"role": "system", "content": system}] + [
            dict(m) for m in messages
        ]
        msgs = _inject_image_openai(msgs, image_b64)
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            # These two are recommended by OpenRouter for app identification.
            "HTTP-Referer": os.environ.get(
                "OPENROUTER_REFERER", "https://github.com/",
            ),
            "X-Title": os.environ.get("OPENROUTER_APP_TITLE", "qa-browser-agent"),
        }
        body = {
            "model": model or self.model,
            "max_tokens": max_tokens or self.max_tokens,
            "temperature": 0.0,
            "messages": msgs,
        }
        data = _http_post_json(self.url, headers, body)
        try:
            text = data["choices"][0]["message"].get("content", "") or ""
        except (KeyError, IndexError, TypeError) as e:
            raise LLMError(f"unexpected OpenRouter response: {data!r}") from e
        u = data.get("usage", {})
        return text, u.get("prompt_tokens", 0), u.get("completion_tokens", 0)


# ---------------------------------------------------------------------------
# Factory — cached singleton per process.
# ---------------------------------------------------------------------------

_PROVIDER: "AnthropicProvider | OpenRouterProvider | None" = None


def get_provider():
    global _PROVIDER
    if _PROVIDER is not None:
        return _PROVIDER
    kind = os.environ.get("LLM_PROVIDER", "anthropic").strip().lower()
    if kind == "anthropic":
        _PROVIDER = AnthropicProvider()
    elif kind == "openrouter":
        _PROVIDER = OpenRouterProvider()
    elif kind == "subscription":
        # Lazy-import from the gitignored qa_agent/oauth/ package.
        try:
            from .oauth import SubscriptionProvider
        except ImportError:
            raise LLMError(
                "LLM_PROVIDER=subscription requires the qa_agent/oauth/ "
                "package which is not included in the public distribution. "
                "Use LLM_PROVIDER=anthropic or =openrouter instead."
            ) from None
        _PROVIDER = SubscriptionProvider()
    else:
        raise LLMError(
            f"unknown LLM_PROVIDER={kind!r}; use 'anthropic' or 'openrouter'"
        )
    return _PROVIDER


def reset_provider() -> None:
    """Re-read env on next get_provider(). Useful for tests."""
    global _PROVIDER
    _PROVIDER = None
