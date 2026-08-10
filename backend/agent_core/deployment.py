"""Active deployment loader — bot_deployments is authoritative.

Prompt Studio publish flips the active row; sandbox / WhatsApp / voice all
resolve runtime config through this module so they cannot drift.
"""

from __future__ import annotations

from typing import Any

import db
from agent_core.tuning import default_tuning, normalize_tuning


def load_active_bundle(
    environment: str = "production",
    *,
    bot_id: str | None = None,
    fallback_environments: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Load active deployment + prompt version + voice config.

    Raises KeyError('active_deployment_not_found') when no active row exists
    for the requested (or fallback) environment(s).
    """
    envs: list[str] = []
    for env in (environment, *fallback_environments):
        if env and env not in envs:
            envs.append(env)
    deployment: dict[str, Any] | None = None
    for env in envs:
        deployment = db.get_active_deployment(bot_id=bot_id, environment=env)
        if deployment:
            break
    if not deployment:
        raise KeyError("active_deployment_not_found")

    prompt_version_id = deployment.get("promptVersionId")
    if not prompt_version_id:
        raise KeyError("active_deployment_missing_prompt_version")

    version = db.get_prompt_version(prompt_version_id)
    if not version:
        raise KeyError(f"prompt_version_not_found: {prompt_version_id}")

    persona = version.get("persona") if isinstance(version.get("persona"), dict) else {}
    voice = version.get("voice") if isinstance(version.get("voice"), dict) else {}
    guardrails = version.get("guardrails") if isinstance(version.get("guardrails"), dict) else {}
    voice_config = deployment.get("voiceConfig") if isinstance(deployment.get("voiceConfig"), dict) else {}
    raw_tuning = deployment.get("tuning") if isinstance(deployment.get("tuning"), dict) else {}
    tuning = normalize_tuning(raw_tuning) if raw_tuning else default_tuning()

    return {
        "deployment": deployment,
        "deploymentId": deployment["id"],
        "promptVersionId": prompt_version_id,
        "kbSnapshotId": deployment.get("kbSnapshotId"),
        # Azure ShortName (column formerly held studio alias ids like "priya").
        "ttsVoiceId": deployment.get("ttsVoiceId")
        or (tuning.get("tts") or {}).get("voice")
        or voice_config.get("azureVoiceName"),
        "voiceConfig": voice_config,
        "tuning": tuning,
        "prompt": version.get("prompt") or "",
        "persona": persona,
        "voice": voice,
        "guardrails": guardrails,
        # Authored conversation graph. Empty when the version predates flow
        # authoring; voice/bot.py then keeps the built-in flow.
        "flow": version.get("flow") if isinstance(version.get("flow"), dict) else {},
        "promptVersion": version,
    }


def resolve_prompt_bundle(
    *,
    prompt_version_id: str | None = None,
    environment: str = "production",
    bot_id: str | None = None,
    fallback_environments: tuple[str, ...] = ("production",),
) -> dict[str, Any]:
    """Resolve an explicit prompt version, else the active deployment bundle."""
    if prompt_version_id:
        version = db.get_prompt_version(prompt_version_id)
        if not version:
            raise KeyError(f"prompt_version_not_found: {prompt_version_id}")
        persona = version.get("persona") if isinstance(version.get("persona"), dict) else {}
        voice = version.get("voice") if isinstance(version.get("voice"), dict) else {}
        guardrails = version.get("guardrails") if isinstance(version.get("guardrails"), dict) else {}
        raw_tuning = version.get("tuning") if isinstance(version.get("tuning"), dict) else {}
        tuning = normalize_tuning(raw_tuning) if raw_tuning else default_tuning()
        return {
            "deployment": None,
            "deploymentId": None,
            "promptVersionId": prompt_version_id,
            "kbSnapshotId": None,
            "ttsVoiceId": (voice or {}).get("voiceId"),
            "voiceConfig": {},
            "tuning": tuning,
            "prompt": version.get("prompt") or "",
            "persona": persona,
            "voice": voice,
            "guardrails": guardrails,
            "flow": version.get("flow") if isinstance(version.get("flow"), dict) else {},
            "promptVersion": version,
        }
    return load_active_bundle(
        environment,
        bot_id=bot_id,
        fallback_environments=fallback_environments,
    )
