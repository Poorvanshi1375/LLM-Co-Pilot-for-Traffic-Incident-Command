"""
Speech-to-text via Groq Whisper API.
Uses the existing key rotation infrastructure.
"""
from __future__ import annotations

import asyncio
import tempfile
import os
from typing import Optional

from groq import Groq
from core.key_manager import get_groq_key


async def transcribe_audio(audio_bytes: bytes, filename: str = "audio.webm") -> dict:
    """
    Transcribe audio bytes using Groq Whisper.
    Returns {"text": "...", "status": "ok"} or {"text": "", "status": "error", "reason": "..."}.
    """
    try:
        client = Groq(api_key=get_groq_key())

        # Determine file extension for Groq
        ext = os.path.splitext(filename)[1] or ".webm"
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        try:
            with open(tmp_path, "rb") as audio_file:
                transcription = await asyncio.to_thread(
                    client.audio.transcriptions.create,
                    file=(filename, audio_file),
                    model="whisper-large-v3-turbo",
                    language="en",
                    response_format="text",
                )
            text = str(transcription).strip()
            return {"text": text, "status": "ok"}
        finally:
            os.unlink(tmp_path)

    except Exception as e:
        return {"text": "", "status": "error", "reason": str(e)}
