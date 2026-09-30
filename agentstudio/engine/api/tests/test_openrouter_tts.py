"""OpenRouter TTS contracts. All provider boundaries are mocked."""

import asyncio
from builtins import anext
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from pydantic import TypeAdapter, ValidationError

from api.services.configuration.registry import REGISTRY, ServiceType, TTSConfig


def test_openrouter_is_discoverable_and_parses_in_tts_union():
    assert "openrouter" in REGISTRY[ServiceType.TTS]
    config = TypeAdapter(TTSConfig).validate_python(
        {"provider": "openrouter", "api_key": "synthetic-test-key"}
    )
    assert config.model == "fish-audio/s2.1-pro-free:free"
    assert config.style == "calm and conversational"
    assert set(config.model_dump()) == {
        "provider",
        "api_key",
        "model",
        "voice",
        "style",
    }


def test_only_free_model_and_short_unbracketed_style_are_accepted():
    cls = REGISTRY[ServiceType.TTS]["openrouter"]
    for kwargs in [
        {"model": "fish-audio/s2.1-pro"},
        {"style": "[angry]"},
        {"style": "x" * 41},
        {"style": "calm\nangry"},
    ]:
        with pytest.raises(ValidationError):
            cls(api_key="synthetic-test-key", **kwargs)
    schema = cls.model_json_schema()
    assert set(schema["properties"]) == {
        "provider",
        "api_key",
        "model",
        "voice",
        "style",
    }


def test_style_is_only_in_provider_payload_and_preview_matches_runtime():
    from api.services.configuration.openrouter_tts import (
        FISH_FREE_MODEL,
        speech_request,
    )

    original = "Hello. नमस्ते। வணக்கம்."
    args = dict(
        text=original,
        model=FISH_FREE_MODEL,
        voice="synthetic-voice",
        style="warm and reassuring",
    )
    pcm, mp3 = speech_request(**args), speech_request(**args, response_format="mp3")
    assert pcm == {**mp3, "response_format": "pcm"}
    assert pcm["input"] == "[warm and reassuring] " + original
    assert original == "Hello. नमस्ते। வணக்கம்."


@pytest.mark.parametrize(
    "content_type",
    [
        "audio/mpeg",
        "audio/pcm",
        "audio/pcm;rate=no;channels=1",
        "audio/pcm;rate=44100;channels=2",
        "audio/pcm;rate=12345;channels=1",
        "audio/pcm;rate=44100;rate=16000;channels=1",
    ],
)
def test_malformed_or_unsupported_pcm_metadata_is_rejected(content_type):
    from api.services.pipecat.openrouter_tts import pcm_metadata

    with pytest.raises(ValueError):
        pcm_metadata(content_type)


class Response:
    def __init__(
        self,
        chunks=(),
        *,
        status=200,
        content_type="audio/pcm;rate=44100;channels=1",
        gate=None,
    ):
        self.status = status
        self.headers = {"Content-Type": content_type}
        self.chunks = chunks
        self.content = self
        self.closed = False
        self.completed = False
        self.gate = gate
        self.arrival = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.close()

    def close(self):
        self.closed = True

    async def iter_any(self):
        for chunk in self.chunks:
            self.arrival = time.perf_counter()
            yield chunk
        if self.gate:
            await self.gate.wait()
        self.completed = True


class Session:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.requests = []
        self.closed = False

    def post(self, url, **kwargs):
        self.requests.append((url, kwargs))
        return next(self.responses)

    async def close(self):
        self.closed = True


def service(session):
    from api.services.configuration.openrouter_tts import FISH_FREE_MODEL
    from api.services.pipecat.openrouter_tts import OpenRouterTTSService

    instance = OpenRouterTTSService(
        api_key="synthetic-test-key",
        model=FISH_FREE_MODEL,
        voice="synthetic-voice",
        style="calm and conversational",
        aiohttp_session=session,
    )
    instance.start_tts_usage_metrics = AsyncMock()
    instance.stop_ttfb_metrics = AsyncMock()
    return instance


@pytest.mark.asyncio
async def test_fragmented_pcm_is_aligned_and_source_rate_and_context_are_preserved():
    from pipecat.frames.frames import TTSAudioRawFrame

    response = Response([b"\x00", b"\x01\x02", b"\x03\x04\x05"])
    instance = service(Session(response))
    frames = [f async for f in instance.run_tts("Hello", "context-1")]
    assert all(
        isinstance(f, TTSAudioRawFrame) and len(f.audio) % 2 == 0 for f in frames
    )
    assert b"".join(f.audio for f in frames) == bytes(range(6))
    assert all(
        f.sample_rate == 44100 and f.num_channels == 1 and f.context_id == "context-1"
        for f in frames
    )
    assert response.closed
    instance.stop_ttfb_metrics.assert_awaited_once()


