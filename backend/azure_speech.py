"""Azure Speech TTS + STT via REST — PS-4 / PS-5E.

Uses the regional cognitiveservices endpoints. No Speech SDK dependency —
httpx is already required. TTS and STT share AZURE_SPEECH_KEY / REGION.
"""

from __future__ import annotations

import hashlib
import logging
import os
import random
import re
import tempfile
import time
import xml.sax.saxutils
from pathlib import Path
from typing import Any

import threading

import httpx

from env_loader import load_env

logger = logging.getLogger(__name__)

_CACHE_DIR = Path(__file__).resolve().parent / ".cache" / "tts"
_MAX_TEXT_CHARS = 500
_DEFAULT_VOICE = "en-IN-AartiNeural"
_MAX_TTS_CACHE_BYTES = int(os.getenv("AZURE_TTS_CACHE_MAX_BYTES") or str(200 * 1024 * 1024))
# Age cap as well as size cap: an instance whose traffic drops below the size
# threshold would otherwise keep synthesized customer-facing audio on disk
# indefinitely.
_MAX_TTS_CACHE_AGE_S = max(
    3600, int(os.getenv("AZURE_TTS_CACHE_MAX_AGE_S") or str(14 * 24 * 3600))
)
# Sweep at most this often, so a cache-hit path does not stat the whole dir on
# every request.
_TTS_SWEEP_INTERVAL_S = 300.0
_tts_last_sweep = 0.0
_tts_sweep_lock = threading.Lock()

_SPEECH_SEM = threading.BoundedSemaphore(
    max(1, int(os.getenv("AZURE_SPEECH_MAX_CONCURRENCY") or "8"))
)

# Shared sync httpx client — keep-alive to Azure Speech (TTS 30s / STT 45s).
_http_client: httpx.Client | None = None
_http_lock = threading.Lock()


def _http() -> httpx.Client:
    global _http_client
    if _http_client is not None:
        return _http_client
    with _http_lock:
        if _http_client is None:
            _http_client = httpx.Client(
                timeout=httpx.Timeout(45.0, connect=10.0),
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            )
        return _http_client


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
    if looks_like_azure_short_name(voice_id):
        return str(voice_id).strip()
    mapped = _voice_map()
    if voice_id and voice_id in mapped:
        return mapped[voice_id]
    return get_default_voice()


def looks_like_azure_short_name(value: str | None) -> bool:
    """True when value looks like en-IN-AartiNeural / hi-IN-SwaraNeural etc."""
    v = (value or "").strip()
    if not v or " " in v:
        return False
    # Locale-ShortName pattern, or known Neural/HD suffixes.
    if re.match(r"^[a-z]{2,3}-[A-Z]{2}-.+$", v):
        return True
    return any(tok in v for tok in ("Neural", "DragonHD", "HDFlash", "Turbo", "MAI-Voice"))


def catalog_styles_for_voice(short_name: str | None) -> list[str] | None:
    """Return StyleList from catalog when available; None if catalog unknown."""
    sn = (short_name or "").strip()
    if not sn:
        return None
    try:
        import db

        entry = db.get_tts_voice_catalog_entry(sn)
        if entry is None:
            return None
        styles = entry.get("styles") or []
        return [str(s) for s in styles] if isinstance(styles, list) else []
    except Exception:
        return None


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
    # Prefer live catalog StyleList; fall back to a small known-capable set.
    catalog_styles = catalog_styles_for_voice(voice_name)
    if catalog_styles is not None:
        capable_styles = {s.lower() for s in catalog_styles}
        if not capable_styles:
            return None, 1.0
    else:
        capable = voice_name in {
            "en-US-JennyNeural",
            "en-US-AriaNeural",
            "en-US-GuyNeural",
            "en-US-SaraNeural",
            "en-US-DavisNeural",
            "en-US-JaneNeural",
            "en-IN-NeerjaNeural",
        }
        if not capable:
            return None, 1.0
        capable_styles = {"friendly", "serious", "empathetic", "cheerful", "calm"}

    w = int(_clamp(int(warmth), 0, 100))
    if w >= 65 and "friendly" in capable_styles:
        return "friendly", float(_clamp(0.9 + (w - 65) / 35 * 1.1, 0.5, 2.0))
    if w >= 65 and "cheerful" in capable_styles:
        return "cheerful", float(_clamp(0.9 + (w - 65) / 35 * 1.1, 0.5, 2.0))
    if w <= 35 and "serious" in capable_styles:
        return "serious", float(_clamp(0.9 + (35 - w) / 35 * 1.1, 0.5, 2.0))
    if "empathetic" in capable_styles and 35 < w < 65:
        return "empathetic", float(_clamp(0.9 + abs(w - 50) / 50 * 0.6, 0.5, 2.0))
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


