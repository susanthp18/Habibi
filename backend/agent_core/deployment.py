"""Active deployment loader — bot_deployments is authoritative.

Prompt Studio publish flips the active row; sandbox / WhatsApp / voice all
resolve runtime config through this module so they cannot drift.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import db
from agent_core.tuning import default_tuning, normalize_tuning
from agent_core.dicts import sub

logger = logging.getLogger(__name__)


def active_environment() -> str:
    """Which deployment environment this process serves.

    Five spellings of "am I live" used to disagree: the text mouth read
    ``BOT_ENVIRONMENT``, the voice mouth wrote ``"production"`` in two
    places, and the bundle loader defaulted to a third literal. One process
    could serve production text and sandbox voice. This is the one answer;
    every default below reads it at call time.
    """
    return (os.getenv("BOT_ENVIRONMENT") or "production").strip() or "production"


class ChannelNotAuthored(RuntimeError):
    """The deployment's card does not answer this channel.

    Deliberately not a ``KeyError``: every runtime treats a ``KeyError`` from
    :func:`load_active_bundle` as "no deployment" and falls back, and a card
    that refused a channel must not be served by the fallback.
    """


def load_active_bundle(
    environment: str | None = None,
    *,
    bot_id: str | None = None,
    fallback_environments: tuple[str, ...] = (),
    customer_id: str | None = None,
    channel: str | None = None,
) -> dict[str, Any]:
    """Load active deployment + prompt version + voice config.

    Raises KeyError('active_deployment_not_found') when no active row exists
    for the requested (or fallback) environment(s). Optional customer_id
    hash-splits a running canary experiment; retired baselines load by id.
    ``channel`` given, the card's ``identity.channels`` is honoured: a card
    that does not author the channel raises :class:`ChannelNotAuthored`.
    """
    envs: list[str] = []
    for env in (environment or active_environment(), *fallback_environments):
        if env and env not in envs:
            envs.append(env)
    deployment: dict[str, Any] | None = None
    resolved_bot = bot_id or db.DEFAULT_BOT_ID
    for env in envs:
        dep_id = None
        picked = False
        try:
            from agent_core.canary import pick_deployment_id

            dep_id = pick_deployment_id(resolved_bot, environment=env, customer_id=customer_id)
            picked = True
        except Exception:
            dep_id = None
        if picked:
            if not dep_id:
                continue
            deployment = db.get_deployment(dep_id)
            if deployment:
                break
            continue
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

    persona = sub(version, "persona")
    voice = sub(version, "voice")
    guardrails = sub(version, "guardrails")
    voice_config = sub(deployment, "voiceConfig")
    raw_tuning = sub(deployment, "tuning")
    tuning = normalize_tuning(raw_tuning) if raw_tuning else default_tuning()

    compiled = version.get("compiled") if isinstance(version.get("compiled"), dict) else None
    frozen_tools = (
        deployment.get("frozenTools") if deployment.get("frozenTools") is not None else []
    )
    bundle = {
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
        "flow": sub(version, "flow"),
        "promptVersion": version,
        "agentCard": sub(version, "agentCard"),
        "botId": version.get("botId"),
        # Frozen at publish. None on a sandbox resolve_prompt_bundle; empty list
        # on a production deployment that predates the snapshot (fail closed).
        "frozenTools": frozen_tools,
        "compiled": compiled,
        "bundleHash": deployment.get("bundleHash"),
    }
    _dual_compute_parity(bundle)
    if channel:
        from agent_core.cards.schema import authors_channel

        if not authors_channel(bundle["agentCard"], channel):
            raise ChannelNotAuthored(f"channel_not_authored:{bundle.get('botId') or bot_id}:{channel}")
    return bundle


def _dual_compute_parity(bundle: dict[str, Any]) -> None:
    """The persisted compiled artefact is the mouth; the live row is checked against it.

    A mismatch is logged (``scripts/fleet_parity.py`` reports the same thing
    across every active deployment) and the compiled fields are installed on
    the bundle either way -- a call runs what publish compiled, never a live
    row that drifted from it.
    """
    compiled = bundle.get("compiled")
    if not isinstance(compiled, dict) or not compiled.get("bundle_hash"):
        return
    pinned_hash = str(bundle.get("bundleHash") or "")
    if pinned_hash and pinned_hash != str(compiled.get("bundle_hash") or ""):
        logger.error(
            "compiled-bundle deployment hash mismatch bot=%s pinned=%s stored=%s",
            bundle.get("botId"),
            pinned_hash,
            compiled.get("bundle_hash"),
        )
        return
    try:
        from agent_core.fleet.compile import bundle_hash_valid, parity_report
        from agent_core.fleet.schema import CompiledBundle
        from agent_core.tools.grant import ToolGrant

        parsed = CompiledBundle.model_validate(compiled)
        if not bundle_hash_valid(parsed):
            logger.error(
                "compiled-bundle content hash invalid bot=%s hash=%s",
                bundle.get("botId"),
                parsed.bundle_hash,
            )
            return
        live_grant = ToolGrant.for_bundle(bundle, channel="voice")
        report = parity_report(
            live_prompt=str(bundle.get("prompt") or ""),
            live_persona=sub(bundle, "persona"),
            live_guardrails=(
                bundle.get("guardrails")
                if isinstance(bundle.get("guardrails"), dict)
                else {}
            ),
            live_flow=sub(bundle, "flow"),
            live_tools=live_grant.allowed,
            bundle=parsed,
            channel="voice",
            bot_id=str(bundle.get("botId") or ""),
            prompt_version_id=str(bundle.get("promptVersionId") or ""),
        )
        if not report["ok"]:
            logger.warning(
                "compiled-bundle parity mismatch bot=%s hash=%s mismatches=%s",
                bundle.get("botId"),
                parsed.bundle_hash,
                report.get("mismatches"),
            )
        bundle["prompt"] = parsed.prompt
        bundle["persona"] = parsed.persona
        bundle["guardrails"] = parsed.guardrails
        # The merged graph when there is a fleet, the authored one when
        # there is not.
        bundle["flow"] = parsed.fleet_flow or parsed.flow
        bundle["agentCard"] = parsed.agent_card
    except Exception:
        logger.exception("compiled-bundle parity check failed")


def resolve_prompt_bundle(
    *,
    prompt_version_id: str | None = None,
    environment: str | None = None,
    bot_id: str | None = None,
    fallback_environments: tuple[str, ...] = ("production",),
) -> dict[str, Any]:
    """Resolve an explicit prompt version, else the active deployment bundle."""
    environment = environment or active_environment()
    if prompt_version_id:
        version = db.get_prompt_version(prompt_version_id)
        if not version:
            raise KeyError(f"prompt_version_not_found: {prompt_version_id}")
        persona = sub(version, "persona")
        voice = sub(version, "voice")
        guardrails = sub(version, "guardrails")
        raw_tuning = sub(version, "tuning")
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
            "flow": sub(version, "flow"),
            "promptVersion": version,
            # Without these the sandbox ran a draft with no skills prefix and no
            # card tool-gating, while the live path had both — so "test in
            # sandbox" did not exercise what publish was about to ship.
            "agentCard": sub(version, "agentCard"),
            "botId": version.get("botId"),
            "frozenTools": None,
            "compiled": version.get("compiled") if isinstance(version.get("compiled"), dict) else None,
            "bundleHash": None,
        }
    return load_active_bundle(
        environment,
        bot_id=bot_id,
        fallback_environments=fallback_environments,
    )
