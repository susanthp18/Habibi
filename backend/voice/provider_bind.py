"""Bind a live call's STT/TTS through the provider registry.

``voice/bot.py`` constructed ``AzureSTTService`` and ``KeepAliveAzureTTSService``
directly. The registry, the capability matrix and the binding UI all worked, and
none of it reached a call: an operator could pick Cartesia in the Agent Studio,
hear the preview, publish it, and every real call still ran Azure. A studio that
configures something the runtime ignores is worse than no studio, because the
screen asserts a fact about the system that is false.

This module is the seam. Two decisions in it are worth stating, because both are
places where the obvious implementation is wrong in opposite directions.

**An unbound slot is not an error.** :mod:`agent_core.providers.factory` raises
``NoBindingError`` rather than substituting a default, and that is right *there*
— its rule exists because substituting an ``en-IN`` recogniser for an unmapped
locale produced fluent nonsense that scored as the caller's words. But "this
tenant has not configured a provider yet" is a different fact from "this locale
is unservable", and answering it by dropping every call would make deploying the
registry an outage. Unbound falls back to the Azure path that ran before this
module existed.

**A bound-but-broken slot falls back too, and says so.** If an operator bound
Cartesia and Cartesia is down, they get Azure and an ERROR in the log — not a
dead collections call. The fallback is not silent: every bind records what was
asked for and what actually ran on ``session.extra["providers"]``, so the
transcript and the CRM record cannot claim a provider that never spoke.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

#: What ran, per slot. Written to ``session.extra["providers"]``.
Provenance = dict[str, Any]


def bind(
    slot: str,
    *,
    tenant_id: str,
    bot_id: str | None,
    locale: str | None,
    session_id: str | None,
    fallback: Callable[[], Any],
    settings: dict[str, Any] | None = None,
    ctor: dict[str, Any] | None = None,
) -> tuple[Any, Provenance]:
    """Return ``(service, provenance)`` for one pipeline slot.

    ``fallback`` builds the pre-registry Azure service and is called only when
    the registry cannot supply one. It is a callable rather than a value so the
    Azure service is not constructed — and its websocket not opened — on the
    common path where a binding exists.
    """
    from agent_core.providers import factory

    try:
        service, binding = factory.build_first_available(
            tenant_id=tenant_id,
            slot=slot,
            bot_id=bot_id,
            locale=locale,
            session_id=session_id,
            ctor=ctor,
            **(settings or {}),
        )
    except factory.NoBindingError:
        # Expected on any tenant that has not opened the Agent Studio yet.
        logger.info(
            "no %s binding for tenant=%s bot=%s locale=%s — using the Azure default",
            slot,
            tenant_id,
            bot_id,
            locale,
        )
        return fallback(), {"slot": slot, "provider": "azure", "source": "default"}
    except Exception as exc:  # noqa: BLE001 - a live call outlives any provider
        # Bound, but nothing in the chain could be built. Falling back keeps the
        # call up; the ERROR and the provenance record keep it from being a lie.
        logger.error(
            "%s binding unavailable for tenant=%s bot=%s locale=%s (%s) — "
            "falling back to Azure so the call survives",
            slot,
            tenant_id,
            bot_id,
            locale,
            exc,
        )
        return fallback(), {
            "slot": slot,
            "provider": "azure",
            "source": "fallback",
            "error": str(exc)[:200],
        }

    logger.info(
        "%s bound · provider=%s · model=%s · locale=%s",
        slot,
        binding.provider_id,
        binding.model_id,
        locale,
    )
    return service, {
        "slot": slot,
        "provider": binding.provider_id,
        "model": binding.model_id,
        "bindingId": binding.binding_id,
        "source": "binding",
        "locale": binding.locale,
    }


def record(session: Any, provenance: Provenance) -> None:
    """Stamp ``provenance`` onto the session so downstream records agree.

    Analytics attributes cost and latency per provider. Without this it would
    read the *configured* provider from the binding table and attribute a call
    that actually fell back to Azure against Cartesia's numbers.
    """
    try:
        slots = session.extra.setdefault("providers", {})
        slots[provenance["slot"]] = provenance
    except Exception:  # noqa: BLE001 - provenance must never break a call
        logger.debug("could not record provider provenance", exc_info=True)
