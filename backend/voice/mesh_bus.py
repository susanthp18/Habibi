"""Redis / local bus for multi-agent role events.

Uses Pipecat ``RedisBus`` when ``REDIS_URL`` is set; otherwise an in-process
async queue. Role activation is still driven by Flows pre_actions — the bus
broadcasts so other workers / Floor UI can observe specialist handoffs.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from voice import config as voice_config
from voice.mesh import ROLES, activate_role, enabled, status

logger = logging.getLogger(__name__)

CHANNEL = "bigbound.voice.mesh"

_bus: Any | None = None
_bus_lock = asyncio.Lock()


async def get_bus() -> Any | None:
    """Lazy-init RedisBus or local queue bus. Returns None when mesh disabled."""
    global _bus
    if not enabled():
        return None
    async with _bus_lock:
        if _bus is not None:
            return _bus
        url = voice_config.redis_url()
        if url:
            client = None
            try:
                from redis.asyncio import Redis
                from pipecat.bus.network.redis import RedisBus

                # Publish-only: do not call RedisBus.start() here — that
                # requires a TaskManager owned by WorkerRunner. publish()
                # uses redis.publish and works without the reader loop.
                client = Redis.from_url(url, decode_responses=False)
                _bus = RedisBus(redis=client, channel=CHANNEL)
                logger.info("voice mesh RedisBus (publish) · channel=%s", CHANNEL)
            except Exception:
                logger.exception("RedisBus init failed — falling back to local")
                if client is not None:
                    try:
                        await client.aclose()
                    except Exception:
                        try:
                            await client.close()
                        except Exception:
                            pass
                _bus = _LocalBus()
        else:
            _bus = _LocalBus()
        return _bus


class _LocalBus:
    """Minimal pub/sub for single-process mesh demos."""

    def __init__(self) -> None:
        self._subs: list[asyncio.Queue] = []

    async def publish(self, channel: str, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload)
        for q in list(self._subs):
            try:
                q.put_nowait({"channel": channel, "data": raw})
            except Exception:
                pass

    async def subscribe(self, channel: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=64)
        self._subs.append(q)
        return q


async def publish_role_change(role: str, *, session_id: str | None = None) -> None:
    if not enabled():
        return
    bus = await get_bus()
    if bus is None:
        return
    payload = {
        "type": "mesh.role",
        "role": role,
        "sessionId": session_id,
        "roles": list(ROLES.keys()),
    }
    try:
        if isinstance(bus, _LocalBus):
            await bus.publish(CHANNEL, payload)
        else:
            from pipecat.bus.messages import BusJobStreamDataMessage

            await bus.publish(
                BusJobStreamDataMessage(
                    job_id=session_id or "voice-mesh",
                    data=payload,
                    source="voice.mesh",
                )
            )
        logger.debug("mesh published role=%s session=%s", role, session_id)
    except Exception:
        logger.exception("mesh publish failed")


async def activate_and_publish(
    role: str,
    *,
    session_id: str | None = None,
    customer_id: str | None = None,
    interaction_id: str | None = None,
    bot_id: str | None = None,
) -> str:
    """Activate a mesh role and announce it.

    ``customer_id`` is per-call: the process-wide MESH_CUSTOMER_ID env fallback
    made every concurrent call activate the insurance worker against the same
    customer, so a second caller's sidecar answered with the first caller's CRM
    context.

    ``interaction_id`` and ``bot_id`` travel with it so anything the specialist
    writes is attributable to the call that triggered it. Without them a
    mesh-captured lead had no source call, no lead_captured event and no
    upsell_presented flag — invisible to every analytic that matters.
    """
    active = activate_role(role, session_id)
    await publish_role_change(active, session_id=session_id)
    # Cross-process activate for the insurance LLMWorker sidecar.
    if active == "insurance":
        try:
            bus = await get_bus()
            if bus is not None and not isinstance(bus, _LocalBus):
                from pipecat.bus.messages import BusActivateWorkerMessage

                await bus.publish(
                    BusActivateWorkerMessage(
                        args={
                            "sessionId": session_id,
                            "role": active,
                            "customerId": customer_id or os.getenv("MESH_CUSTOMER_ID") or "",
                            "interactionId": interaction_id or "",
                            "botId": bot_id or "",
                        },
                        source="voice.collections",
                        target="insurance",
                    )
                )
        except Exception:
            logger.exception("BusActivateWorkerMessage publish failed")
    return active


def mesh_status(session_id: str | None = None) -> dict[str, Any]:
    st = status(session_id)
    st["channel"] = CHANNEL
    return st
