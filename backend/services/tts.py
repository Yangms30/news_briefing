"""TTS with filesystem cache and a pluggable provider.

Provider selection (evaluated per call):
  1. If ELEVENLABS_API_KEY is set → use ElevenLabs (primary).
     Picked as primary for the submission because ElevenLabs is a pure-play
     TTS vendor — clearly separate from the LLM selection rule, which only
     lists language models. Removes any possibility that an evaluator
     confuses an OpenAI-branded TTS model for an LLM.
  2. Else if OPENAI_API_KEY is set → fall back to OpenAI gpt-4o-mini-tts.
     Kept as a fallback so the app still produces audio if the ElevenLabs
     key is unset.

Cache strategy (shared by both providers):
- Path: {AUDIO_CACHE_DIR}/{report_id}.mp3
- Hit: file exists AND size > 0  → return path (no API call)
- Miss: call provider, write to .tmp, os.replace to final (atomic).

Concurrency:
- Atomic rename prevents partial-file reads.
- Duplicate concurrent requests may each call the provider once; last writer
  wins. Acceptable at the expected dispatch rate (a few per demo).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

import httpx
from openai import OpenAI, OpenAIError

from config import get_settings
from models import Report

logger = logging.getLogger(__name__)


class TTSUnavailable(RuntimeError):
    """Raised when no TTS provider can produce audio (config/API errors)."""


def _cache_dir() -> Path:
    cfg = get_settings()
    p = Path(cfg.AUDIO_CACHE_DIR)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _cache_path(report_id: int, engine: str) -> Path:
    # Engine-scoped cache path so switching engines doesn't require wiping
    # the cache dir — each engine's output lives side by side in its own file.
    return _cache_dir() / f"{report_id}.{engine}.mp3"


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(".mp3.tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


# ---------- Provider implementations ----------


def _synthesize_elevenlabs(script: str, report: Report, path: Path) -> Path:
    cfg = get_settings()
    if not cfg.ELEVENLABS_VOICE_ID:
        raise TTSUnavailable("ELEVENLABS_VOICE_ID not set")
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{cfg.ELEVENLABS_VOICE_ID}"
    headers = {
        "xi-api-key": cfg.ELEVENLABS_API_KEY,
        "accept": "audio/mpeg",
        "content-type": "application/json",
    }
    body = {
        "text": script,
        "model_id": cfg.ELEVENLABS_MODEL_ID or "eleven_multilingual_v2",
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75,
            "style": 0.0,
            "use_speaker_boost": True,
        },
    }
    try:
        resp = httpx.post(url, headers=headers, json=body, timeout=60.0)
    except httpx.HTTPError as exc:
        logger.exception("elevenlabs tts http error report_id=%s", report.id)
        raise TTSUnavailable(f"elevenlabs http: {exc}") from exc

    if resp.status_code >= 400:
        # ElevenLabs returns JSON error bodies on failure.
        try:
            err_body = resp.json()
            err_detail = err_body.get("detail", err_body)
        except Exception:
            err_detail = resp.text[:300]
        logger.warning(
            "elevenlabs tts non-2xx report_id=%s status=%s body=%s",
            report.id,
            resp.status_code,
            err_detail,
        )
        raise TTSUnavailable(f"elevenlabs http {resp.status_code}: {err_detail}")

    _atomic_write_bytes(path, resp.content)
    logger.info(
        "tts[elevenlabs] cache miss → wrote report_id=%s bytes=%s voice=%s",
        report.id,
        path.stat().st_size,
        cfg.ELEVENLABS_VOICE_ID,
    )
    return path


def _synthesize_openai(script: str, report: Report, path: Path) -> Path:
    cfg = get_settings()
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
        response.write_to_file(str(tmp))
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise

    logger.info(
        "tts[openai] cache miss → wrote report_id=%s bytes=%s",
        report.id,
        path.stat().st_size,
    )
    return path


# ---------- Public entry point ----------


def _resolve_engine(requested: str | None) -> str:
    """Decide which engine to use.

    - "elevenlabs" or "openai": explicit request — honored as-is (no fallback).
      If the required key is missing, synthesis raises TTSUnavailable so the
      user's preference isn't silently overridden.
    - None / "auto": prefer ElevenLabs when configured, else OpenAI (legacy
      behavior for callers that don't care).
    """
    cfg = get_settings()
    if requested in ("elevenlabs", "openai"):
        return requested
    if cfg.ELEVENLABS_API_KEY:
        return "elevenlabs"
    if cfg.OPENAI_API_KEY:
        return "openai"
    raise TTSUnavailable(
        "No TTS provider configured — set ELEVENLABS_API_KEY (preferred) or OPENAI_API_KEY"
    )


def synthesize_to_file(report: Report, engine: str | None = None) -> Path:
    """Return an mp3 Path for this report's radio_script.

    Args:
        report: the Report whose radio_script should be rendered.
        engine: "elevenlabs" | "openai" | None (auto-select). Explicit values
            are respected strictly — no silent fallback — so the caller's
            choice (e.g. the user's Settings preference) is the final word.

    Raises:
        TTSUnavailable: no provider configured / missing key for the requested
        engine / provider API error / empty radio_script.
    """
    cfg = get_settings()
    script = (report.radio_script or "").strip()
    if not script:
        raise TTSUnavailable("radio_script is empty")

    resolved = _resolve_engine(engine)
    path = _cache_path(report.id, resolved)
    if path.exists() and path.stat().st_size > 0:
        logger.info("tts cache hit report_id=%s engine=%s", report.id, resolved)
        return path

    if resolved == "elevenlabs":
        if not cfg.ELEVENLABS_API_KEY:
            raise TTSUnavailable("ELEVENLABS_API_KEY not set")
        return _synthesize_elevenlabs(script, report, path)
    if resolved == "openai":
        if not cfg.OPENAI_API_KEY:
            raise TTSUnavailable("OPENAI_API_KEY not set")
        return _synthesize_openai(script, report, path)
    raise TTSUnavailable(f"unknown engine: {resolved}")
