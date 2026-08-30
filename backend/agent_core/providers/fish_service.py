"""Fish S2.1 Pro as a live Pipecat service.

Separate from :mod:`agent_core.providers.fish_tts` on purpose. That module is
the HTTP client, and the API process imports it on every voice preview; keeping
it free of ``pipecat`` means auditioning a voice does not drag the whole
pipeline framework into the request path. This module is the half that only the
voice worker needs, and the two share :func:`~agent_core.providers.fish_tts.
build_payload` so an audition and a call are built from identical bodies.

Why it exists at all: the registry named ``FishTTSService`` before anything
implemented it. Binding Fish in the Agent Studio resolved to an ImportError, the
binder fell back to Azure, and the operator heard an Azure voice on a call they
had configured for Fish — the precise failure the registry was built to end.

Three decisions are load-bearing.

**PCM out, not mp3.** :func:`fish_tts.synthesize` defaults to mp3 because a
browser ``<audio>`` element plays it. A pipeline does not: it wants raw frames
at the transport's sample rate, and an mp3 body here reaches the mixer as noise.

**Streamed, not buffered.** The response is consumed chunk by chunk, so
time-to-first-audio is the model's first chunk rather than the whole utterance.
On a barge-in pipeline that difference is the conversational feel.

**Markers steer speech but are not speech.** ``[angry]`` must reach Fish — it is
the control — but it is not a spoken character, so usage metering counts the
stripped text. Billing the direction as dialogue would overstate every turn.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any

import httpx

from pipecat.frames.frames import ErrorFrame, Frame, TTSAudioRawFrame
from pipecat.services.settings import TTSSettings
from pipecat.services.tts_service import TTSService

from agent_core.providers import pool as pool_mod
from agent_core.providers.fish_tts import (
    _TIMEOUT,
    base_url,
    build_payload,
    default_model,
    strip_tags,
)

logger = logging.getLogger(__name__)


@dataclass
class FishTTSSettings(TTSSettings):
    """Runtime-updatable settings. ``voice`` is a Fish library ``reference_id``.

    ``language`` is inherited but unused: S2 detects language from the text
    itself and exposes no language parameter, so a delta naming one is accepted
    and ignored rather than sent and rejected.
    """


class FishTTSService(TTSService):
    """Fish S2.1 Pro over the direct HTTP API, streamed into the pipeline."""

    Settings = FishTTSSettings
    _settings: FishTTSSettings

    def __init__(
        self,
        *,
        api_key: str | None = None,
        settings: FishTTSSettings | None = None,
        sample_rate: int | None = None,
        params: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            sample_rate=sample_rate,
            push_start_frame=True,
            push_stop_frames=True,
            settings=settings or FishTTSSettings(),
            **kwargs,
        )
        # api_key is accepted for symmetry with every other service and as an
        # explicit override, but the pool is the normal source: a key taken at
        # construction could not be rotated when it 429s mid-call.
        self._api_key = api_key
        self._params = dict(params or {})
        self._client: httpx.AsyncClient | None = None

    def can_generate_metrics(self) -> bool:
        return True

    async def start(self, frame: Any) -> None:
        await super().start(frame)
        self._ensure_client()

    async def stop(self, frame: Any) -> None:
        await super().stop(frame)
        await self._close()

    async def cancel(self, frame: Any) -> None:
        await super().cancel(frame)
        await self._close()

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=_TIMEOUT)
        return self._client

    async def _close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _key(self, context_id: str) -> str:
        """A pooled key, sticky for this call.

        Sticky because the alternative is a different account voicing
        consecutive sentences, and the accounts are not bit-identical — the
        caller hears a seam mid-turn.
        """
        if self._api_key:
            return self._api_key
        return pool_mod.get_pool("fish").acquire(context_id)

    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame | None, None]:
        """Synthesize ``text``, yielding audio frames as the bytes arrive."""
        voice = getattr(self._settings, "voice", None)
        params = {
            **self._params,
            # The pipeline consumes raw little-endian PCM at its own rate.
            "format": "pcm",
            "sample_rate": self.sample_rate,
        }
        payload = build_payload(text, params, reference_id=voice or None)
        client = self._ensure_client()

        try:
            await self.start_ttfb_metrics()
            # Markers are stage directions: they steer synthesis but are never
            # spoken, so they must not be metered as characters.
            await self.start_tts_usage_metrics(strip_tags(text))

            key = self._key(context_id)
            first = True
            async with client.stream(
                "POST",
                f"{base_url()}/v1/tts",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                    # Selects s2.1-pro vs legacy s1; the bracket-vs-parenthesis
                    # emotion syntax differs between them.
                    "model": default_model(),
                },
                json=payload,
            ) as response:
                if response.status_code >= 400:
                    body = (await response.aread())[:300].decode("utf-8", "replace")
                    if pool_mod.is_key_fault(response.status_code):
                        # Retire so the *next* turn rotates onto a live key
                        # rather than rediscovering this one mid-conversation.
                        pool_mod.get_pool("fish").retire(
                            key, reason=pool_mod.reason_for_status(response.status_code)
                        )
                    logger.warning("fish tts %s: %s", response.status_code, body)
                    yield ErrorFrame(f"fish tts {response.status_code}: {body}")
                    return

                async for chunk in response.aiter_bytes(self.chunk_size):
                    if not chunk:
                        continue
                    if first:
                        await self.stop_ttfb_metrics()
                        first = False
                    yield TTSAudioRawFrame(
                        audio=chunk,
                        sample_rate=self.sample_rate,
                        num_channels=1,
                        context_id=context_id,
                    )
        except Exception as exc:  # noqa: BLE001 - a TTS fault must not kill the call
            logger.exception("fish tts stream failed")
            yield ErrorFrame(f"fish tts error: {exc}")
