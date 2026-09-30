"""Streaming OpenRouter PCM synthesis; the output transport owns resampling."""

from email.message import Message

import aiohttp

from pipecat.frames.frames import ErrorFrame, TTSAudioRawFrame
from pipecat.services.settings import TTSSettings
from pipecat.services.tts_service import TTSService
from pipecat.utils.errors import ErrorCategory, classify_http_status_code

from api.services.configuration.openrouter_tts import (
    OPENROUTER_SPEECH_URL,
    speech_request,
)


def pcm_metadata(content_type: str) -> tuple[int, int]:
    message = Message()
    message["content-type"] = content_type
    params = message.get_params() or []
    if message.get_content_type() != "audio/pcm":
        raise ValueError("OpenRouter returned an unsupported audio format")
    values = {}
    for name, value in params[1:]:
        if name in values:
            raise ValueError("OpenRouter returned duplicate audio metadata")
        values[name] = value
    try:
        rate, channels = int(values["rate"]), int(values["channels"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("OpenRouter returned malformed PCM metadata") from None
    if rate not in {8000, 16000, 22050, 24000, 32000, 44100, 48000} or channels != 1:
        raise ValueError("OpenRouter returned unsupported PCM rate or channels")
    return rate, channels


class OpenRouterTTSService(TTSService):
    """Streams one HTTP PCM response per sentence. Subclasses supply the request
    and the response's audio format (see fish_tts)."""

    _provider_label = "OpenRouter"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        voice: str,
        style: str,
        aiohttp_session: aiohttp.ClientSession,
        **kwargs,
    ):
        super().__init__(
            settings=TTSSettings(model=model, voice=voice),
            push_start_frame=True,
            push_stop_frames=True,
            **kwargs,
        )
        self._api_key = api_key
        self._style = style
        self._session = aiohttp_session
        self._responses: set[aiohttp.ClientResponse] = set()
        self._generation = 0

    def can_generate_metrics(self) -> bool:
        return True

    def _close_requests(self):
        self._generation += 1
        for response in tuple(self._responses):
            response.close()

    async def _handle_interruption(self, frame, direction):
        self._close_requests()
        await super()._handle_interruption(frame, direction)

    async def cancel(self, frame):
        self._close_requests()
        await super().cancel(frame)

    async def cleanup(self):
        self._close_requests()
        try:
            await super().cleanup()
        finally:
            if not self._session.closed:
                await self._session.close()

    def _request(self, text: str) -> tuple[str, dict, dict]:
        payload = speech_request(
            text=text,
            model=self._settings.model,
            voice=self._settings.voice,
            style=self._style,
        )
        return OPENROUTER_SPEECH_URL, payload, {"Authorization": f"Bearer {self._api_key}"}

    def _audio_format(self, response: aiohttp.ClientResponse) -> tuple[int, int]:
        return pcm_metadata(response.headers.get("Content-Type", ""))

    async def run_tts(self, text: str, context_id: str):
        generation = self._generation
        url, payload, headers = self._request(text)
        try:
            async with self._session.post(
                url,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=60, connect=10, sock_read=30),
            ) as response:
                self._responses.add(response)
                try:
                    if generation != self._generation:
                        return
                    if response.status != 200:
                        yield ErrorFrame(
                            error=f"{self._provider_label} speech failed (HTTP {response.status})",
                            category=classify_http_status_code(response.status),
                        )
                        return
                    rate, channels = self._audio_format(response)
                    await self.start_tts_usage_metrics(text)
                    pending = b""
                    emitted = False
                    # iter_any delivers the first available bytes without waiting for
                    # a fixed read size. At most one partial PCM16 sample is retained.
                    async for chunk in response.content.iter_any():
                        if generation != self._generation:
                            return
                        data = pending + chunk
                        aligned = len(data) - len(data) % 2
                        pending = data[aligned:]
                        for offset in range(0, aligned, (rate // 50) * 2):
                            if generation != self._generation:
                                return
                            if not emitted:
                                await self.stop_ttfb_metrics()
                                emitted = True
                            if generation != self._generation:
                                return
                            yield TTSAudioRawFrame(
                                data[offset : min(offset + (rate // 50) * 2, aligned)],
                                rate,
                                channels,
                                context_id=context_id,
                            )
                    if generation != self._generation:
                        return
                    if pending or not emitted:
                        yield ErrorFrame(
                            error=f"{self._provider_label} returned incomplete PCM audio",
                            category=ErrorCategory.SERVER,
                        )
                finally:
                    self._responses.discard(response)
        except (aiohttp.ClientError, TimeoutError):
            if generation == self._generation:
                yield ErrorFrame(
                    error=f"{self._provider_label} speech connection interrupted or timed out",
                    category=ErrorCategory.CONNECTIVITY,
                )
        except ValueError as error:
            yield ErrorFrame(error=str(error), category=ErrorCategory.SERVER)
