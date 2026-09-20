"""Owns every Asterisk call from first ring to the recording upload.

    python -m voice.asterisk_controller

Why this exists
---------------
Calls used to go dialplan -> ``Dial(WebSocket/...)``. Nothing Habibi ran saw the
call, so: the bot never learned who was calling or which attempt it was
(dialplan variables do not reach the media channel), attempts never left
``dialing`` (no status source), transfer returned 409 (``continue`` needs a
Stasis channel) and the recording was looked up under the wrong channel id.

Now every call enters the ``habibi`` Stasis application and this process, one per
PBX, drives it over ARI:

* **inbound** -- a softphone or the trunk hits ``Stasis(habibi,inbound)``;
* **outbound** -- ``asterisk_ops.originate`` creates the SIP leg inside the app.

For each call: bring up the bot's media leg (a Local channel into the dialplan's
``Dial(WebSocket/habibi_bot)``, carrying ``HABIBI_CTX`` as an inherited channel
variable), answer only once that leg is up, bridge the two, record
the bridge, turn the SIP leg's hangup cause into the attempt's final state, and
upload the recording as ``sip_audio``.

Ids are derived, never looked up: SIP leg ``S`` (``att-<attempt>`` when we dialled),
media leg ``S-m``, bridge ``br-S``, recording ``S``.

ponytail: call state is in memory. A controller restart forgets in-flight calls;
on connect it hangs up any ``habibi`` channel it does not know. Upgrade path for
HA: persist ``Call`` rows and re-adopt instead of hanging up.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from env_utils import env_int, env_str
from voice import asterisk_ops as ops

logger = logging.getLogger(__name__)

#: How long the bot's media socket may take to come up before the call is refused.
MEDIA_TIMEOUT_S = float(env_int("ASTERISK_MEDIA_TIMEOUT_S", 10))
#: Set by ``asterisk_ops.warm_transfer`` just before it moves the caller out.
TRANSFER_VARIABLE = ops.TRANSFER_VARIABLE
HEALTH_PORT = env_int("ASTERISK_CONTROLLER_HEALTH_PORT", 8090)
#: A refusal can beat the dialer's own write of the channel id onto the attempt.
STATUS_WRITE_TRIES = 6
STATUS_WRITE_WAIT_S = 2.0

# Q.850 causes, grouped by what they mean for an attempt.
_BUSY = {17}
_NO_ANSWER = {18, 19}
_REJECTED = {21}
_NORMAL = {16, 31}


def status_for(cause: int | None, *, answered: bool) -> str:
    """The attempt status for a SIP leg that ended with ``cause``.

    Spelled in the carrier-status vocabulary ``outbound.apply_provider_status``
    already maps, so there is one state machine for every provider.
    """
    if answered:
        return "completed"
    if cause in _BUSY:
        return "busy"
    if cause in _NO_ANSWER or cause in _NORMAL:
        # Ring timeout and a caller who hung up before answer both clear normally.
        return "no-answer"
    if cause in _REJECTED:
        return "rejected"
    return "failed"


@dataclass
class Call:
    sip_id: str
    direction: str
    ctx: dict[str, str] = field(default_factory=dict)
    answered_at: float | None = None
    media_up: bool = False
    bridged: bool = False
    transferring: bool = False
    finished: bool = False
    recorded: bool = False
    #: Bot media never came up; apology played and the attempt is retryable.
    bot_unreachable: bool = False
    #: Bridge recording never started; disclosure+callback then hangup.
    recording_unavailable: bool = False
    #: Q.850 cause, which only ChannelHangupRequest carries.
    hangup_cause: int | None = None


def _default_status_writer(**kwargs: Any) -> Any:
    import db_outbound

    return db_outbound.apply_provider_status(**kwargs)


def _default_mark_transferred(attempt_id: str) -> None:
    import db
    import outbound

    with db.engine.begin() as conn:
        outbound.mark(conn, attempt_id, state=outbound.STATE_TRANSFERRED)


def _default_store_recording(sip_id: str, wav: bytes) -> str | None:
    """Upload the call recording and attach it to the call's interaction."""
    import db
    import storage
    from sqlalchemy import text

    from voice import persist

    interaction_id = None
    # The voice process writes voice_sessions when the bot connects; the recording
    # finishes after hangup, so the row is normally there. Allow for a slow writer.
    for _ in range(15):
        with db.engine.connect() as conn:
            interaction_id = conn.execute(
                text("SELECT interaction_id FROM voice_sessions WHERE provider_call_id = :sid"),
                {"sid": sip_id},
            ).scalar()
        if interaction_id:
            break
        time.sleep(2)
    if not interaction_id:
        logger.error("recording %s: no voice_sessions row for this call; not stored", sip_id)
        return None
    key = f"recordings/{db.current_tenant()}/sip/{sip_id}.wav"
    ref = storage.put_bytes(key, wav, "audio/wav", bucket=storage.RECORDINGS_BUCKET)
    return persist.record_media(
        interaction_id=interaction_id,
        kind="sip_audio",
        storage_ref=ref,
        duration_sec=None,
        mime_type="audio/wav",
        size_bytes=len(wav),
        content_hash=hashlib.sha256(wav).hexdigest(),
    )


