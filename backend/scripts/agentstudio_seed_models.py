"""Give AgentStudio this deployment's own model providers.

The engine runs on the organization's keys (BYOK); nothing is hosted by the
engine vendor. This writes the tenant's engine model configuration from the
provider settings the rest of the platform already uses (backend .env), so a
fresh engine is usable without anyone pasting keys into a form:

    LLM         Azure OpenAI  (AZURE_OPENAI_VOICE_* deployment)
    Transcriber Azure Speech  (AZURE_SPEECH_KEY / _REGION, AZURE_SPEECH_STT_LANGUAGE)
    Voice       Fish Audio    (FISH_API_KEYS, FISH_TTS_VOICE_DEFAULT); Azure Speech
                (AZURE_SPEECH_KEY / _REGION / _TTS_VOICE_DEFAULT) when no Fish key is set
    Embeddings  Azure OpenAI  (AZURE_OPENAI_EMBEDDING_DEPLOYMENT, 1536 dims)

The organization transcribes in one language; an agent whose callers may
switch language sets its own list in Voice Studio (Azure language
identification). ``--stt-only`` changes just the transcriber and keeps every
other section as saved (voices, models, keys).

Idempotent; re-run after rotating a key. Secrets are never printed.

    docker exec collections_api python -m scripts.agentstudio_seed_models --actor priya-nair
    docker exec collections_api python -m scripts.agentstudio_seed_models --actor priya-nair --dry-run
    docker exec collections_api python -m scripts.agentstudio_seed_models --actor priya-nair --stt-only
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


def build_stt() -> dict:
    return {
        "provider": "azure_speech",
        "region": _require("AZURE_SPEECH_REGION"),
        "language": env_str("AZURE_SPEECH_STT_LANGUAGE", "en-IN"),
        "api_key": _require("AZURE_SPEECH_KEY"),
    }


def build_tts() -> dict:
    fish_key = (env_str("FISH_API_KEYS") or "").split(",")[0].strip()
    if fish_key:
        # Fish S2.1 Pro (free) detects the spoken language from the text; "Amir" is
        # the English + Hindi voice chosen by audition.
        return {
            "provider": "fish",
            "voice": env_str("FISH_TTS_VOICE_DEFAULT", "7cccb9161ca24b13861f77f038aaa97a"),
            "api_key": fish_key,
        }
    return {
        "provider": "azure_speech",
        "region": _require("AZURE_SPEECH_REGION"),
        "voice": env_str("AZURE_SPEECH_TTS_VOICE_DEFAULT", "en-IN-NeerjaNeural"),
        "language": "en-IN",
        "api_key": _require("AZURE_SPEECH_KEY"),
    }


def build_configuration() -> dict:
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
                "stt": build_stt(),
                "tts": build_tts(),
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
    parser.add_argument("--stt-only", action="store_true",
                        help="replace only the transcriber; keep the saved voice, models and keys")
    args = parser.parse_args()

    import db

    engine_url = env_str("AGENTSTUDIO_ENGINE_URL", "http://agentstudio_engine:8000").rstrip("/")
    headers = {
        "X-Internal-Secret": _require("AGENTSTUDIO_INTERNAL_SECRET"),
        "X-User-Id": args.actor,
        "X-Org-Id": db.current_tenant(),
    }
    if args.stt_only:
        # The saved configuration comes back with its keys masked; the engine
        # restores masked keys from what it stores, so only the transcriber changes.
        current = httpx.get(f"{engine_url}/api/v1/organizations/model-configurations/v2",
                            headers=headers, timeout=30)
        current.raise_for_status()
        config = current.json().get("configuration") or {}
        pipeline = ((config.get("byok") or {}).get("pipeline"))
        if config.get("mode") != "byok" or not pipeline:
            sys.exit("the organization has no speech pipeline configuration to update; run without --stt-only")
        pipeline["stt"] = build_stt()
    else:
        config = build_configuration()
    print(json.dumps(_redacted(config), indent=2))
    if args.dry_run:
        return

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