def _evict_tts_cache() -> None:
    """Bound the on-disk TTS cache by age first, then total size (LRU by mtime)."""
    try:
        files = [p for p in _CACHE_DIR.glob("*.mp3") if p.is_file()]
    except OSError:
        return

    now = time.time()
    total = 0
    live: list[tuple[float, int, Path]] = []
    for path in files:
        try:
            stat = path.stat()
        except OSError:
            continue
        if now - stat.st_mtime > _MAX_TTS_CACHE_AGE_S:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            continue
        live.append((stat.st_mtime, stat.st_size, path))
        total += stat.st_size

    if total <= _MAX_TTS_CACHE_BYTES:
        return
    live.sort(key=lambda item: item[0])
    for _mtime, size, path in live:
        if total <= _MAX_TTS_CACHE_BYTES:
            break
        try:
            path.unlink(missing_ok=True)
            total -= size
        except OSError:
            continue


def _maybe_sweep_tts_cache() -> None:
    """Throttled sweep so eviction also runs on cache-hit-only workloads."""
    global _tts_last_sweep

    now = time.monotonic()
    if now - _tts_last_sweep < _TTS_SWEEP_INTERVAL_S:
        return
    with _tts_sweep_lock:
        if now - _tts_last_sweep < _TTS_SWEEP_INTERVAL_S:
            return
        _tts_last_sweep = now
    try:
        _evict_tts_cache()
    except Exception:
        logger.debug("tts cache sweep failed", exc_info=True)


_SPEECH_RETRY_STATUSES = frozenset({408, 429, 500, 502, 503, 504})
_SPEECH_MAX_RETRIES = max(0, int(os.getenv("AZURE_SPEECH_MAX_RETRIES") or "2"))
_SPEECH_RETRY_MAX_SLEEP_S = 10.0


def _retry_after_seconds(resp: httpx.Response, attempt: int) -> float:
    """Honour Retry-After when Azure sends it, else exponential backoff + jitter.

    Jitter matters here because every worker throttled by the same Azure region
    retries on the same schedule otherwise, re-creating the burst that caused
    the 429. Retry-After is honoured exactly (Azure's instruction wins) but
    still gets a small positive jitter for the same reason.
    """
    raw = (resp.headers.get("retry-after") or "").strip()
    if raw:
        try:
            base = min(_SPEECH_RETRY_MAX_SLEEP_S, max(0.0, float(raw)))
            return min(_SPEECH_RETRY_MAX_SLEEP_S, base + random.uniform(0.0, 0.25))
        except ValueError:
            pass
    base = min(_SPEECH_RETRY_MAX_SLEEP_S, 0.5 * (2**attempt))
    # Full jitter: uniform over [0, base] — standard AWS-style decorrelation.
    return random.uniform(0.0, base)


class _SpeechRetryable(Exception):
    """A 429/5xx from Azure Speech, raised so the breaker counts it as a failure.

    ``httpx`` returns those as ordinary responses, so the breaker saw a clean
    success on every throttled or server-errored attempt and could never open —
    the opposite of what the retry loop's docstring promised.
    """

    def __init__(self, response: httpx.Response) -> None:
        super().__init__(f"azure_speech_status_{response.status_code}")
        self.response = response


def _speech_call(fn, *, raise_on_retryable: bool = False):
    """Concurrency semaphore + circuit breaker around one Azure Speech HTTP call."""
    import circuit_breaker

    def _guarded():
        resp = fn()
        if raise_on_retryable and resp.status_code in _SPEECH_RETRY_STATUSES:
            raise _SpeechRetryable(resp)
        return resp

    if not _SPEECH_SEM.acquire(timeout=10.0):
        raise RuntimeError("azure_speech_concurrency_saturated")
    try:
        return circuit_breaker.get_breaker("azure_speech").call(_guarded)
    finally:
        _SPEECH_SEM.release()


