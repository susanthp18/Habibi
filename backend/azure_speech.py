"""Azure Speech TTS + STT via REST — PS-4 / PS-5E.

Uses the regional cognitiveservices endpoints. No Speech SDK dependency —
httpx is already required. TTS and STT share AZURE_SPEECH_KEY / REGION.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import time
import xml.sax.saxutils
from pathlib import Path
from typing import Any

import httpx

from env_loader import load_env

logger = logging.getLogger(__name__)

_CACHE_DIR = Path(__file__).resolve().parent / ".cache" / "tts"
_MAX_TEXT_CHARS = 500
_DEFAULT_VOICE = "en-IN-NeerjaNeural"


class AzureSpeechConfigError(RuntimeError):
    pass


def _require(name: str) -> str:
    value = (os.getenv(name) or "").strip()
    if not value:
        raise AzureSpeechConfigError(f"Missing required env var: {name}")
    return value


def get_speech_key() -> str:
    load_env()
    return _require("AZURE_SPEECH_KEY")


def get_speech_region() -> str:
    load_env()
    return _require("AZURE_SPEECH_REGION")


def get_default_voice() -> str:
    load_env()
    return (os.getenv("AZURE_SPEECH_TTS_VOICE_DEFAULT") or _DEFAULT_VOICE).strip()


def _voice_map() -> dict[str, str]:
    """Optional AZURE_SPEECH_VOICE_MAP=priya:en-IN-NeerjaNeural,ravi:en-IN-PrabhatNeural"""
    load_env()
    raw = (os.getenv("AZURE_SPEECH_VOICE_MAP") or "").strip()
    out: dict[str, str] = {}
    if not raw:
        return out
    for part in raw.split(","):
        part = part.strip()
        if ":" not in part:
            continue
        k, v = part.split(":", 1)
        k, v = k.strip(), v.strip()
        if k and v:
            out[k] = v
    return out


def resolve_azure_voice_name(voice_id: str | None, *, db_azure_name: str | None = None) -> str:
    """Resolve studio voice id → Azure neural voice name."""
    if db_azure_name and str(db_azure_name).strip():
        return str(db_azure_name).strip()
    mapped = _voice_map()
    if voice_id and voice_id in mapped:
        return mapped[voice_id]
    return get_default_voice()


def _clamp(n: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, n))


def _rate_attr(speed: float) -> str:
    # SSML relative multiplier — keep within Azure's 0.5–2.0 guidance.
    s = _clamp(float(speed), 0.5, 1.5)
    return f"{s:.2f}"


def _pitch_attr(pitch_semitones: int) -> str:
    p = int(_clamp(int(pitch_semitones), -6, 6))
    # Azure rejects pitch="0st"; use default for neutral pitch.
    if p == 0:
        return "default"
    return f"{p:+d}st"


def _volume_attr(warmth: int) -> str:
    # Soft volume cue from warmth (kept as one axis of timbre).
    w = int(_clamp(int(warmth), 0, 100))
    pct = int(round((w - 50) / 50 * 20))
    if pct == 0:
        return "default"
    return f"{pct:+d}%"


def _warmth_pitch_bias(warmth: int) -> int:
    """Warmer → slightly higher pitch (timbre cue), cooler → lower."""
    w = int(_clamp(int(warmth), 0, 100))
    return int(round((w - 50) / 50 * 2))  # -2 .. +2 semitones


def _warmth_rate_scale(warmth: int) -> float:
    """Warmer → slightly slower (more deliberate); cooler → snappier."""
    w = int(_clamp(int(warmth), 0, 100))
    return 1.0 - ((w - 50) / 50 * 0.06)  # 0.94 .. 1.06


def _warmth_express_as(warmth: int, voice_name: str) -> tuple[str | None, float]:
    """Optional mstts express-as for style-capable voices. Returns (style, degree)."""
    # Multilingual / many en-IN voices reject express-as — only enable for known US neural styles.
    capable = voice_name in {
        "en-US-JennyNeural",
        "en-US-AriaNeural",
        "en-US-GuyNeural",
        "en-US-SaraNeural",
        "en-US-DavisNeural",
        "en-US-JaneNeural",
    }
    if not capable:
        return None, 1.0
    w = int(_clamp(int(warmth), 0, 100))
    if w >= 65:
        return "friendly", float(_clamp(0.9 + (w - 65) / 35 * 1.1, 0.5, 2.0))
    if w <= 35:
        return "serious", float(_clamp(0.9 + (35 - w) / 35 * 1.1, 0.5, 2.0))
    return None, 1.0


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p for p in parts if p.strip()]


def build_ssml(
    text: str,
    *,
    voice_name: str,
    speed: float = 1.0,
    pitch: int = 0,
    warmth: int = 60,
    pause_ms: int = 300,
    lang: str = "en-IN",
    use_express_as: bool = True,
) -> str:
    """Build SSML with prosody; warmth biases pitch/rate/volume (+ optional express-as)."""
    cleaned = " ".join((text or "").split())
    if not cleaned:
        raise ValueError("text must not be empty")
    if len(cleaned) > _MAX_TEXT_CHARS:
        cleaned = cleaned[:_MAX_TEXT_CHARS].rstrip() + "…"

    pause = int(_clamp(int(pause_ms), 0, 2000))
    # Combine user pitch with warmth timbre bias.
    effective_pitch = int(_clamp(int(pitch) + _warmth_pitch_bias(warmth), -6, 6))
    effective_speed = float(_clamp(float(speed) * _warmth_rate_scale(warmth), 0.5, 1.5))
    rate = _rate_attr(effective_speed)
    pitch_a = _pitch_attr(effective_pitch)
    volume = _volume_attr(warmth)
    sentences = _split_sentences(cleaned) or [cleaned]

    chunks: list[str] = []
    for i, sent in enumerate(sentences):
        chunks.append(xml.sax.saxutils.escape(sent))
        if i < len(sentences) - 1 and pause > 0:
            chunks.append(f'<break time="{pause}ms"/>')

    body = " ".join(chunks)
    m = re.match(r"^([a-z]{2}-[A-Z]{2})", voice_name or "")
    xml_lang = m.group(1) if m else lang

    prosody = (
        f'<prosody rate="{rate}" pitch="{pitch_a}" volume="{volume}">'
        f"{body}"
        f"</prosody>"
    )
    style, degree = _warmth_express_as(warmth, voice_name) if use_express_as else (None, 1.0)
    if style:
        inner = (
            f'<mstts:express-as style="{xml.sax.saxutils.escape(style)}" '
            f'styledegree="{degree:.2f}">{prosody}</mstts:express-as>'
        )
        ns = ' xmlns:mstts="https://www.w3.org/2001/mstts"'
    else:
        inner = prosody
        ns = ""

    return (
        f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis"{ns} xml:lang="{xml_lang}">'
        f'<voice name="{xml.sax.saxutils.escape(voice_name)}">'
        f"{inner}"
        f"</voice>"
        f"</speak>"
    )


def cache_key(
    *,
    text: str,
    voice_name: str,
    speed: float,
    pitch: int,
    warmth: int,
    pause_ms: int,
) -> str:
    payload = "|".join(
        [
            text.strip(),
            voice_name,
            f"{float(speed):.3f}",
            str(int(pitch)),
            str(int(warmth)),
            str(int(pause_ms)),
            "mp3-16k-128",
            "warmth-v2",  # pitch/rate bias + optional express-as
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cache_path(key: str) -> Path:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _CACHE_DIR / f"{key}.mp3"


def synthesize(
    text: str,
    *,
    voice_name: str | None = None,
    speed: float = 1.0,
    pitch: int = 0,
    warmth: int = 60,
    pause_ms: int = 300,
) -> dict[str, Any]:
    """Synthesize MP3 audio. Returns {audio, contentType, cacheHit, cacheKey, voiceName, latencyMs}."""
    voice = (voice_name or get_default_voice()).strip()
    key = cache_key(
        text=text,
        voice_name=voice,
        speed=speed,
        pitch=pitch,
        warmth=warmth,
        pause_ms=pause_ms,
    )
    path = _cache_path(key)
    if path.exists() and path.stat().st_size > 0:
        return {
            "audio": path.read_bytes(),
            "contentType": "audio/mpeg",
            "cacheHit": True,
            "cacheKey": key,
            "voiceName": voice,
            "latencyMs": 0,
            "chars": len(text or ""),
        }

    ssml = build_ssml(
        text,
        voice_name=voice,
        speed=speed,
        pitch=pitch,
        warmth=warmth,
        pause_ms=pause_ms,
        use_express_as=True,
    )
    region = get_speech_region()
    key_header = get_speech_key()
    url = f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1"

    def _post(ssml_body: str) -> httpx.Response:
        with httpx.Client(timeout=30.0) as client:
            return client.post(
                url,
                headers={
                    "Ocp-Apim-Subscription-Key": key_header,
                    "Content-Type": "application/ssml+xml",
                    "X-Microsoft-OutputFormat": "audio-16khz-128kbitrate-mono-mp3",
                    "User-Agent": "collections-agent-ps4",
                },
                content=ssml_body.encode("utf-8"),
            )

    t0 = time.perf_counter()
    resp = _post(ssml)
    # Some voices reject express-as — retry with prosody-only warmth mapping.
    if resp.status_code >= 400 and "express-as" in (resp.text or "").lower():
        ssml = build_ssml(
            text,
            voice_name=voice,
            speed=speed,
            pitch=pitch,
            warmth=warmth,
            pause_ms=pause_ms,
            use_express_as=False,
        )
        resp = _post(ssml)
    latency_ms = int((time.perf_counter() - t0) * 1000)

    if resp.status_code >= 400:
        detail = (resp.text or "")[:300]
        logger.error("azure_speech_tts failed status=%s detail=%s", resp.status_code, detail)
        raise RuntimeError(f"azure_speech_tts_failed:{resp.status_code}:{detail}")

    audio = resp.content
    if not audio:
        raise RuntimeError("azure_speech_tts_empty_audio")

    path.write_bytes(audio)
    chars = len(text or "")
    logger.info(
        "azure_speech_tts voice=%s chars=%s latency_ms=%s cache=miss",
        voice,
        chars,
        latency_ms,
    )
    try:
        import usage_meter

        usage_meter.record_tts_usage(
            chars=chars,
            voice=voice,
            cache_hit=False,
            source_ref="azure_speech.synthesize",
        )
    except Exception:
        logger.exception("tts usage metering failed")
    return {
        "audio": audio,
        "contentType": "audio/mpeg",
        "cacheHit": False,
        "cacheKey": key,
        "voiceName": voice,
        "latencyMs": latency_ms,
        "chars": chars,
    }


_MAX_STT_BYTES = 10 * 1024 * 1024  # 10 MiB PoC cap

_CONTENT_TYPE_ALIASES = {
    "audio/webm": "audio/webm; codecs=opus",
    "audio/wav": "audio/wav",
    "audio/x-wav": "audio/wav",
    "audio/wave": "audio/wav",
    "audio/mpeg": "audio/mpeg",
    "audio/mp3": "audio/mpeg",
    "audio/ogg": "audio/ogg; codecs=opus",
}


def _normalize_stt_content_type(content_type: str) -> str:
    base = (content_type or "").split(";")[0].strip().lower()
    if not base or base == "application/octet-stream":
        # Browsers often send webm from MediaRecorder without a precise type.
        return "audio/webm; codecs=opus"
    if base in _CONTENT_TYPE_ALIASES:
        return _CONTENT_TYPE_ALIASES[base]
    if base.startswith("audio/"):
        return content_type.split(";")[0].strip()
    raise ValueError(f"unsupported_audio_content_type:{content_type}")


def transcribe(
    audio: bytes,
    *,
    content_type: str,
    language: str | None = "en-IN",
) -> dict[str, Any]:
    """Transcribe audio via Azure Speech REST. Does not persist raw audio.

    Returns {text, latencyMs, language, recognitionStatus}.
    """
    if not audio:
        raise ValueError("empty_audio")
    if len(audio) > _MAX_STT_BYTES:
        raise ValueError("audio_too_large")

    ct = _normalize_stt_content_type(content_type)
    lang = (language or "en-IN").strip() or "en-IN"
    region = get_speech_region()
    key_header = get_speech_key()
    url = (
        f"https://{region}.stt.speech.microsoft.com/speech/recognition/conversation/"
        f"cognitiveservices/v1?language={lang}&format=simple"
    )

    t0 = time.perf_counter()
    with httpx.Client(timeout=45.0) as client:
        resp = client.post(
            url,
            headers={
                "Ocp-Apim-Subscription-Key": key_header,
                "Content-Type": ct,
                "Accept": "application/json",
                "User-Agent": "collections-agent-ps5e",
            },
            content=audio,
        )
    latency_ms = int((time.perf_counter() - t0) * 1000)

    if resp.status_code >= 400:
        detail = (resp.text or "")[:300]
        logger.error("azure_speech_stt failed status=%s detail=%s", resp.status_code, detail)
        raise RuntimeError(f"azure_speech_stt_failed:{resp.status_code}:{detail}")

    try:
        payload = resp.json()
    except Exception as exc:
        raise RuntimeError(f"azure_speech_stt_bad_json:{exc}") from exc

    status = str(payload.get("RecognitionStatus") or "")
    text = str(payload.get("DisplayText") or payload.get("Text") or "").strip()
    if status and status not in ("Success", "InitialSilenceTimeout"):
        logger.warning("azure_speech_stt status=%s text_len=%s", status, len(text))

    logger.info(
        "azure_speech_stt lang=%s bytes=%s latency_ms=%s status=%s",
        lang,
        len(audio),
        latency_ms,
        status or "?",
    )
    try:
        import usage_meter

        usage_meter.record_stt_usage(
            audio_bytes=len(audio),
            content_type=ct,
            language=lang,
            source_ref="azure_speech.transcribe",
        )
    except Exception:
        logger.exception("stt usage metering failed")
    return {
        "text": text,
        "latencyMs": latency_ms,
        "language": lang,
        "recognitionStatus": status or None,
    }

