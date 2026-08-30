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

    from voice.call_trace import Stopwatch, event, redact_url

    await client.accept()
    upstream = voice_ws_upstream()
    logger.info("Voice WS proxy → %s", upstream)
    watch = Stopwatch()

    try:
        async with websockets.connect(
            upstream,
            max_size=8 * 1024 * 1024,
            open_timeout=10,
            ping_interval=20,
            ping_timeout=20,
        ) as server:
            # The upstream leg opened. Timed because a slow connect here is
            # indistinguishable from a slow pipeline downstream, and they have
            # different fixes.
            event("ws.upstream_open", upstream=redact_url(upstream), took_s=watch.s())
            # Why these are counted and logged at WARNING rather than DEBUG:
            # a bridge that dies silently presents as a connected call with no
            # audio. Twilio holds the PSTN leg open, every status callback
            # reports a healthy call, and the only party who knows is the person
            # listening to silence. The direction and the frame counts are the
            # difference between "the bot never spoke" and "the bot spoke and we
            # dropped it".
            counts = {"c2s": 0, "s2c": 0}

            async def client_to_server() -> None:
                try:
                    while True:
                        msg = await client.receive()
                        if msg.get("type") == "websocket.disconnect":
                            logger.warning(
                                "voice ws: caller hung up after %d/%d frames",
                                counts["c2s"], counts["s2c"],
                            )
                            break
                        if "text" in msg and msg["text"] is not None:
                            await server.send(msg["text"])
                            counts["c2s"] += 1
                        elif "bytes" in msg and msg["bytes"] is not None:
                            await server.send(msg["bytes"])
                            counts["c2s"] += 1
                except WebSocketDisconnect:
                    logger.warning(
                        "voice ws: caller disconnected after %d/%d frames",
                        counts["c2s"], counts["s2c"],
                    )
                except Exception:
                    logger.warning(
                        "voice ws: caller→bot leg failed after %d/%d frames",
                        counts["c2s"], counts["s2c"], exc_info=True,
                    )

            async def server_to_client() -> None:
                try:
                    async for message in server:
                        if isinstance(message, bytes):
                            await client.send_bytes(message)
                        else:
                            await client.send_text(message)
                        counts["s2c"] += 1
                except ConnectionClosed:
                    logger.warning(
                        "voice ws: bot closed the socket after %d/%d frames",
                        counts["c2s"], counts["s2c"],
                    )
                except Exception:
                    logger.warning(
                        "voice ws: bot→caller leg failed after %d/%d frames",
                        counts["c2s"], counts["s2c"], exc_info=True,
                    )

            c2s = asyncio.create_task(client_to_server(), name="voice-ws-c2s")
            s2c = asyncio.create_task(server_to_client(), name="voice-ws-s2c")
            done, pending = await asyncio.wait(
                [c2s, s2c], return_when=asyncio.FIRST_COMPLETED
            )
            # WARNING, not INFO, and deliberately so: this module's INFO records
            # do not reach the API's log at all (root sits at WARNING), which is
            # how the original failure managed to leave no trace anywhere. One
            # line per call is not noise — it is the only record that the audio
            # path existed, and which end let go of it first.
            first = "caller→bot" if c2s in done else "bot→caller"
            event(
                "ws.closed",
                first=first,
                inbound_frames=counts["c2s"],
                outbound_frames=counts["s2c"],
                open_s=watch.s(),
            )
            logger.warning(
                "voice ws bridge closed · first=%s · caller→bot=%d bot→caller=%d",
                first, counts["c2s"], counts["s2c"],
            )
            for t in pending:
                t.cancel()
            # A cancelled task that never gets awaited logs "Task exception was
            # never retrieved" at interpreter shutdown and hides anything real.
            await asyncio.gather(*pending, return_exceptions=True)
    except Exception as exc:
        event(
            "ws.upstream_failed",
            upstream=redact_url(upstream),
            error=type(exc).__name__,
            took_s=watch.s(),
        )
        logger.exception("Voice WS proxy failed connecting to %s", upstream)
        try:
            await client.close(code=1011)
        except Exception:
            pass
