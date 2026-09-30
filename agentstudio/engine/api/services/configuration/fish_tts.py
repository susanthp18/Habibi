"""Fish Audio's own speech API: the request contract shared by previews and runtime.

Measured against api.fish.audio on 2026-09-30: `latency="normal"` buffers the whole
clip before the first byte (2-4.5 s), so only the streaming modes are offered; PCM
responses carry no rate in their Content-Type, so the rate is always requested.
"""

FISH_TTS_URL = "https://api.fish.audio/v1/tts"
FISH_CATALOG_URL = "https://api.fish.audio/model"
FISH_KEY_CHECK_URL = "https://api.fish.audio/wallet/self/api-credit"
FISH_MODEL = "s2.1-pro-free"
FISH_PCM_RATES = (8000, 16000, 24000, 32000, 44100)
FISH_MP3_RATE = 44100


def fish_request(
    *,
    text: str,
    voice: str,
    style: str | None = None,
    speed: float = 1.0,
    volume: float = 0,
    latency: str = "balanced",
    temperature: float | None = None,
    top_p: float | None = None,
    response_format: str = "pcm",
    sample_rate: int = 8000,
) -> dict:
    """The JSON body for POST /v1/tts. The style cue reaches only the provider;
    the original text continues through Pipecat's transcript/context unchanged."""
    body = {
        "text": f"[{style}] {text}" if style else text,
        "reference_id": voice,
        "format": response_format,
        "sample_rate": sample_rate,
        "latency": latency,
        "prosody": {"speed": speed, "volume": volume},
    }
    if temperature is not None:
        body["temperature"] = temperature
    if top_p is not None:
        body["top_p"] = top_p
    return body


def fish_headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}", "model": FISH_MODEL}


def fish_pcm_rate(pipeline_rate: int) -> int:
    """Synthesize at the pipeline's own rate when Fish offers it (8 kHz telephony,
    16 kHz WebRTC); otherwise 24 kHz, and the output transport resamples."""
    return pipeline_rate if pipeline_rate in FISH_PCM_RATES else 24000
