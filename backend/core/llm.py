"""
LLM — the single place agents call Groq and Gemini.
Every call gets a timeout, key failover (auth errors bench a key for 10 min,
rate limits for 1 min) and raises LLMError on failure so callers can fall back
and label their output as rule-based instead of silently passing it off as AI.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from functools import lru_cache

from google import genai
from google.genai import types
from groq import Groq

from core.key_manager import KeyPool, gemini_pool, groq_pool

# llama-3.3-70b-versatile was removed from Groq; gpt-oss-120b is the large general model there now
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_FALLBACK_MODEL = os.getenv("GROQ_FALLBACK_MODEL", "openai/gpt-oss-20b")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
# Gemini 2.5 counts thinking tokens against max_output_tokens; 0 turns thinking off
GEMINI_THINKING_BUDGET = int(os.getenv("GEMINI_THINKING_BUDGET", "0"))
LLM_TIMEOUT_S = float(os.getenv("LLM_TIMEOUT_S", "20"))
LLM_ATTEMPTS = 2

AUTH_COOLDOWN_S = 600
RATE_LIMIT_COOLDOWN_S = 60
DAILY_QUOTA_COOLDOWN_S = 3600  # e.g. Gemini free tier: 20 requests/day per model

# Most recent runtime failure per provider, cleared on success (shown by /health)
LAST_ERRORS: dict[str, dict] = {}


class LLMError(Exception):
    """An LLM call failed on every attempted key."""


@lru_cache(maxsize=32)
def groq_client(key: str) -> Groq:
    return Groq(api_key=key, timeout=LLM_TIMEOUT_S, max_retries=0)


@lru_cache(maxsize=32)
def gemini_client(key: str) -> genai.Client:
    return genai.Client(api_key=key, http_options=types.HttpOptions(timeout=int(LLM_TIMEOUT_S * 1000)))


def _status_code(e: Exception) -> int | None:
    for attr in ("status_code", "code"):
        value = getattr(e, attr, None)
        if isinstance(value, int):
            return value
    return None


def call_with_failover(pool: KeyPool, provider: str, fn):
    """Run fn(key) on up to LLM_ATTEMPTS keys, benching keys that fail."""
    if not len(pool):
        raise LLMError(f"{provider}: no API key configured")
    last: Exception | None = None
    for _ in range(min(LLM_ATTEMPTS, len(pool))):
        key = pool.next()
        try:
            result = fn(key)
            LAST_ERRORS.pop(provider, None)
            return result
        except Exception as e:  # noqa: BLE001 — any provider error triggers failover
            last = e
            status = _status_code(e)
            if status in (401, 403):
                pool.mark_failed(key, AUTH_COOLDOWN_S)
            elif status == 429:
                daily = "PerDay" in str(e)
                pool.mark_failed(key, DAILY_QUOTA_COOLDOWN_S if daily else RATE_LIMIT_COOLDOWN_S)
    message = f"{provider}: {type(last).__name__}: {str(last)[:200]}"
    LAST_ERRORS[provider] = {
        "at": datetime.now(timezone.utc).isoformat(),
        "status": _status_code(last) if last else None,
        "error": message,
    }
    raise LLMError(message)


async def groq_chat(
    messages: list[dict],
    *,
    max_tokens: int,
    temperature: float = 0.3,
    json_mode: bool = False,
) -> str:
    """Chat completion on Groq; returns the message text.

    Groq rate limits are per model (free tier: 8,000 tokens/minute each), so a
    429 on the main model retries once on GROQ_FALLBACK_MODEL before failing.
    """
    def extra_for(model: str) -> dict:
        extra: dict = {"response_format": {"type": "json_object"}} if json_mode else {}
        if model.startswith("openai/gpt-oss"):
            # Reasoning tokens count against max_tokens; low effort keeps answers fast and complete
            extra["reasoning_effort"] = "low"
        return extra

    models = [GROQ_MODEL] + ([GROQ_FALLBACK_MODEL] if GROQ_FALLBACK_MODEL and GROQ_FALLBACK_MODEL != GROQ_MODEL else [])

    def fn(key: str) -> str:
        for i, model in enumerate(models):
            try:
                response = groq_client(key).chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **extra_for(model),
                )
            except Exception as e:  # noqa: BLE001
                if _status_code(e) == 429 and i + 1 < len(models):
                    continue  # this model's per-minute budget is spent; try the next one
                raise
            content = response.choices[0].message.content
            if not content:
                raise LLMError("groq: empty response")
            return content
        raise LLMError("groq: no model available")

    return await asyncio.to_thread(call_with_failover, groq_pool(), "groq", fn)


async def gemini_generate(
    prompt: str | list,
    *,
    max_tokens: int,
    temperature: float = 0.3,
    system: str | None = None,
    json_mode: bool = False,
) -> str:
    """Single-turn Gemini generation (text, or a list of parts); returns the response text."""
    config = types.GenerateContentConfig(
        temperature=temperature,
        max_output_tokens=max_tokens,
        system_instruction=system,
        response_mime_type="application/json" if json_mode else None,
        thinking_config=types.ThinkingConfig(thinking_budget=GEMINI_THINKING_BUDGET),
        # No function tools are passed; turning AFC off also silences an SDK warning
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )

    def fn(key: str) -> str:
        response = gemini_client(key).models.generate_content(
            model=GEMINI_MODEL, contents=prompt, config=config,
        )
        text = response.text
        if not text:
            reason = response.candidates[0].finish_reason if response.candidates else "no candidates"
            raise LLMError(f"gemini: empty response ({reason})")
        return text

    return await asyncio.to_thread(call_with_failover, gemini_pool(), "gemini", fn)


async def generate(
    prompt: str,
    *,
    max_tokens: int,
    temperature: float = 0.3,
    system: str | None = None,
    json_mode: bool = False,
    prefer: str = "gemini",
) -> str:
    """Text generation with cross-provider fallback (Gemini <-> Groq).

    One provider being down or out of quota never takes an agent offline:
    the same prompt goes to the other provider before callers fall back to rules.
    """
    order = ("gemini", "groq") if prefer == "gemini" else ("groq", "gemini")
    errors = []
    for provider in order:
        try:
            if provider == "gemini":
                return await gemini_generate(
                    prompt, max_tokens=max_tokens, temperature=temperature, system=system, json_mode=json_mode,
                )
            messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
            return await groq_chat(messages, max_tokens=max_tokens, temperature=temperature, json_mode=json_mode)
        except LLMError as e:
            errors.append(str(e))
    raise LLMError(" | ".join(errors))


def extract_json(text: str) -> dict | list:
    """Parse JSON from a model response, tolerating surrounding prose or fences."""
    import json

    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    starts = [i for i in (text.find("{"), text.find("[")) if i >= 0]
    if not starts:
        raise LLMError("response contained no JSON")
    start = min(starts)
    end = max(text.rfind("}"), text.rfind("]")) + 1
    try:
        return json.loads(text[start:end])
    except json.JSONDecodeError as e:
        raise LLMError(f"invalid JSON in response: {e}") from e


def image_part(image_bytes: bytes, mime_type: str = "image/jpeg") -> types.Part:
    """Gemini content part for an image."""
    return types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
