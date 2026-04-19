"""OpenAI TTS (gpt-4o-mini-tts) with filesystem cache.

Cache strategy:
- Path: {AUDIO_CACHE_DIR}/{report_id}.mp3
- Hit: file exists AND size > 0  -> return path (no API call)
- Miss: call OpenAI, write to .tmp, os.replace to final (atomic)

Concurrency:
- Atomic rename prevents partial-file reads.
- Duplicate concurrent requests may each call OpenAI once; last writer wins.
  Acceptable: < 1s race window, cost ~ $0.03 in worst case. No process-wide lock
  to keep scope minimal.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from openai import OpenAI, OpenAIError

from config import get_settings
from models import Report

logger = logging.getLogger(__name__)


class TTSUnavailable(RuntimeError):
    """Raised when OpenAI TTS cannot produce audio (config/API errors)."""


def _cache_dir() -> Path:
    cfg = get_settings()
    p = Path(cfg.AUDIO_CACHE_DIR)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _cache_path(report_id: int) -> Path:
    return _cache_dir() / f"{report_id}.mp3"


def synthesize_to_file(report: Report) -> Path:
    """Return an mp3 Path for this report's radio_script.

    Raises:
        TTSUnavailable: missing API key, empty script, or OpenAI error.
    """
    cfg = get_settings()
    if not cfg.OPENAI_API_KEY:
        raise TTSUnavailable("OPENAI_API_KEY not set")

    script = (report.radio_script or "").strip()
    if not script:
        raise TTSUnavailable("radio_script is empty")

    path = _cache_path(report.id)
    if path.exists() and path.stat().st_size > 0:
        logger.info("tts cache hit report_id=%s", report.id)
        return path

    client = OpenAI(api_key=cfg.OPENAI_API_KEY)
    try:
        response = client.audio.speech.create(
            model=cfg.OPENAI_TTS_MODEL,   # "gpt-4o-mini-tts"
            voice=cfg.OPENAI_TTS_VOICE,   # "nova"
            input=script,
            response_format="mp3",
        )
    except OpenAIError as exc:
        logger.exception("openai tts failed report_id=%s", report.id)
        raise TTSUnavailable(f"openai error: {exc}") from exc

    tmp = path.with_suffix(".mp3.tmp")
    try:
        # openai>=1.55.0 exposes write_to_file on the streamed response.
        response.write_to_file(str(tmp))
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise

    logger.info(
        "tts cache miss -> wrote report_id=%s bytes=%s", report.id, path.stat().st_size
    )
    return path