class Controller:
    def __init__(
        self,
        *,
        ari: Callable[..., Any] = ops.ari,
        status_writer: Callable[..., None] = _default_status_writer,
        mark_transferred: Callable[[str], None] = _default_mark_transferred,
        store_recording: Callable[[str, bytes], Any] = _default_store_recording,
        agents_available: bool | None = None,
    ) -> None:
        self._ari = ari
        self._write_status = status_writer
        self._mark_transferred = mark_transferred
        self._store_recording = store_recording
        self._agents = (
            bool(env_str("ASTERISK_AGENT_EXTENSIONS")) if agents_available is None else agents_available
        )
        self.calls: dict[str, Call] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    # -- plumbing -----------------------------------------------------------

    async def _call_ari(self, *args: Any, **kwargs: Any) -> Any:
        return await asyncio.to_thread(self._ari, *args, **kwargs)

    async def _quiet(self, *args: Any, **kwargs: Any) -> None:
        """An ARI request whose failure is expected (the channel is already gone)."""
        try:
            await self._call_ari(*args, **kwargs)
        except ops.AriError as exc:
            if exc.status not in (404, 409, 422):
                logger.warning("ari %s %s: %s", args[0], args[1], exc)

    async def _status(self, call: Call, status: str, **extra: Any) -> None:
        """Move the attempt to ``status``, waiting for the dialer if it has to.

        A call can be refused (busy, declined, unallocated number) before
        ``outbound.place`` has committed the channel id onto the attempt row. The
        write then matches nothing and the outcome is lost, which is how a busy
        borrower stayed "dialing". The id is derived from the attempt, so the row
        is certain to arrive: retry briefly rather than drop the only report of
        how this call ended.
        """
        if call.direction != "outbound":
            return
        for attempt in range(STATUS_WRITE_TRIES):
            try:
                written = await asyncio.to_thread(
                    self._write_status,
                    provider_call_id=call.sip_id,
                    status=status,
                    provider="asterisk",
                    duration_sec=extra.get("duration_sec"),
                    error_code=extra.get("error_code"),
                    answered_by=None,
                )
            except Exception:
                logger.exception("status %s for %s could not be written", status, call.sip_id)
                return
            if written is not None:
                return
            if attempt + 1 < STATUS_WRITE_TRIES:
                await asyncio.sleep(STATUS_WRITE_WAIT_S)
        logger.warning(
            "status %s for %s matched no attempt row -- an inbound call, or a dial that never recorded its id",
            status,
            call.sip_id,
        )

    @staticmethod
    def _sip_id_of(channel_id: str) -> tuple[str, bool]:
        """(SIP leg id, whether this channel is the bot's media leg).

        A Local channel is two halves, ``<id>;1`` and ``<id>;2``, and both report
        events; they belong to the same call as ``<id>``.
        """
        base = channel_id.split(";", 1)[0]
        if base.endswith("-m"):
            return base[:-2], True
        return base, False

    def _call_for(self, channel_id: str) -> Call | None:
        """The call this SIP-leg event belongs to.

        An outbound leg has events before it ever enters Stasis (ringing, or a
        refusal), so one is created on demand -- but only for a leg this process
        dialled. Anything else is another channel on the PBX, and inventing a call
        for it meant retrying a status write for an attempt that does not exist.
        """
        call = self.calls.get(channel_id)
        if call is None and channel_id.startswith(ops.OUTBOUND_ID_PREFIX):
            call = Call(sip_id=channel_id, direction="outbound")
            self.calls[channel_id] = call
        return call

    # -- events -------------------------------------------------------------

    def _release_if_done(self, call: Call) -> None:
        if call.finished and (call.recorded or not call.bridged):
            self.calls.pop(call.sip_id, None)
            self._locks.pop(call.sip_id, None)

    async def handle(self, event: dict[str, Any]) -> None:
        """One ARI event. Events for the same call run in order; calls run in parallel."""
        channel = event.get("channel") or {}
        key = str(channel.get("id") or (event.get("recording") or {}).get("name") or "")
        lock = self._locks.setdefault(self._sip_id_of(key)[0], asyncio.Lock())
        async with lock:
            await self._handle(event)

    async def _handle(self, event: dict[str, Any]) -> None:
        kind = event.get("type")
        channel = event.get("channel") or {}
        channel_id = str(channel.get("id") or "")
        logger.debug("event %s %s %s", kind, channel_id, event.get("cause", ""))
        try:
            if kind == "StasisStart":
                await self._on_stasis_start(event, channel)
            elif kind == "ChannelStateChange":
                sip_id, is_media = self._sip_id_of(channel_id)
                if not is_media and channel.get("state") == "Ringing":
                    call = self._call_for(sip_id)
                    if call is not None:
                        await self._status(call, "ringing")
            elif kind == "ChannelHangupRequest":
                sip_id, is_media = self._sip_id_of(channel_id)
                call = self.calls.get(sip_id)
                if call is not None and not is_media:
                    try:
                        call.hangup_cause = int(event.get("cause"))
                    except (TypeError, ValueError):
                        pass
            elif kind == "ChannelVarset" and event.get("variable") == TRANSFER_VARIABLE:
                if channel_id in self.calls:
                    self.calls[channel_id].transferring = True
            elif kind == "StasisEnd":
                await self._on_stasis_end(channel_id)
            elif kind == "ChannelDestroyed":
                await self._on_destroyed(channel_id, event.get("cause"))
            elif kind == "RecordingFinished":
                await self._on_recording_finished(str((event.get("recording") or {}).get("name") or ""))
            elif kind == "RecordingFailed":
                name = str((event.get("recording") or {}).get("name") or "")
                logger.error("recording failed for %s: %s", name, event.get("recording"))
                call = self.calls.get(name)
                if call is not None and not call.finished:
                    await self._recording_failed(call)
                elif call is not None:
                    call.recorded = True
                    self._release_if_done(call)
        except Exception:
            logger.exception("controller: %s for %s failed", kind, channel_id or "?")

    async def _on_stasis_start(self, event: dict[str, Any], channel: dict[str, Any]) -> None:
        channel_id = str(channel.get("id") or "")
        sip_id, is_media = self._sip_id_of(channel_id)
        if is_media:
            call = self.calls.get(sip_id)
            if call is None or call.finished:
                await self._quiet("DELETE", f"/channels/{channel_id}")
                return
            call.media_up = True
            await self._bridge(call)
            return

        args = event.get("args") or []
        direction = args[0] if args else ""
        if direction == "inbound":
            ctx = {
                "call_type": "inbound",
                "from": str((channel.get("caller") or {}).get("number") or ""),
                "to": str((channel.get("dialplan") or {}).get("exten") or ""),
                "sip_channel_id": sip_id,
            }
            call = Call(sip_id=sip_id, direction="inbound", ctx=ctx)
            self.calls[sip_id] = call
        elif direction == "outbound":
            call = self._call_for(sip_id) or Call(sip_id=sip_id, direction="outbound")
            self.calls[sip_id] = call
            call.answered_at = time.monotonic()
            await self._status(call, "in-progress")
            var = await self._call_ari(
                "GET", f"/channels/{sip_id}/variable", query={"variable": ops.CTX_VARIABLE}
            )
            try:
                call.ctx = json.loads(str((var or {}).get("value") or "{}"))
            except json.JSONDecodeError:
                call.ctx = {}
            call.ctx.setdefault("call_type", "outbound")
            call.ctx["sip_channel_id"] = sip_id
        else:
            logger.warning("StasisStart without a direction for %s; hanging up", sip_id)
            await self._quiet("DELETE", f"/channels/{sip_id}")
            return
        await self._start_media(call)

    async def _start_media(self, call: Call) -> None:
        """Bring up the bot's leg: a Local channel whose far end dials the bot.

        ``externalMedia`` with the websocket transport does create a chan_websocket
        channel, but such a channel is not in ARI's bridgeable registry: every
        ``addChannel`` and ``record`` naming it answers "Channel not found". The
        dialplan can reach it, so the media leg is ``Local/bot@to-bot`` and its far
        end runs ``Dial(WebSocket/habibi_bot)``. The Dial comes before any Answer,
        so this leg answering means the bot is really on the socket.

        Identity travels as an inherited variable on the *caller's* channel plus
        ``originator``: ARI copies ``__`` variables from the originator onto the new
        channel, and from there onto the Local's far end and the WebSocket channel,
        where the bot reads it out of MEDIA_START. Passing it as an originate
        variable instead reaches only the near end, and the bot sees an anonymous call.
        """
        try:
            await self._call_ari(
                "POST",
                f"/channels/{call.sip_id}/variable",
                query={"variable": f"__{ops.CTX_VARIABLE}", "value": json.dumps(call.ctx)},
            )
            await self._call_ari(
                "POST",
                "/channels",
                query={
                    "endpoint": ops.MEDIA_ENDPOINT,
                    "app": ops.APP,
                    "appArgs": "media",
                    "channelId": ops.media_channel_id(call.sip_id),
                    "originator": call.sip_id,
                    "timeout": int(MEDIA_TIMEOUT_S),
                },
            )
        except ops.AriError as exc:
            logger.error("bot media for %s could not start: %s", call.sip_id, exc)
            await self._media_failed(call)
            return
        asyncio.get_running_loop().call_later(
            MEDIA_TIMEOUT_S, lambda: asyncio.ensure_future(self._media_deadline(call.sip_id))
        )

    async def _media_deadline(self, sip_id: str) -> None:
        lock = self._locks.get(sip_id)
        if lock is None:
            return
        async with lock:
            await self._check_media_deadline(sip_id)

    async def _check_media_deadline(self, sip_id: str) -> None:
        call = self.calls.get(sip_id)
        if call is not None and not call.media_up and not call.finished:
            logger.error("bot media for %s did not connect in %.0fs", sip_id, MEDIA_TIMEOUT_S)
            await self._quiet("DELETE", f"/channels/{ops.media_channel_id(sip_id)}")
            await self._media_failed(call)

    async def _media_failed(self, call: Call) -> None:
        """The bot is unreachable. Never leave the caller answered in silence.

        Do not auto-transfer to collectors. Play a pre-recorded apology, hang up,
        and (on outbound) stamp a retryable ``bot_unreachable`` connection.
        """
        call.bot_unreachable = True
        try:
            if call.answered_at is None:
                await self._quiet("POST", f"/channels/{call.sip_id}/answer")
                call.answered_at = time.monotonic()
            await self._quiet(
                "POST",
                f"/channels/{call.sip_id}/play",
                query={"media": ops.UNREACHABLE_SOUND},
            )
        except Exception:
            logger.exception("unreachable apology playback failed for %s", call.sip_id)
        await self._quiet("DELETE", f"/channels/{call.sip_id}", query={"reason": "normal"})
        await self._finish(call, cause=None)

    async def _recording_failed(self, call: Call) -> None:
        """Tape never started. Disclose, offer a callback, hang up. No collections.

        Do not leave the caller in an unrecorded negotiation, and do not dump
        them to agents. Outbound stamps retryable ``recording_unavailable``.
        """
        if call.finished:
            return
        call.recording_unavailable = True
        await self._teardown_media(call)
        try:
            if call.answered_at is None:
                await self._quiet("POST", f"/channels/{call.sip_id}/answer")
                call.answered_at = time.monotonic()
            await self._quiet(
                "POST",
                f"/channels/{call.sip_id}/play",
                query={"media": ops.RECORDING_UNAVAILABLE_SOUND},
            )
        except Exception:
            logger.exception("recording-unavailable playback failed for %s", call.sip_id)
        await self._quiet("DELETE", f"/channels/{call.sip_id}", query={"reason": "normal"})
        await self._finish(call, cause=None)

    async def _bridge(self, call: Call) -> None:
        if call.direction == "inbound":
            await self._call_ari("POST", f"/channels/{call.sip_id}/answer")
            call.answered_at = time.monotonic()
        bridge = ops.bridge_id(call.sip_id)
        await self._call_ari("POST", "/bridges", query={"type": "mixing", "bridgeId": bridge})
        # One channel per request: ARI answers 204 for a repeated `channel`
        # parameter but only the last value actually joins, which left the caller
        # outside the bridge listening to silence.
        for channel_id in (call.sip_id, ops.media_channel_id(call.sip_id)):
            await self._call_ari("POST", f"/bridges/{bridge}/addChannel", query={"channel": channel_id})
        call.bridged = True
        # Recording starts with the conversation, so a refused call leaves no empty file.
        # A failed start is fail-closed: disclose, callback, hang up — never collect off-tape.
        try:
            await self._call_ari(
                "POST",
                f"/bridges/{bridge}/record",
                query={"name": call.sip_id, "format": "wav", "ifExists": "overwrite"},
            )
        except Exception:
            logger.exception("bridge recording did not start for %s", call.sip_id)
            await self._recording_failed(call)

    async def _teardown_media(self, call: Call) -> None:
        await self._quiet("DELETE", f"/channels/{ops.media_channel_id(call.sip_id)}")
        if call.bridged:
            await self._quiet("DELETE", f"/bridges/{ops.bridge_id(call.sip_id)}")

    async def _on_stasis_end(self, channel_id: str) -> None:
        """The caller's leg left the application.

        For a leg that entered Stasis this is the **last** event ARI sends: no
        ``ChannelDestroyed`` follows, because the channel is no longer the app's.
        Waiting for one left the bot talking to a hung-up line -- on a live call
        it ran on for two minutes, spending model calls on nobody -- and the
        attempt never reached a final state.
        """
        sip_id, is_media = self._sip_id_of(channel_id)
        call = self.calls.get(sip_id)
        if is_media or call is None:
            return
        if call.transferring:
            # Left alive, on its way to the agents queue.
            call.finished = True
            attempt_id = call.ctx.get("attempt_id")
            if attempt_id:
                try:
                    await asyncio.to_thread(self._mark_transferred, attempt_id)
                except Exception:
                    logger.exception("attempt %s could not be marked transferred", attempt_id)
            await self._teardown_media(call)
            return
        await self._finish(call, call.hangup_cause)

    async def _on_destroyed(self, channel_id: str, cause: Any) -> None:
        sip_id, is_media = self._sip_id_of(channel_id)
        if is_media:
            call = self.calls.get(sip_id)
            if call is None or call.finished:
                return
            if not call.media_up:
                await self._media_failed(call)
            elif not call.transferring:
                # The bot hung up (end of conversation): clear the caller too.
                await self._quiet("DELETE", f"/channels/{sip_id}", query={"reason": "normal"})
            return

        # A leg that never entered Stasis (an outbound dial nobody answered)
        # reports its end here instead; an answered one ends at StasisEnd above.
        call = self._call_for(sip_id)
        if call is None or call.transferring:
            return
        await self._finish(call, cause)

    async def _finish(self, call: Call, cause: Any) -> None:
        """Record how the call ended and release the bot's leg. Idempotent."""
        if call.finished:
            return
        call.finished = True
        try:
            code = int(cause) if cause is not None else None
        except (TypeError, ValueError):
            code = None
        answered = call.answered_at is not None
        duration = int(time.monotonic() - call.answered_at) if answered else None
        if call.bot_unreachable:
            status = "bot-unreachable"
            error_code = "bot_unreachable"
        elif call.recording_unavailable:
            status = "recording-unavailable"
            error_code = "recording_unavailable"
        else:
            status = status_for(code, answered=answered)
            error_code = f"q850:{code}" if code is not None else None
        await self._status(
            call,
            status,
            duration_sec=duration,
            error_code=error_code,
        )
        await self._teardown_media(call)
        self._release_if_done(call)

    async def _on_recording_finished(self, name: str) -> None:
        if not name:
            return
        call = self.calls.get(name)
        try:
            wav = await self._call_ari("GET", f"/recordings/stored/{name}/file", raw=True)
            stored = await asyncio.to_thread(self._store_recording, name, wav)
        except Exception:
            logger.exception("recording %s could not be stored; left on the PBX", name)
            stored = None
        if stored:
            await self._quiet("DELETE", f"/recordings/stored/{name}")
            logger.info("recording %s stored as %s", name, stored)
        if call is not None:
            call.recorded = True
            self._release_if_done(call)

    async def adopt_or_clear(self) -> None:
        """On (re)connect: hang up app channels this process has no state for."""
        try:
            app = await self._call_ari("GET", f"/applications/{ops.APP}")
        except ops.AriError:
            return
        for channel_id in app.get("channel_ids") or []:
            if self._sip_id_of(channel_id)[0] not in self.calls:
                logger.warning("clearing orphan channel %s from a previous controller", channel_id)
                await self._quiet("DELETE", f"/channels/{channel_id}")


