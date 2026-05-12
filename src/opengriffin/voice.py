"""Voice round-trip: Telegram .ogg -> faster-whisper STT -> ... -> edge-tts -> Telegram .ogg.

The whisper model is loaded lazily on first use (downloads ~150MB).
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import tempfile
from pathlib import Path

log = logging.getLogger("opengriffin.voice")

_WHISPER = None  # lazy
_WHISPER_MODEL = "small"  # small balances speed and accuracy on M-series
TTS_VOICE = "en-US-AvaNeural"  # matches user's preferred voice


def _ensure_whisper():
    global _WHISPER
    if _WHISPER is None:
        from faster_whisper import WhisperModel

        log.info("Loading faster-whisper model %s…", _WHISPER_MODEL)
        _WHISPER = WhisperModel(_WHISPER_MODEL, device="cpu", compute_type="int8")
    return _WHISPER


def _ogg_to_wav(ogg_path: Path) -> Path:
    wav = ogg_path.with_suffix(".wav")
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(ogg_path), "-ar", "16000", "-ac", "1", str(wav)],
        check=True,
        capture_output=True,
    )
    return wav


async def transcribe_ogg(ogg_bytes: bytes) -> str:
    """Run STT in a thread to keep the asyncio loop responsive."""

    def _work() -> str:
        with tempfile.TemporaryDirectory() as td:
            ogg_path = Path(td) / "in.ogg"
            ogg_path.write_bytes(ogg_bytes)
            wav = _ogg_to_wav(ogg_path)
            model = _ensure_whisper()
            segments, info = model.transcribe(str(wav), beam_size=1)
            return " ".join(s.text.strip() for s in segments).strip()

    return await asyncio.to_thread(_work)


async def synthesize_ogg(text: str, voice: str | None = None) -> bytes:
    """Use edge-tts to render text to MP3, then convert to OGG/Opus for Telegram voice."""
    import edge_tts

    voice = voice or TTS_VOICE
    with tempfile.TemporaryDirectory() as td:
        mp3_path = Path(td) / "out.mp3"
        ogg_path = Path(td) / "out.ogg"
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(str(mp3_path))
        # Convert to telegram-friendly OGG/Opus.
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(mp3_path),
                "-c:a",
                "libopus",
                "-b:a",
                "48k",
                str(ogg_path),
            ],
            check=True,
            capture_output=True,
        )
        return ogg_path.read_bytes()
