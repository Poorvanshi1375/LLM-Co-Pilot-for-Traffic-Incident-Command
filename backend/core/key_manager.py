"""
Key Manager — Thread-safe round-robin API key rotation with failover.
Parses comma-separated key lists from env vars and rotates on each call.
A key that fails with an auth or rate-limit error is benched for a cooldown
and skipped until it expires, so one dead key never takes an agent down.
"""
from __future__ import annotations

import os
import threading
import time


class KeyPool:
    """Thread-safe round-robin key pool that skips benched keys."""

    def __init__(self, primary_env: str, pool_env: str):
        self._lock = threading.Lock()
        primary = os.getenv(primary_env, "").strip()
        pool_csv = os.getenv(pool_env, "")
        pool_keys = [k.strip() for k in pool_csv.split(",") if k.strip()]
        # Primary first, then pool keys
        self._keys: list[str] = []
        if primary:
            self._keys.append(primary)
        for k in pool_keys:
            if k not in self._keys:
                self._keys.append(k)
        self._index = 0
        self._benched_until: dict[str, float] = {}

    def next(self) -> str:
        """Return the next usable key; if all are benched, the one freed soonest."""
        if not self._keys:
            return ""
        with self._lock:
            now = time.time()
            for _ in range(len(self._keys)):
                key = self._keys[self._index % len(self._keys)]
                self._index += 1
                if self._benched_until.get(key, 0) <= now:
                    return key
            return min(self._keys, key=lambda k: self._benched_until.get(k, 0))

    def mark_failed(self, key: str, cooldown_s: float):
        """Bench a key for cooldown_s seconds."""
        with self._lock:
            self._benched_until[key] = time.time() + cooldown_s

    def keys(self) -> list[str]:
        return list(self._keys)

    def __len__(self) -> int:
        return len(self._keys)


_groq_pool: KeyPool | None = None
_gemini_pool: KeyPool | None = None
_init_lock = threading.Lock()


def _ensure_init():
    global _groq_pool, _gemini_pool
    if _groq_pool is None:
        with _init_lock:
            if _groq_pool is None:
                _groq_pool = KeyPool("GROQ_API_KEY", "GROQ_API_KEYS")
                _gemini_pool = KeyPool("GOOGLE_AI_API_KEY", "GOOGLE_AI_API_KEYS")


def groq_pool() -> KeyPool:
    _ensure_init()
    assert _groq_pool is not None
    return _groq_pool


def gemini_pool() -> KeyPool:
    _ensure_init()
    assert _gemini_pool is not None
    return _gemini_pool


def get_groq_key() -> str:
    """Get next Groq API key (round-robin, skipping benched keys)."""
    return groq_pool().next()


def get_gemini_key() -> str:
    """Get next Gemini API key (round-robin, skipping benched keys)."""
    return gemini_pool().next()


def groq_keys() -> list[str]:
    return groq_pool().keys()


def gemini_keys() -> list[str]:
    return gemini_pool().keys()