# -- process ---------------------------------------------------------------


class Health:
    def __init__(self) -> None:
        self.connected = False
        self.media_client_ok = False
        self.detail = "starting"

    @property
    def ok(self) -> bool:
        return self.connected and self.media_client_ok


async def _check_media_client(health: Health) -> None:
    """The websocket_client the bot's media leg dials must exist in Asterisk.

    A bad value in websocket_client.conf is not a startup error in Asterisk: the
    object is skipped, the container stays healthy, and every call fails. This
    makes that a failing healthcheck instead.
    """
    while True:
        try:
            await asyncio.to_thread(
                ops.ari, "GET", "/asterisk/config/dynamic/res_websocket_client/websocket_client/habibi_bot"
            )
            health.media_client_ok = True
        except ops.AriError as exc:
            health.media_client_ok = False
            health.detail = f"websocket_client habibi_bot unavailable: {exc}"
            logger.error(health.detail)
        await asyncio.sleep(60)


async def _serve_health(health: Health) -> None:
    async def respond(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readline()
        body = json.dumps({"ok": health.ok, "connected": health.connected, "detail": health.detail})
        status = "200 OK" if health.ok else "503 Service Unavailable"
        writer.write(
            f"HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\n"
            f"Connection: close\r\n\r\n{body}".encode()
        )
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(respond, "0.0.0.0", HEALTH_PORT)
    async with server:
        await server.serve_forever()


def _events_url() -> str:
    root = ops._ari_root()
    scheme = "wss" if root.startswith("https") else "ws"
    return f"{scheme}{root[root.index(':'):]}/events?app={ops.APP}&subscribeAll=false"


async def run() -> None:
    from websockets.asyncio.client import connect

    # Runs on the api image, where nothing configures the root logger.
    logging.basicConfig(
        level=(env_str("ASTERISK_CONTROLLER_LOG_LEVEL") or "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    controller = Controller()
    health = Health()
    asyncio.create_task(_serve_health(health))
    asyncio.create_task(_check_media_client(health))
    backoff = 1.0
    while True:
        try:
            async with connect(
                _events_url(), additional_headers={"Authorization": ops._ari_auth_header()}
            ) as ws:
                health.connected, health.detail, backoff = True, "connected", 1.0
                logger.info("asterisk_controller: ARI app '%s' connected", ops.APP)
                await controller.adopt_or_clear()
                async for message in ws:
                    event = json.loads(message)
                    asyncio.create_task(controller.handle(event))
        except Exception as exc:
            health.connected = False
            health.detail = f"ARI events disconnected: {exc}"
            logger.warning("asterisk_controller: %s; retrying in %.0fs", health.detail, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)


if __name__ == "__main__":
    asyncio.run(run())
