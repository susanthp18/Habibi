"""Fish Audio's own TTS API. All provider boundaries are mocked."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from pydantic import TypeAdapter, ValidationError

from api.services.configuration.fish_tts import (
    FISH_KEY_CHECK_URL,
    FISH_TTS_URL,
    fish_pcm_rate,
    fish_request,
)
from api.services.configuration.registry import REGISTRY, ServiceType, TTSConfig


def config(**kwargs):
    return TypeAdapter(TTSConfig).validate_python({"provider": "fish", "api_key": "synthetic-key", **kwargs})


def test_fish_parses_in_the_tts_union_with_streaming_defaults():
    c = config(style="  ")
    assert (c.model, c.latency, c.style, c.speed, c.volume) == ("s2.1-pro-free", "balanced", None, 1.0, 0)
    assert "fish" in REGISTRY[ServiceType.TTS]
    for bad in ({"latency": "normal"}, {"speed": 5}, {"style": "[angry]"}, {"volume": 30},
                {"model": "s2.1-pro"}, {"temperature": 2}):
        with pytest.raises(ValidationError):
            config(**bad)


def test_request_body_carries_style_only_to_fish_and_the_rate_is_always_asked_for():
    body = fish_request(text="Hello.", voice="v", style="empathetic", speed=1.2, volume=3,
                        latency="low", temperature=0.5, sample_rate=8000)
    assert body == {"text": "[empathetic] Hello.", "reference_id": "v", "format": "pcm",
                    "sample_rate": 8000, "latency": "low", "prosody": {"speed": 1.2, "volume": 3},
                    "temperature": 0.5}
    assert fish_request(text="Hi", voice="v")["text"] == "Hi"
    # Fish's PCM rates (verified): the pipeline's own when offered, else 24 kHz.
    assert [fish_pcm_rate(r) for r in (8000, 16000, 48000)] == [8000, 16000, 24000]


class Response:
    def __init__(self, chunks=(), *, status=200, content_type="audio/pcm"):
        self.status = status
        self.headers = {"Content-Type": content_type}
        self.chunks = chunks
        self.content = self
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.closed = True

    def close(self):
        self.closed = True

    async def read(self):
        return b""

    async def iter_any(self):
        for chunk in self.chunks:
            yield chunk


class Session:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.requests = []
        self.closed = False

    def post(self, url, **kwargs):
        self.requests.append(("POST", url, kwargs))
        return next(self.responses)

    def get(self, url, **kwargs):
        self.requests.append(("GET", url, kwargs))
        return next(self.responses)

    async def close(self):
        self.closed = True


def service(session, rate=8000):
    from api.services.pipecat.fish_tts import FishAudioHTTPTTSService

    instance = FishAudioHTTPTTSService(
        api_key="synthetic-key", voice="synthetic-voice", style="empathetic", speed=1.0,
        volume=0, latency="balanced", temperature=None, top_p=None, aiohttp_session=session,
    )
    instance._sample_rate = rate
    instance.start_tts_usage_metrics = AsyncMock()
    instance.stop_ttfb_metrics = AsyncMock()
    return instance


@pytest.mark.asyncio
async def test_streams_pcm_at_the_requested_rate_from_fishs_own_endpoint():
    from pipecat.frames.frames import TTSAudioRawFrame

    session = Session(Response([b"\x00\x01\x02", b"\x03"]))
    frames = [f async for f in service(session).run_tts("Hello.", "ctx")]
    method, url, kwargs = session.requests[0]
    assert (method, url) == ("POST", FISH_TTS_URL)
    assert kwargs["headers"]["model"] == "s2.1-pro-free"
    assert kwargs["json"]["sample_rate"] == 8000 and kwargs["json"]["text"] == "[empathetic] Hello."
    assert all(isinstance(f, TTSAudioRawFrame) and f.sample_rate == 8000 for f in frames)
    assert b"".join(f.audio for f in frames) == b"\x00\x01\x02\x03"


@pytest.mark.asyncio
@pytest.mark.parametrize("response, category", [
    (Response(status=400), "invalid_request"),   # unknown voice: the call cannot recover
    (Response(status=429), "rate_limit"),
    (Response(status=503), "server"),
    (Response([b"\x00\x01"], content_type="application/json"), "server"),
])
async def test_failures_are_classified(response, category):
    frames = [f async for f in service(Session(response)).run_tts("Hello.", "ctx")]
    assert len(frames) == 1 and frames[0].category.value == category
    assert "Fish Audio" in frames[0].error


@pytest.mark.asyncio
async def test_warm_up_opens_the_connection_before_the_first_sentence():
    session = Session(Response())
    await service(session)._warm_connection()
    assert session.requests[0][:2] == ("GET", FISH_KEY_CHECK_URL)


def test_key_check_is_read_only_and_rejects_a_bad_key(monkeypatch):
    from api.services.configuration.check_validity import UserConfigurationValidator

    statuses = iter([200, 401])
    calls = []
    monkeypatch.setattr(httpx, "get", lambda url, **kw: calls.append(url) or httpx.Response(next(statuses)))
    validator = UserConfigurationValidator()
    assert validator._check_api_key("fish", "synthetic-key") is True
    with pytest.raises(ValueError, match="rejected"):
        validator._check_api_key("fish", "synthetic-key")
    assert calls == [FISH_KEY_CHECK_URL] * 2


def _catalog_client(monkeypatch, handler):
    from api.services import voice_catalog_local as catalog

    client = httpx.AsyncClient
    monkeypatch.setattr(catalog.httpx, "AsyncClient",
                        lambda **kw: client(transport=httpx.MockTransport(handler)))
    return catalog


@pytest.mark.asyncio
async def test_catalog_plays_a_voices_own_sample_and_filters_server_side(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"has_more": False, "items": [
            {"_id": "with-sample", "title": "A", "languages": ["hi"], "tags": ["male"],
             "samples": [{"title": "s", "audio": "https://platform.r2.fish.audio/a.mp3"}]},
            {"_id": "no-sample", "title": "B", "languages": ["en"], "tags": [], "samples": []},
        ]})

    catalog = _catalog_client(monkeypatch, handler)
    result = await catalog.list_voices(organization_id=1, provider="fish", language="hi-IN", gender="male")
    params = calls[0].url.params
    assert (params["language"], params["tag"]) == ("hi", "male")
    assert [v["preview_url"] for v in result["voices"]] == ["https://platform.r2.fish.audio/a.mp3", None]


@pytest.mark.asyncio
async def test_preview_speaks_with_the_forms_settings(monkeypatch):
    def handler(request):
        body = json.loads(request.content)
        assert request.headers["model"] == "s2.1-pro-free"
        assert (body["format"], body["sample_rate"], body["prosody"]) == ("mp3", 44100, {"speed": 1.2, "volume": -3.0})
        assert body["text"] == "[calm] Hello"
        return httpx.Response(200, content=b"mp3", headers={"Content-Type": "audio/mpeg"})

    catalog = _catalog_client(monkeypatch, handler)
    audio = await catalog.preview_voice(organization_id=1, provider="fish", params=SimpleNamespace(
        voice="v", text="Hello", style="calm", speed=1.2, volume_db=-3, api_key="typed-key"))
    assert audio == b"mp3"


@pytest.mark.asyncio
async def test_factory_builds_the_fish_service_with_a_long_keepalive():
    from api.services.pipecat.fish_tts import FishAudioHTTPTTSService
    from api.services.pipecat.service_factory import create_tts_service
    from pipecat.services.tts_service import TTSService

    instance = create_tts_service(SimpleNamespace(tts=config(style="empathetic")),
                                  SimpleNamespace(transport_out_sample_rate=8000))
    assert isinstance(instance, FishAudioHTTPTTSService)
    assert instance._session.connector._keepalive_timeout == 120
    with patch.object(TTSService, "cleanup", new=AsyncMock()):
        await instance.cleanup()
    assert instance._session.closed


def _pipeline(tts):
    return {"mode": "byok", "byok": {"mode": "pipeline", "pipeline": {
        "llm": {"provider": "openai", "api_key": "llm-key", "model": "gpt-4.1"},
        "stt": {"provider": "deepgram", "api_key": "stt-key"}, "tts": tts}}}


def _agent_settings_tool(monkeypatch, organization_tts):
    import copy

    from api.mcp_server.tools import agent_settings as tool
    from api.schemas.ai_model_configuration import OrganizationAIModelConfigurationV2

    configs = {"model_configuration_v2_override": _pipeline(
        {"provider": "azure_speech", "api_key": "azure-key", "region": "southeastasia", "voice": "en-IN-NeerjaNeural"})}

    async def current(workflow_id, organization_id):
        return SimpleNamespace(), copy.deepcopy(configs)

    async def update_workflow(workflow_id, request, user):
        configs.update(request.workflow_configurations.model_dump(exclude_unset=True))

    monkeypatch.setattr(tool, "authenticate_mcp_request", AsyncMock(return_value=SimpleNamespace(selected_organization_id=1)))
    monkeypatch.setattr(tool, "_current", current)
    monkeypatch.setattr(tool, "get_resolved_ai_model_configuration", AsyncMock(return_value=SimpleNamespace(
        organization_configuration=OrganizationAIModelConfigurationV2.model_validate(_pipeline(organization_tts)))))
    monkeypatch.setattr("api.routes.workflow.update_workflow", update_workflow)
    return tool, configs


@pytest.mark.asyncio
async def test_an_agent_switches_to_the_organizations_voice_provider_without_its_key_crossing_mcp(monkeypatch):
    tool, configs = _agent_settings_tool(monkeypatch, {"provider": "fish", "api_key": "org-fish-key", "voice": "org"})
    result = await tool.update_agent_settings(4, tts={"provider": "fish", "voice": "agent-voice", "style": "empathetic"})
    assert result["updated"] and result["tts"]["provider"] == "fish" and result["tts"]["voice"] == "agent-voice"
    assert "org-fish-key" not in json.dumps(result)
    saved = configs["model_configuration_v2_override"]["byok"]["pipeline"]["tts"]
    assert saved["api_key"] == "org-fish-key" and "region" not in saved


@pytest.mark.asyncio
async def test_switching_to_a_provider_the_organization_does_not_use_is_refused(monkeypatch):
    tool, _ = _agent_settings_tool(monkeypatch, {"provider": "azure_speech", "api_key": "k", "region": "southeastasia"})
    result = await tool.update_agent_settings(4, tts={"provider": "fish", "voice": "v"})
    assert result["error_code"] == "provider_change"


@pytest.mark.asyncio
async def test_the_voice_endpoints_accept_fish(monkeypatch):
    from fastapi import FastAPI
    from api.routes import user as routes
    from api.services.auth.depends import get_user

    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[get_user] = lambda: SimpleNamespace(selected_organization_id=1)
    listing = AsyncMock(return_value={"provider": "fish", "voices": []})
    monkeypatch.setattr(routes.voice_catalog_local, "list_voices", listing)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://t") as client:
        response = await client.get("/user/configurations/voices/fish", params={"gender": "female"})
    assert response.status_code == 200 and listing.call_args.kwargs["gender"] == "female"
