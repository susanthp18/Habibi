"""Proxy Twilio / Pipecat WebSocket ``/ws`` from the API (:8000) to the voice runner (:7860).

Lets a single ngrok tunnel (WhatsApp + Twilio) reach Media Streams without a
second tunnel. Voice still listens on 7860 locally; the API bridges the socket.
"""

from __future__ import annotations

import asyncio
import logging
import os

from fastapi import WebSocket, WebSocketDisconnect

from env_loader import load_env

logger = logging.getLogger(__name__)


def voice_ws_upstream() -> str:
    load_env()
    # Prefer explicit override; docker compose sets VOICE_RUNNER_URL=http://voice:7860
    base = (os.getenv("VOICE_WS_UPSTREAM") or os.getenv("VOICE_RUNNER_URL") or "http://127.0.0.1:7860").rstrip("/")
    if base.startswith("https://"):
        return "wss://" + base[len("https://") :] + "/ws"
    if base.startswith("http://"):
        return "ws://" + base[len("http://") :] + "/ws"
    if base.startswith("wss://") or base.startswith("ws://"):
        return base if base.endswith("/ws") else base + "/ws"
    return f"ws://{base}/ws"


def ws_proxy_enabled() -> bool:
    load_env()
    raw = (os.getenv("VOICE_WS_VIA_API") or "true").strip().lower()
    return raw in {"1", "true", "yes", "on", ""}


async def proxy_voice_websocket(client: WebSocket) -> None:
    """Bidirectional byte/text bridge between Twilio (via ngrok→API) and Pipecat."""
    import websockets
    from websockets.exceptions import ConnectionClosed

    await client.accept()
    upstream = voice_ws_upstream()
    logger.info("Voice WS proxy → %s", upstream)

    try:
        async with websockets.connect(
            upstream,
            max_size=8 * 1024 * 1024,
            open_timeout=10,
            ping_interval=20,
            ping_timeout=20,
        ) as server:
            async def client_to_server() -> None:
                try:
                    while True:
                        msg = await client.receive()
                        if msg.get("type") == "websocket.disconnect":
                            break
                        if "text" in msg and msg["text"] is not None:
                            await server.send(msg["text"])
                        elif "bytes" in msg and msg["bytes"] is not None:
                            await server.send(msg["bytes"])
                except WebSocketDisconnect:
                    pass
                except Exception:
                    logger.debug("client→server closed", exc_info=True)

            async def server_to_client() -> None:
                try:
                    async for message in server:
                        if isinstance(message, bytes):
                            await client.send_bytes(message)
                        else:
                            await client.send_text(message)
                except ConnectionClosed:
                    pass
                except Exception:
                    logger.debug("server→client closed", exc_info=True)

            done, pending = await asyncio.wait(
                [
                    asyncio.create_task(client_to_server()),
                    asyncio.create_task(server_to_client()),
                ],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()
    except Exception:
        logger.exception("Voice WS proxy failed connecting to %s", upstream)
        try:
            await client.close(code=1011)
        except Exception:
            pass