@pytest.mark.asyncio
async def test_first_frame_precedes_completion_and_adapter_overhead_is_below_20ms():
    timings = []
    for _ in range(20):
        response = Response([b"\x00\x01"], gate=asyncio.Event())
        instance = service(Session(response))
        generator = instance.run_tts("Hello", "first")
        frame = await asyncio.wait_for(anext(generator), 1)
        timings.append(time.perf_counter() - response.arrival)
        assert frame.audio == b"\x00\x01" and not response.completed
        await generator.aclose()
        assert response.closed
    assert max(timings) < 0.020
    print(f"ADAPTER_FIRST_FRAME_OVERHEAD_MAX_MS={max(timings) * 1000:.3f}")


@pytest.mark.asyncio
async def test_interruption_closes_response_and_old_context_cannot_emit_into_next_turn():
    from pipecat.services.tts_service import TTSService

    old, new = Response([b"\x00\x01\x02"]), Response([b"\x04\x05"])
    session = Session(old, new)
    instance = service(session)
    generator = instance.run_tts("Hello", "old")
    assert (await anext(generator)).context_id == "old"
    with patch.object(TTSService, "_handle_interruption", new=AsyncMock()) as parent:
        await instance._handle_interruption(None, None)
        parent.assert_awaited_once()
    assert old.closed
    assert [f async for f in generator] == []
    frames = [f async for f in instance.run_tts("Next", "new")]
    assert len(session.requests) == 2
    assert all(f.context_id == "new" and f.audio == b"\x04\x05" for f in frames)
    with patch.object(TTSService, "cleanup", new=AsyncMock()):
        await instance.cleanup()
        await instance.cleanup()
    assert session.closed


@pytest.mark.asyncio
async def test_task_cancellation_closes_blocked_stream_without_error_or_stale_audio():
    response = Response([], gate=asyncio.Event())
    instance = service(Session(response))
    generator = instance.run_tts("Hello", "cancelled")
    task = asyncio.create_task(anext(generator))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert response.closed and not instance._responses


@pytest.mark.parametrize(
    "status,category",
    [
        (400, "invalid_request"),
        (401, "authentication"),
        (403, "authorization"),
        (429, "rate_limit"),
        (502, "server"),
    ],
)
@pytest.mark.asyncio
async def test_provider_errors_are_classified_without_body_text_or_credentials(
    status, category
):
    response = Response([b"sensitive-provider-body"], status=status)
    frames = [
        f
        async for f in service(Session(response)).run_tts(
            "private-request-text", "error"
        )
    ]
    assert len(frames) == 1 and frames[0].category.value == category
    assert frames[0].error == f"OpenRouter speech failed (HTTP {status})"
    assert response.closed and not response.completed


@pytest.mark.asyncio
async def test_truncated_pcm_is_reported_and_connections_are_redacted():
    response = Response([b"\x00"])
    frames = [f async for f in service(Session(response)).run_tts("Hello", "odd")]
    assert frames[0].category.value == "server"
    session = Session()
    session.post = lambda *args, **kwargs: (_ for _ in ()).throw(
        TimeoutError("sensitive timeout")
    )
    frames = [f async for f in service(session).run_tts("Hello", "timeout")]
    assert (
        frames[0].category.value == "connectivity"
        and "sensitive" not in frames[0].error
    )


def test_credential_validation_is_read_only_and_preserves_openrouter_llm_behavior(
    monkeypatch,
):
    from api.services.configuration.check_validity import UserConfigurationValidator

    validator = UserConfigurationValidator()
    config = REGISTRY[ServiceType.TTS]["openrouter"](api_key="synthetic-test-key")
    calls = []

    def get(url, **kwargs):
        calls.append(url)
        return httpx.Response(401, json={"error": {"message": "sensitive"}})

    monkeypatch.setattr(httpx, "get", get)
    with pytest.raises(ValueError, match="rejected"):
        validator._check_api_key("openrouter", "synthetic-test-key", config)
    assert calls == ["https://openrouter.ai/api/v1/key"]
    assert validator._check_api_key("openrouter", "synthetic-test-key") is True


