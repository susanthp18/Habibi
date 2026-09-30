"""The verified OpenRouter/Fish speech request contract, shared by previews and runtime."""

import re

OPENROUTER_SPEECH_URL = "https://openrouter.ai/api/v1/audio/speech"
FISH_FREE_MODEL = "fish-audio/s2.1-pro-free:free"
FISH_DEMO_VOICE = "9dc372bfccb04efb9f6b7cd588952a73"
FISH_DEFAULT_STYLE = "calm and conversational"


def speech_request(
    *,
    text: str,
    model: str,
    voice: str,
    style: str | None,
    response_format: str = "pcm",
) -> dict:
    if model != FISH_FREE_MODEL:
        raise ValueError("Select the supported Fish free model")
    if not voice or len(voice) > 80:
        raise ValueError("Enter a Fish voice ID")
    style = FISH_DEFAULT_STYLE if style is None else style.strip()
    if not style or len(style) > 40 or re.search(r"[\[\]\r\n]", style):
        raise ValueError(
            "Use a speaking style of 1–40 characters without brackets or newlines"
        )
    if response_format not in {"pcm", "mp3"}:
        raise ValueError("Unsupported speech format")
    # Only the provider request contains delivery cues. The original text continues
    # through Pipecat's transcript/context path unchanged.
    return {
        "model": model,
        "voice": voice,
        "input": f"[{style}] {text}",
        "response_format": response_format,
    }
