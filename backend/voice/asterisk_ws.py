"""Asterisk media WebSocket -- dedicated route, explicit transport.

Pipecat's ``create_transport`` does not detect Asterisk, so ``/ws/asterisk``
builds ``FastAPIWebsocketTransport`` with the owned serializer. Asterisk dials
this per call from the ``habibi_bot`` websocket_client, when the ARI controller
creates the call's media channel.

Auth is HTTP Basic (``ASTERISK_WS_USER`` / ``ASTERISK_WS_PASSWORD``, the same pair
rendered into ``websocket_client.conf``). It used to be a path segment, which put
the secret in every access-log line.
"""

from __future__ import annotations

import base64
import binascii
import logging
import secrets
from typing import Any

# Module level, not inside the handler: this file uses postponed annotations, and
# FastAPI resolves them against module globals. A local import leaves `WebSocket`
# unresolvable, FastAPI treats the parameter as a required query field, and every
# Asterisk connection is refused with 403.
from starlette.websockets import WebSocket

logger = logging.getLogger(__name__)

ROUTE = "/ws/asterisk"


def _credentials() -> tuple[str, str]:
    from env_loader import env_str, load_env

    load_env()
    return env_str("ASTERISK_WS_USER"), env_str("ASTERISK_WS_PASSWORD")


def asterisk_ws_authorized(websocket: Any) -> bool:
    user, password = _credentials()
    if not (user and password):
        logger.error("Asterisk WS rejected: ASTERISK_WS_USER / ASTERISK_WS_PASSWORD not configured")
        return False
    header = (websocket.headers.get("authorization") or "").strip()
    scheme, _, encoded = header.partition(" ")
    if scheme.lower() != "basic" or not encoded:
        logger.warning("Asterisk WS rejected: no Basic credentials")
        return False
    try:
        given_user, _, given_password = base64.b64decode(encoded).decode("utf-8").partition(":")
    except (binascii.Error, UnicodeDecodeError):
        logger.warning("Asterisk WS rejected: malformed Basic credentials")
        return False
    ok = secrets.compare_digest(given_user.encode(), user.encode()) & secrets.compare_digest(
        given_password.encode(), password.encode()
    )
    if not ok:
        logger.warning("Asterisk WS rejected: wrong credentials")
    return bool(ok)


def asterisk_transport_params(call_data: Any = None, serializer: Any = None) -> Any:
    """Asterisk media params. Hangup sends no trailing silence."""
    from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams

    from voice.asterisk_serializer import AsteriskFrameSerializer

    return FastAPIWebsocketParams(
        audio_in_enabled=True,
        audio_out_enabled=True,
        audio_out_end_silence_secs=0,
        serializer=serializer or AsteriskFrameSerializer(),
        # chan_websocket plays whole frames of optimal_frame_size (640 bytes =
        # 20 ms of slin16); send exactly that rather than TTS chunk sizes.
        fixed_audio_packet_size=getattr(call_data, "optimal_frame_size", 0) or None,
    )


def build_asterisk_transport(runner_args: Any) -> Any:
    from pipecat.transports.websocket.fastapi import FastAPIWebsocketTransport

    from voice.asterisk_serializer import AsteriskFrameSerializer

    serializer = getattr(runner_args, "asterisk_serializer", None) or AsteriskFrameSerializer()
    call_data = getattr(runner_args, "call_data", None)
    return FastAPIWebsocketTransport(
        websocket=runner_args.websocket,
        params=asterisk_transport_params(call_data, serializer),
    )


async def run_asterisk_websocket_session(websocket: Any) -> None:
    from pipecat.runner.types import WebSocketRunnerArguments

    from voice.asterisk_serializer import (
        AsteriskFrameSerializer,
        call_data_from_media_start,
        parse_text_event,
    )
    from voice.bot import bot

    await websocket.accept()
    first = await websocket.receive()
    if first.get("type") == "websocket.disconnect":
        return
    payload = parse_text_event(first.get("text") or "")
    if str(payload.get("event") or "").upper() != "MEDIA_START":
        logger.error("asterisk WS: first message was not MEDIA_START; closing")
        await websocket.close(code=1002)
        return
    call_data = call_data_from_media_start(payload)

    serializer = AsteriskFrameSerializer(sample_rate=call_data.sample_rate)
    serializer.call_data = call_data
    runner_args = WebSocketRunnerArguments(websocket=websocket)
    runner_args.transport_type = "asterisk"
    runner_args.call_data = call_data
    runner_args.asterisk_serializer = serializer
    runner_args.prebuilt_transport = build_asterisk_transport(runner_args)
    arrived = getattr(getattr(websocket, "state", None), "ws_arrived_at", None)
    if arrived is not None:
        runner_args.ws_arrived_at = arrived

    try:
        from voice.host import embedded_host_enabled, get_runner

        if embedded_host_enabled():
            runner_args.handle_sigint = False
            runner_args.shared_runner = await get_runner()
    except Exception:
        logger.debug("asterisk WS: embedded host not attached", exc_info=True)

    await bot(runner_args)


def register_asterisk_runner_routes(app: Any) -> None:
    """Mount ``/ws/asterisk`` *before* Pipecat's ``/ws/{token}`` catch-all."""

    async def _asterisk_ws(websocket: WebSocket) -> None:
        import time as _time

        try:
            websocket.state.ws_arrived_at = _time.monotonic()
        except Exception:
            pass
        if not asterisk_ws_authorized(websocket):
            await websocket.close(code=1008, reason="unauthorized")
            return
        await run_asterisk_websocket_session(websocket)

    # Starlette matches in registration order: the literal path must come first.
    app.websocket(ROUTE)(_asterisk_ws)
    logger.info("Asterisk media WS: %s mounted", ROUTE)


def install_runner_hook() -> None:
    """Patch Pipecat's telephony route setup so ``/ws/asterisk`` is registered first."""
    try:
        from pipecat.runner import run as runner_mod
    except Exception:
        logger.debug("pipecat.runner unavailable -- asterisk WS hook skipped")
        return
    orig = getattr(runner_mod, "_setup_telephony_routes", None)
    if orig is None or getattr(orig, "_habibi_asterisk", False):
        return

    def wrapped(app, *args, **kwargs):  # noqa: ANN001
        from voice.sandbox_ws import register_sandbox_ws_route

        from voice.llm_pool import install_serving_loop_warmers

        register_asterisk_runner_routes(app)
        # The browser's Sandbox Live socket rides the same hook: this is the
        # one place the runner's app is handed to us before it serves.
        register_sandbox_ws_route(app)
        # And so does the LLM warm-up, which must happen on the serving loop.
        install_serving_loop_warmers(app)
        return orig(app, *args, **kwargs)

    wrapped._habibi_asterisk = True  # type: ignore[attr-defined]
    runner_mod._setup_telephony_routes = wrapped