@pytest.mark.asyncio
async def test_catalog_search_pagination_and_reference_metadata_require_no_key(
    monkeypatch,
):
    from api.services import voice_catalog_local as catalog

    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "_id": "synthetic-voice",
                        "title": "indian",
                        "description": "Synthetic catalog description",
                        "languages": ["en"],
                        "tags": ["male", "Indian Accent"],
                        "samples": [
                            {
                                "title": "Sample",
                                "audio": "https://example.com/sample.mp3",
                                "text": "not returned",
                            }
                        ],
                    }
                ],
                "has_more": True,
            },
        )

    client = httpx.AsyncClient
    monkeypatch.setattr(
        catalog.httpx,
        "AsyncClient",
        lambda **kwargs: client(transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setattr(
        catalog,
        "_provider_key",
        AsyncMock(side_effect=AssertionError("catalog must be public")),
    )
    result = await catalog.list_voices(
        organization_id=42,
        provider="openrouter",
        q="indian",
        page_number=2,
        page_size=10,
    )
    assert result["pagination"] == {"page_number": 2, "page_size": 10, "has_more": True}
    assert (
        calls[0].url.params["title"] == "indian"
        and calls[0].url.params["page_number"] == "2"
    )
    voice = result["voices"][0]
    assert voice["reference_languages"] == ["en"] and voice["accent"] == "Indian Accent"
    assert "multilingual" not in voice and voice["preview_url"] is None
    assert voice["samples"] == [
        {"title": "Sample", "audio": "https://example.com/sample.mp3"}
    ]


@pytest.mark.asyncio
async def test_preview_uses_selected_model_style_and_temporary_key_without_persistence(
    monkeypatch,
):
    from api.services import voice_catalog_local as catalog
    from api.services.configuration.openrouter_tts import (
        FISH_FREE_MODEL,
        speech_request,
    )
    import json

    def handler(request):
        assert request.headers["Authorization"] == "Bearer temporary-test-key"
        assert json.loads(request.content) == speech_request(
            text="வணக்கம்",
            model=FISH_FREE_MODEL,
            voice="synthetic-voice",
            style="warm and reassuring",
            response_format="mp3",
        )
        return httpx.Response(
            200, content=b"synthetic-mp3", headers={"Content-Type": "audio/mpeg"}
        )

    client = httpx.AsyncClient
    monkeypatch.setattr(
        catalog.httpx,
        "AsyncClient",
        lambda **kwargs: client(transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setattr(
        catalog,
        "_provider_key",
        AsyncMock(side_effect=AssertionError("typed key should be temporary")),
    )
    result = await catalog.preview_voice(
        organization_id=42,
        provider="openrouter",
        params=SimpleNamespace(
            voice="synthetic-voice",
            model=FISH_FREE_MODEL,
            style="warm and reassuring",
            text="வணக்கம்",
            api_key="temporary-test-key",
        ),
    )
    assert result == b"synthetic-mp3"


def test_secret_round_trip_preserves_other_model_settings():
    from api.schemas.ai_model_configuration import OrganizationAIModelConfigurationV2
    from api.services.configuration.ai_model_configuration import (
        mask_ai_model_configuration_v2,
        merge_ai_model_configuration_v2_secrets,
    )

    config = OrganizationAIModelConfigurationV2(
        mode="byok",
        byok={
            "mode": "pipeline",
            "pipeline": {
                "llm": {
                    "provider": "openrouter",
                    "api_key": "synthetic-llm-key",
                    "model": "synthetic-llm",
                },
                "tts": {"provider": "openrouter", "api_key": "synthetic-tts-key"},
                "stt": {"provider": "deepgram", "api_key": "synthetic-stt-key"},
            },
        },
    )
    masked = mask_ai_model_configuration_v2(config)
    assert "***" in masked["byok"]["pipeline"]["tts"]["api_key"]
    incoming = OrganizationAIModelConfigurationV2.model_validate(masked)
    incoming.byok.pipeline.tts.style = "warm and reassuring"
    merged = merge_ai_model_configuration_v2_secrets(incoming, config)
    assert merged.byok.pipeline.tts.api_key == "synthetic-tts-key"
    assert merged.byok.pipeline.llm == config.byok.pipeline.llm
    assert merged.byok.pipeline.stt == config.byok.pipeline.stt


@pytest.mark.asyncio
async def test_draft_resolves_openrouter_without_organization_lookup(monkeypatch):
    from api.services.configuration import ai_model_configuration as configs

    monkeypatch.setattr(
        configs,
        "get_resolved_ai_model_configuration",
        AsyncMock(side_effect=AssertionError("draft must own its model settings")),
    )
    effective = await configs.get_effective_ai_model_configuration_for_workflow(
        organization_id=42,
        workflow_configurations={
            "model_configuration_v2_override": {
                "mode": "byok",
                "byok": {
                    "mode": "pipeline",
                    "pipeline": {
                        "llm": {
                            "provider": "openai",
                            "api_key": "synthetic-llm-key",
                            "model": "gpt-4.1",
                        },
                        "tts": {
                            "provider": "openrouter",
                            "api_key": "synthetic-tts-key",
                        },
                        "stt": {"provider": "deepgram", "api_key": "synthetic-stt-key"},
                    },
                },
            }
        },
    )
    assert effective.tts.provider == "openrouter"
    assert effective.llm.provider == "openai" and effective.stt.provider == "deepgram"


@pytest.mark.asyncio
async def test_existing_output_transport_resamples_source_frames_once():
    from pipecat.transports.base_output import BaseOutputTransport
    from pipecat.frames.frames import TTSAudioRawFrame
    from pipecat.audio.utils import create_stream_resampler
    from pipecat.transports.base_transport import TransportParams

    sender = BaseOutputTransport.MediaSender.__new__(BaseOutputTransport.MediaSender)
    sender._params = TransportParams(audio_out_enabled=True)
    sender._sample_rate = 16000
    sender._resampler = create_stream_resampler()
    sender._audio_buffer = bytearray()
    sender._audio_chunk_size = 640
    sender._audio_queue = asyncio.Queue()
    sender._destination = None
    frame = TTSAudioRawFrame(b"\x00\x01" * 4410, 44100, 1, context_id="source")
    await sender.handle_audio_frame(frame)
    assert not sender._audio_queue.empty()
    while not sender._audio_queue.empty():
        converted = sender._audio_queue.get_nowait()
        assert converted.sample_rate == 16000 and len(converted.audio) == 640


@pytest.mark.asyncio
async def test_factory_wires_owned_session_and_filters_without_setting_a_source_rate(
    monkeypatch,
):
    from api.services.pipecat.service_factory import create_tts_service
    from pipecat.services.tts_service import TTSService

    config = REGISTRY[ServiceType.TTS]["openrouter"](api_key="synthetic-test-key")
    session = Session()
    monkeypatch.setattr(
        "api.services.pipecat.service_factory.aiohttp.ClientSession", lambda: session
    )
    instance = create_tts_service(
        SimpleNamespace(tts=config), SimpleNamespace(transport_out_sample_rate=16000)
    )
    assert instance._session is session and instance._init_sample_rate is None
    assert {type(f).__name__ for f in instance._text_filters} == {
        "XMLFunctionTagFilter",
        "MarkdownTextFilter",
    }
    with patch.object(TTSService, "cleanup", new=AsyncMock()):
        await instance.cleanup()
    assert session.closed


@pytest.mark.asyncio
async def test_authenticated_voice_endpoints_accept_openrouter_and_forward_pagination(
    monkeypatch,
):
    from fastapi import FastAPI
    from api.routes import user as routes
    from api.services.auth.depends import get_user

    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[get_user] = lambda: SimpleNamespace(
        selected_organization_id=42
    )
    listing = AsyncMock(
        return_value={
            "provider": "openrouter",
            "voices": [],
            "pagination": {"page_number": 2, "page_size": 10, "has_more": True},
        }
    )
    preview = AsyncMock(return_value=b"synthetic-mp3")
    monkeypatch.setattr(routes.voice_catalog_local, "list_voices", listing)
    monkeypatch.setattr(routes.voice_catalog_local, "preview_voice", preview)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/user/configurations/voices/openrouter",
            params={"q": "indian", "page_number": 2, "page_size": 10},
        )
        assert (
            response.status_code == 200
            and response.json()["pagination"]["has_more"] is True
        )
        assert listing.call_args.kwargs["organization_id"] == 42
        assert (
            listing.call_args.kwargs["q"] == "indian"
            and listing.call_args.kwargs["page_number"] == 2
        )
        response = await client.get(
            "/user/configurations/voices/openrouter", params={"page_size": 101}
        )
        assert response.status_code == 422
        response = await client.post(
            "/user/configurations/voices/openrouter/preview",
            json={
                "voice": "synthetic-voice",
                "model": "fish-audio/s2.1-pro-free:free",
                "style": "calm and conversational",
            },
        )
        assert (
            response.status_code == 200
            and response.headers["content-type"] == "audio/mpeg"
        )
        assert (
            preview.call_args.kwargs["params"].model == "fish-audio/s2.1-pro-free:free"
        )
