"""Give AgentStudio this deployment's own model providers.

The engine runs on the organization's keys (BYOK); nothing is hosted by the
engine vendor. This writes the tenant's engine model configuration from the
provider settings the rest of the platform already uses (backend .env), so a
fresh engine is usable without anyone pasting keys into a form:

    LLM         Azure OpenAI  (AZURE_OPENAI_VOICE_* deployment)
    Transcriber Deepgram      (DEEPGRAM_API_KEYS, DEEPGRAM_STT_MODEL, multilingual)
    Voice       Azure Speech  (AZURE_SPEECH_KEY / _REGION / _TTS_VOICE_DEFAULT)
    Embeddings  Azure OpenAI  (AZURE_OPENAI_EMBEDDING_DEPLOYMENT, 1536 dims)

Idempotent; re-run after rotating a key. Secrets are never printed.

    docker exec collections_api python -m scripts.agentstudio_seed_models --actor priya-nair
    docker exec collections_api python -m scripts.agentstudio_seed_models --actor priya-nair --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys

import httpx

from env_loader import load_env
from env_utils import env_str


def _require(name: str) -> str:
    value = env_str(name)
    if not value:
        sys.exit(f"missing {name} in the backend environment")
    return value


def build_configuration() -> dict:
    deepgram_keys = [k.strip() for k in _require("DEEPGRAM_API_KEYS").split(",") if k.strip()]
    return {
        "version": 2,
        "mode": "byok",
        "byok": {
            "mode": "pipeline",
            "pipeline": {
                "llm": {
                    "provider": "azure",
                    "model": _require("AZURE_OPENAI_VOICE_DEPLOYMENT"),
                    "endpoint": _require("AZURE_OPENAI_VOICE_ENDPOINT"),
                    "api_key": _require("AZURE_OPENAI_VOICE_API_KEY"),
                },
                "stt": {
                    "provider": "deepgram",
                    "model": env_str("DEEPGRAM_STT_MODEL", "nova-3"),
                    "language": "multi",
                    "api_key": deepgram_keys if len(deepgram_keys) > 1 else deepgram_keys[0],
                },
                "tts": {
                    "provider": "azure_speech",
                    "region": _require("AZURE_SPEECH_REGION"),
                    "voice": env_str("AZURE_SPEECH_TTS_VOICE_DEFAULT", "en-IN-NeerjaNeural"),
                    "language": "en-IN",
                    "api_key": _require("AZURE_SPEECH_KEY"),
                },
                "embeddings": {
                    "provider": "azure",
                    "model": _require("AZURE_OPENAI_EMBEDDING_DEPLOYMENT"),
                    "endpoint": _require("AZURE_OPENAI_ENDPOINT"),
                    "api_version": env_str("AZURE_OPENAI_API_VERSION", "2024-10-21"),
                    "api_key": _require("AZURE_OPENAI_API_KEY"),
                },
            },
        },
    }


def _redacted(config: dict) -> dict:
    def walk(node):
        if isinstance(node, dict):
            return {k: ("***" if k == "api_key" else walk(v)) for k, v in node.items()}
        return node

    return walk(config)


def main() -> None:
    load_env()
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--actor", required=True, help="users.id recorded as the engine user making the change")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    config = build_configuration()
    print(json.dumps(_redacted(config), indent=2))
    if args.dry_run:
        return

    import db

    engine_url = env_str("AGENTSTUDIO_ENGINE_URL", "http://agentstudio_engine:8000").rstrip("/")
    headers = {
        "X-Internal-Secret": _require("AGENTSTUDIO_INTERNAL_SECRET"),
        "X-User-Id": args.actor,
        "X-Org-Id": db.current_tenant(),
    }
    resp = httpx.put(
        f"{engine_url}/api/v1/organizations/model-configurations/v2",
        json=config,
        headers=headers,
        timeout=60,
    )
    if resp.status_code >= 400:
        sys.exit(f"engine refused the configuration ({resp.status_code}): {resp.text[:400]}")
    print(f"saved: {resp.json().get('source')}")


if __name__ == "__main__":
    main()
