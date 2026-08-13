"""Provider adapter — one file to swap the model behind the product.

DeepSeek is OpenAI-compatible, so this wraps the `openai` SDK pointed at their base URL.
Three deliberate behaviours:

**Non-streaming.** Streamed responses are `text/event-stream`, and this machine's network
filter blocks `text/` media types between 21:00–06:00. A streaming agent would work all
day and fail mysteriously at night.

**Disk cache.** Identical (model, messages, tools) returns the cached reply, so rehearsing
a demo costs nothing and runs instantly.

**Never fatal.** Any failure — missing key, rate limit, no network — raises `LLMUnavailable`,
which the agent catches to fall back to deterministic answers. A demo must not die on
hotel wifi.
"""

import hashlib
import json
import os
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "llm_cache")
TIMEOUT = 60


class LLMUnavailable(Exception):
    pass


def _key() -> Optional[str]:
    k = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not k:
        # Streamlit Cloud injects secrets through st.secrets, not the environment. Guarded
        # because agent.py runs as a plain CLI with no Streamlit runtime.
        try:
            import streamlit as st

            k = str(st.secrets.get("DEEPSEEK_API_KEY", "")).strip()
        except Exception:
            k = ""
    return k or None


def available() -> bool:
    return bool(_key()) and os.environ.get("INSIGHT_COPILOT_MOCK", "0") != "1"


def model_name() -> str:
    return os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")


def _cache_path(payload: dict) -> str:
    h = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:20]
    return os.path.join(CACHE_DIR, f"{h}.json")


def _client():
    from openai import OpenAI

    return OpenAI(
        api_key=_key(),
        base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    )


def chat(messages: list, tools: list = None, temperature: float = 0.2,
         use_cache: bool = True) -> dict:
    """Return {text, tool_calls, cached}. Raises LLMUnavailable on any failure."""
    if not available():
        raise LLMUnavailable("no API key, or mock mode forced")

    payload = {"model": model_name(), "messages": messages, "tools": tools,
               "temperature": temperature}
    path = _cache_path(payload)
    if use_cache and os.path.exists(path):
        try:
            with open(path) as f:
                hit = json.load(f)
            hit["cached"] = True
            return hit
        except (json.JSONDecodeError, OSError):
            pass

    try:
        kwargs = dict(model=model_name(), messages=messages, temperature=temperature,
                      stream=False, timeout=TIMEOUT)
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        resp = _client().chat.completions.create(**kwargs)
    except Exception as e:  # noqa: BLE001 — every failure degrades to the mock path
        raise LLMUnavailable(f"{type(e).__name__}: {e}") from e

    msg = resp.choices[0].message
    out = {
        "text": msg.content or "",
        "tool_calls": [
            {"id": tc.id, "name": tc.function.name, "arguments": tc.function.arguments}
            for tc in (msg.tool_calls or [])
        ],
        "cached": False,
    }

    if use_cache:
        os.makedirs(CACHE_DIR, exist_ok=True)
        try:
            with open(path, "w") as f:
                json.dump({k: out[k] for k in ("text", "tool_calls")}, f)
        except OSError:
            pass
    return out
