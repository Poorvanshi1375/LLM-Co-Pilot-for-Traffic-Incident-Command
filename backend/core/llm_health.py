"""
LLM Health — verifies every configured Groq / Gemini key with a tiny call.
Runs once at startup (in the background) and on demand; /health reports the
cached result so operators can see bad keys without reading server logs.
Keys are never returned — only their position in the pool.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from core.key_manager import groq_keys, gemini_keys
from core.llm import GROQ_MODEL, GEMINI_MODEL, groq_client, gemini_client

_status: dict = {"checked_at": None, "groq": {"status": "unchecked"}, "gemini": {"status": "unchecked"}}


def _summarize(results: list[dict]) -> dict:
    if not results:
        return {"status": "no_keys", "keys": 0, "ok": 0, "failures": []}
    ok = sum(1 for r in results if r["ok"])
    return {
        "status": "ok" if ok == len(results) else ("degraded" if ok else "failing"),
        "keys": len(results),
        "ok": ok,
        "failures": [{"key_index": r["index"], "error": r["error"]} for r in results if not r["ok"]],
    }


def _check_groq_key(key: str) -> None:
    groq_client(key).chat.completions.create(
        model=GROQ_MODEL,
        messages=[{"role": "user", "content": "ping"}],
        max_tokens=1,
    )


def _check_gemini_key(key: str) -> None:
    gemini_client(key).models.get(model=GEMINI_MODEL)


async def _check_pool(keys: list[str], check) -> list[dict]:
    async def one(i: int, key: str) -> dict:
        try:
            await asyncio.wait_for(asyncio.to_thread(check, key), timeout=15)
            return {"index": i, "ok": True, "error": ""}
        except Exception as e:  # noqa: BLE001 — report any provider error
            return {"index": i, "ok": False, "error": f"{type(e).__name__}: {str(e)[:160]}"}

    return list(await asyncio.gather(*(one(i, k) for i, k in enumerate(keys))))


async def check_llms() -> dict:
    """Test every key and cache the summary."""
    groq_results, gemini_results = await asyncio.gather(
        _check_pool(groq_keys(), _check_groq_key),
        _check_pool(gemini_keys(), _check_gemini_key),
    )
    _status["groq"] = {"model": GROQ_MODEL, **_summarize(groq_results)}
    _status["gemini"] = {"model": GEMINI_MODEL, **_summarize(gemini_results)}
    _status["checked_at"] = datetime.now(timezone.utc).isoformat()
    for provider in ("groq", "gemini"):
        s = _status[provider]
        print(f"LLM check {provider}: {s['status']} ({s.get('ok', 0)}/{s.get('keys', 0)} keys ok)")
    return _status


def get_status() -> dict:
    return _status
