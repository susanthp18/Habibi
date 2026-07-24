"""Redis / local bus for multi-agent role events.

Uses Pipecat ``RedisBus`` when ``REDIS_URL`` is set; otherwise an in-process
async queue. Role activation is still driven by Flows pre_actions — the bus
broadcasts so other workers / Floor UI can observe specialist handoffs.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from voice import config as voice_config
from voice.mesh import ROLES, activate_role, enabled, status

logger = logging.getLogger(__name__)

CHANNEL = "bigbound.voice.mesh"

_bus: Any | None = None
_bus_lock = asyncio.Lock()
_listeners: list[asyncio.Queue] = []


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
            try:
                from redis.asyncio import Redis
                from pipecat.bus.network.redis import RedisBus

                client = Redis.from_url(url, decode_responses=False)
                _bus = RedisBus(redis=client, channel=CHANNEL)
                if hasattr(_bus, "start"):
                    maybe = _bus.start()
                    if asyncio.iscoroutine(maybe):
                        await maybe
                logger.info("voice mesh RedisBus connected · channel=%s", CHANNEL)
            except Exception:
                logger.exception("RedisBus init failed — falling back to local")
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


async def activate_and_publish(role: str, *, session_id: str | None = None) -> str:
    active = activate_role(role)
    await publish_role_change(active, session_id=session_id)
    # Cross-process activate for the insurance LLMWorker sidecar.
    if active == "insurance":
        try:
            bus = await get_bus()
            if bus is not None and not isinstance(bus, _LocalBus):
                from pipecat.bus.messages import BusActivateWorkerMessage

                await bus.publish(
                    BusActivateWorkerMessage(
                        args={"sessionId": session_id, "role": active},
                        source="voice.collections",
                        target="insurance",
                    )
                )
        except Exception:
            logger.exception("BusActivateWorkerMessage publish failed")
    return active


def mesh_status() -> dict[str, Any]:
    st = status()
    st["channel"] = CHANNEL
    return st
