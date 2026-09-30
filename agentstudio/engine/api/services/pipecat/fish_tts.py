"""Fish Audio's own streaming HTTP speech API, one request per sentence.

Warm-connection first audio measured at ~0.35 s, the same as Fish's websocket, with
no extra dependency and no connection slot held between sentences.
"""

import aiohttp
from loguru import logger

from api.services.configuration.fish_tts import (
    FISH_KEY_CHECK_URL,
    FISH_MODEL,
    FISH_TTS_URL,
    fish_headers,
    fish_pcm_rate,
    fish_request,
)
from api.services.pipecat.openrouter_tts import OpenRouterTTSService


class FishAudioHTTPTTSService(OpenRouterTTSService):
    _provider_label = "Fish Audio"

    def __init__(
        self,
        *,
        api_key: str,
        voice: str,
        style: str | None,
        speed: float,
        volume: float,
        latency: str,
        temperature: float | None,
        top_p: float | None,
        aiohttp_session: aiohttp.ClientSession,
        **kwargs,
    ):
        super().__init__(
            api_key=api_key,
            model=FISH_MODEL,
            voice=voice,
            style=style,
            aiohttp_session=aiohttp_session,
            **kwargs,
        )
        self._delivery = {
            "speed": speed,
            "volume": volume,
            "latency": latency,
            "temperature": temperature,
            "top_p": top_p,
        }
        self._warmup_task = None

    def _request(self, text: str) -> tuple[str, dict, dict]:
        payload = fish_request(
            text=text,
            voice=self._settings.voice,
            style=self._style,
            sample_rate=fish_pcm_rate(self.sample_rate),
            **self._delivery,
        )
        return FISH_TTS_URL, payload, fish_headers(self._api_key)

    def _audio_format(self, response: aiohttp.ClientResponse) -> tuple[int, int]:
        # Fish's PCM Content-Type carries no rate: the audio is at the rate asked for.
        if response.headers.get("Content-Type", "").split(";")[0].strip() != "audio/pcm":
            raise ValueError("Fish Audio returned an unsupported audio format")
        return fish_pcm_rate(self.sample_rate), 1

    async def start(self, frame):
        await super().start(frame)
        # The TLS handshake costs 0.4-1 s; pay it while the call connects, not on the
        # first sentence.
        self._warmup_task = self.create_task(self._warm_connection())

    async def _warm_connection(self):
        try:
            async with self._session.get(
                FISH_KEY_CHECK_URL,
                headers=fish_headers(self._api_key),
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                await response.read()
        except (aiohttp.ClientError, TimeoutError) as error:
            # Best effort: the first sentence opens the connection itself.
            logger.debug(f"{self}: Fish Audio warm-up failed: {type(error).__name__}")

    async def cleanup(self):
        if self._warmup_task:
            await self.cancel_task(self._warmup_task)
            self._warmup_task = None
        await super().cleanup()
