"""Sandbox Live over a WebSocket -- the browser voice path that needs no UDP.

SmallWebRTC needs a signalling route *and* a UDP media path. On a server
behind nginx and a cloud firewall there was neither: ``/voice-rtc`` fell to the
marketing site, and with no STUN/TURN the media could not have flowed anyway.
Audio over one WebSocket on 443 rides the same proxy the phone calls use, and
works behind a bank's corporate proxy too.

Auth is a single-use ticket. It rides in the path because a browser cannot put
a header on a WebSocket, so uvicorn's access line prints it -- by then it has
been redeemed, and a logged ticket is a spent one. ``voice_sandbox.start_voice_sandbox`` -- reached
only through the signed-in API -- mints it, stores its sha256 on the session,
and hands the browser ``/ws-sandbox/{session_id}/{ticket}``. This route consumes
it atomically in the shared session store, so a URL that leaks from a log or a
browser history opens nothing: it has been used, or it has expired.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import secrets
import time
from typing import Any

# Module level, not inside the route factory: under `from __future__ import
# annotations` FastAPI resolves the handler's `WebSocket` annotation from this
# module's globals. Imported locally it did not resolve, the socket parameter
# was treated as a missing query value, and every handshake was refused 403
# before the handler ran.
from starlette.websockets import WebSocket

logger = logging.getLogger(__name__)

ROUTE = "/ws-sandbox/{session_id}/{ticket}"
PATH_PREFIX = "/ws-sandbox"
#: Long enough for a slow microphone permission prompt, short enough that a
#: leaked URL is dead before anyone reads it.
TICKET_TTL_SECS = 120.0
#: The browser records at 16 kHz and plays at 24 kHz (the client transport's
#: defaults); the pipeline is pinned to the same so nothing resamples twice.
IN_SAMPLE_RATE = 16000
OUT_SAMPLE_RATE = 24000


def mint_ticket() -> tuple[str, dict[str, Any]]:
    """A fresh ticket, and the session fields that make it redeemable once."""
    ticket = secrets.token_urlsafe(24)
    return ticket, {
        "wsTicketHash": hashlib.sha256(ticket.encode()).hexdigest(),
        "wsTicketExpiresAt": time.time() + TICKET_TTL_SECS,
    }


def consume_ticket(session_id: str, ticket: str) -> str | None:
    """Redeem ``ticket`` for ``session_id``. None on success, else why not.

    Runs inside the store's exclusive section, so two sockets racing on one
    ticket cannot both win. Blocking -- call it through ``asyncio.to_thread``.
    """
    import voice_session_store

    digest = hashlib.sha256(ticket.encode()).hexdigest()
    outcome: dict[str, str | None] = {"reason": "session_not_found"}

    def redeem(cur: dict[str, Any]) -> dict[str, Any]:
        stored = str(cur.get("wsTicketHash") or "")
        if not stored or not hmac.compare_digest(stored, digest):
            outcome["reason"] = "ticket_invalid_or_used"
            return cur
        spent = {**cur, "wsTicketHash": None}
        if time.time() > float(cur.get("wsTicketExpiresAt") or 0):
            outcome["reason"] = "ticket_expired"
            return spent
        if cur.get("status") == "stopped":
            outcome["reason"] = "session_stopped"
            return spent
        outcome["reason"] = None
        return {**spent, "wsTicketUsedAt": time.time()}

    voice_session_store.mutate(session_id, redeem)
    return outcome["reason"]


def build_transport(websocket: Any) -> Any:
    from pipecat.serializers.protobuf import ProtobufFrameSerializer
    from pipecat.transports.websocket.fastapi import (
        FastAPIWebsocketParams,
        FastAPIWebsocketTransport,
    )

    return FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            audio_in_sample_rate=IN_SAMPLE_RATE,
            audio_out_sample_rate=OUT_SAMPLE_RATE,
            audio_out_end_silence_secs=0,
            add_wav_header=False,
            serializer=ProtobufFrameSerializer(),
        ),
    )


async def run_sandbox_ws_session(websocket: Any, session_id: str, ticket: str) -> None:
    """Redeem the ticket, then run the ordinary bot on this socket."""
    from pipecat.runner.types import WebSocketRunnerArguments

    import voice_session_store
    from voice.bot import bot

    reason: str | None
    if not voice_session_store.is_session_id(session_id):
        reason = "invalid_session_id"
    else:
        try:
            reason = await asyncio.to_thread(consume_ticket, session_id, ticket)
        except voice_session_store.SessionStoreUnavailable:
            logger.exception("sandbox ws: session store unavailable for %s", session_id)
            reason = "store_unavailable"
    if reason:
        # WARNING: the only trace of a browser that could not connect.
        logger.warning("sandbox ws refused · session=%s · reason=%s", session_id, reason)
        await websocket.close(code=4003, reason=reason)
        return

    await websocket.accept()
    logger.info("sandbox ws accepted · session=%s", session_id)
    runner_args = WebSocketRunnerArguments(
        websocket=websocket, transport_type="websocket", session_id=session_id
    )
    runner_args.prebuilt_transport = build_transport(websocket)
    arrived = getattr(getattr(websocket, "state", None), "ws_arrived_at", None)
    if arrived is not None:
        runner_args.ws_arrived_at = arrived
    try:
        from voice.host import embedded_host_enabled, get_runner

        if embedded_host_enabled():
            runner_args.handle_sigint = False
            runner_args.shared_runner = await get_runner()
    except Exception:
        logger.debug("sandbox ws: embedded host not attached", exc_info=True)
    await bot(runner_args)


def register_sandbox_ws_route(app: Any) -> None:
    async def _sandbox_ws(websocket: WebSocket, session_id: str, ticket: str) -> None:
        websocket.state.ws_arrived_at = time.monotonic()
        await run_sandbox_ws_session(websocket, session_id, ticket)

    app.websocket(ROUTE)(_sandbox_ws)
    logger.info("Sandbox browser WS: %s mounted", PATH_PREFIX)
