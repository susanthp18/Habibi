"""Voice runtime env helpers — map our .env names onto Pipecat constructors.

Do NOT rename AZURE_OPENAI_* / AZURE_SPEECH_* globals; pass values explicitly.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Allow `python -m voice.spike` and `python voice/spike.py` from backend/.
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from env_loader import load_env  # noqa: E402


def _require(name: str) -> str:
    load_env()
    value = (os.getenv(name) or "").strip()
    if not value:
        raise RuntimeError(f"Missing required env var: {name}")
    return value


def _optional(name: str) -> str | None:
    load_env()
    value = (os.getenv(name) or "").strip()
    return value or None


def azure_openai_api_key() -> str:
    return _require("AZURE_OPENAI_API_KEY")


def azure_openai_endpoint() -> str:
    return _require("AZURE_OPENAI_ENDPOINT").rstrip("/")


def azure_openai_api_version() -> str:
    load_env()
    return (os.getenv("AZURE_OPENAI_API_VERSION") or "2025-04-01-preview").strip()


def azure_openai_chat_deployment() -> str:
    return _require("AZURE_OPENAI_CHAT_DEPLOYMENT")


def azure_openai_voice_api_key() -> str:
    """Voice resource key (BT-RMC etc.); falls back to main AZURE_OPENAI_API_KEY."""
    return _optional("AZURE_OPENAI_VOICE_API_KEY") or azure_openai_api_key()


def azure_openai_voice_endpoint() -> str:
    """Voice resource endpoint; falls back to main AZURE_OPENAI_ENDPOINT."""
    raw = _optional("AZURE_OPENAI_VOICE_ENDPOINT")
    return (raw or azure_openai_endpoint()).rstrip("/")


def azure_openai_voice_api_version() -> str:
    return _optional("AZURE_OPENAI_VOICE_API_VERSION") or azure_openai_api_version()


def azure_openai_voice_deployment() -> str:
    """Fast voice-loop deployment; falls back to CHAT until provisioned."""
    return _optional("AZURE_OPENAI_VOICE_DEPLOYMENT") or azure_openai_chat_deployment()


def azure_speech_key() -> str:
    return _require("AZURE_SPEECH_KEY")


def azure_speech_region() -> str:
    return _require("AZURE_SPEECH_REGION")


def azure_speech_default_voice() -> str:
    load_env()
    return (os.getenv("AZURE_SPEECH_TTS_VOICE_DEFAULT") or "en-IN-AartiNeural").strip()


def twilio_account_sid() -> str | None:
    return _optional("TWILIO_ACCOUNT_SID")


def twilio_auth_token() -> str | None:
    return _optional("TWILIO_AUTH_TOKEN")


def twilio_phone_number() -> str | None:
    return _optional("TWILIO_PHONE_NUMBER")


def supervisor_callback_phone() -> str | None:
    return _optional("SUPERVISOR_CALLBACK_PHONE")


def voice_handoff_mode() -> str:
    """callback_queue (Inbox) | warm (Twilio conference dial-out)."""
    load_env()
    mode = (os.getenv("VOICE_HANDOFF_MODE") or "callback_queue").strip().lower()
    return "warm" if mode in {"warm", "warm_transfer", "conference"} else "callback_queue"


def voice_multi_agent_enabled() -> bool:
    load_env()
    return (os.getenv("VOICE_MULTI_AGENT_ENABLED") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def redis_url() -> str | None:
    return _optional("REDIS_URL")


def voice_public_base_url() -> str | None:
    """Public HTTPS origin for the Pipecat runner (Media Streams /ws).

    Must point at the voice process (:7860), not the CRM API (:8000).
    """
    return _optional("VOICE_PUBLIC_BASE_URL")
