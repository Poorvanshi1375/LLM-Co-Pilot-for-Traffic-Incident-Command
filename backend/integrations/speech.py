"""
Speech-to-text via Groq Whisper API.
Uses the shared key pool with failover.
"""
from __future__ import annotations

import asyncio
import io
import os

from core.key_manager import groq_pool
from core.llm import call_with_failover, groq_client

WHISPER_MODEL = "whisper-large-v3-turbo"


async def transcribe_audio(audio_bytes: bytes, filename: str = "audio.webm") -> dict:
    """
    Transcribe audio bytes using Groq Whisper.
    Returns {"text": "...", "status": "ok"} or {"text": "", "status": "error", "reason": "..."}.
    """
    name = filename if os.path.splitext(filename)[1] else f"{filename}.webm"

    def fn(key: str) -> str:
        transcription = groq_client(key).audio.transcriptions.create(
            file=(name, io.BytesIO(audio_bytes)),
            model=WHISPER_MODEL,
            language="en",
            response_format="text",
        )
        return str(transcription).strip()

    try:
        text = await asyncio.to_thread(call_with_failover, groq_pool(), "groq", fn)
        return {"text": text, "status": "ok"}
    except Exception as e:
        return {"text": "", "status": "error", "reason": str(e)}