def _speech_call_with_retry(fn, *, label: str) -> httpx.Response:
    """Bounded retry for idempotent Speech requests on 429/5xx.

    Azure Speech throttles aggressively under burst; surfacing the first 429 to
    the caller drops a live call turn that a sub-second retry would have served.
    Retries stop at _SPEECH_MAX_RETRIES so a hard outage still fails fast and
    the circuit breaker (which sees each attempt) can open.
    """
    last: httpx.Response | None = None
    for attempt in range(_SPEECH_MAX_RETRIES + 1):
        try:
            return _speech_call(fn, raise_on_retryable=True)
        except _SpeechRetryable as exc:
            resp = exc.response
        last = resp
        if attempt == _SPEECH_MAX_RETRIES:
            break
        delay = _retry_after_seconds(resp, attempt)
        logger.warning(
            "azure_speech %s status=%s retrying in %.2fs (attempt %s/%s)",
            label,
            resp.status_code,
            delay,
            attempt + 1,
            _SPEECH_MAX_RETRIES,
        )
        time.sleep(delay)
    assert last is not None
    return last


def synthesize(
    text: str,
    *,
    voice_name: str | None = None,
    speed: float = 1.0,
    pitch: int = 0,
    warmth: int = 60,
    pause_ms: int = 300,
    force_fresh: bool = False,
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
    _maybe_sweep_tts_cache()
    # exists() → read_bytes() is not atomic, and _maybe_sweep_tts_cache() above
    # can evict this very entry in between. Treat the race as a miss and
    # synthesize rather than raising FileNotFoundError at the caller.
    # `force_fresh` is the studio's re-roll. Azure is effectively deterministic
    # — with this cache cleared, three synthesises of the same text returned
    # 85248 bytes every time, differing only in low-order encoder bits — so the
    # studio does not offer a re-roll for Azure voices. Honoured anyway: the
    # request can be made, and silently serving a cache hit for an explicit
    # "new take" would be the kind of lie this path already had one of.
    try:
        if not force_fresh and path.exists() and path.stat().st_size > 0:
            return {
                "audio": path.read_bytes(),
                "contentType": "audio/mpeg",
                "cacheHit": True,
                "cacheKey": key,
                "voiceName": voice,
                "latencyMs": 0,
                "chars": len(text or ""),
            }
    except (FileNotFoundError, OSError):
        logger.debug("tts cache entry vanished mid-read key=%s", key)

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
        # Synthesis is idempotent (same SSML → same audio), so retrying a 429/5xx
        # cannot produce a duplicate side effect.
        return _speech_call_with_retry(
            lambda: _http().post(
                url,
                headers={
                    "Ocp-Apim-Subscription-Key": key_header,
                    "Content-Type": "application/ssml+xml",
                    "X-Microsoft-OutputFormat": "audio-16khz-128kbitrate-mono-mp3",
                    "User-Agent": "collections-agent-ps4",
                },
                content=ssml_body.encode("utf-8"),
                timeout=30.0,
            ),
            label="tts",
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

    # Atomic write: a crash mid-write must not leave a truncated MP3 that the
    # cache-hit size gate above would then serve as valid audio. Use a UNIQUE temp
    # file per write (same dir, for an atomic rename) so concurrent writers to the
    # same cache key don't clobber each other's temp file before os.replace.
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".mp3.tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(audio)
        os.replace(tmp_name, path)
        _evict_tts_cache()
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
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
    # Recognition is idempotent — the same bytes yield the same transcript and
    # nothing is persisted server-side, so a 429/5xx retry is safe.
    resp = _speech_call_with_retry(
        lambda: _http().post(
            url,
            headers={
                "Ocp-Apim-Subscription-Key": key_header,
                "Content-Type": ct,
                "Accept": "application/json",
                "User-Agent": "collections-agent-ps5e",
            },
            content=audio,
            timeout=45.0,
        ),
        label="stt",
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

        minutes = None
        raw_duration = payload.get("Duration")
        try:
            # Azure Speech Duration is in 100-nanosecond ticks.
            ticks = int(raw_duration) if raw_duration is not None else 0
            if ticks > 0:
                minutes = ticks / 10_000_000.0 / 60.0
        except (TypeError, ValueError):
            minutes = None

        usage_meter.record_stt_usage(
            audio_bytes=len(audio),
            content_type=ct,
            minutes=minutes,
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

