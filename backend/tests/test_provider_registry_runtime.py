"""The registry's claims must be true.

Every entry in the capability matrix is an assertion the Agent Studio shows to
an operator, and until these tests existed nothing checked any of them. Three
seeded models could not be constructed at all — Fish named a class that was
never written, and two recognisers needed Pipecat extras that were not
installed — while the studio offered all three exactly like the working ones.
Binding one produced a call that quietly ran Azure instead.
"""

from __future__ import annotations


import pytest

from agent_core.providers import registry


def _models():
    return registry.model_specs()


@pytest.mark.parametrize(
    "provider,model",
    _models(),
    ids=[f"{p.slug}:{m.kind}:{m.model_id}" for p, m in _models()],
)
def test_every_service_class_is_importable_or_declared_unavailable(provider, model):
    """A model is either constructable or says why not — never quietly broken."""
    status, detail = registry.runtime_status(model)
    assert status in {
        registry.RUNTIME_LIVE,
        registry.RUNTIME_PREVIEW_ONLY,
        registry.RUNTIME_UNAVAILABLE,
        # Off a call host this is the only honest answer, and it is the one
        # every model gets there — see the process-boundary block below.
        registry.RUNTIME_UNKNOWN,
    }
    if status != registry.RUNTIME_LIVE:
        # Allowed, but only with a reason an operator can act on.
        assert detail, f"{provider.slug}:{model.model_id} {status} with no reason"


@pytest.mark.skipif(
    not registry.can_host_calls(),
    reason="only a call host can resolve a service class; elsewhere the probe answers for the wrong machine",
)
def test_the_models_we_ship_as_live_actually_import():
    """The set that must work. A regression here means a binding silently
    falls back to Azure on a real call."""
    must_work = {
        ("azure", "azure-stt"),
        ("azure", "azure-neural"),
        ("cartesia", "sonic-3.5"),
        ("deepgram", "aura-2-thalia-en"),
        ("fish", "s2.1-pro"),
    }
    broken = []
    for provider, model in registry.model_specs():
        if (provider.slug, model.model_id) not in must_work:
            continue
        status, detail = registry.runtime_status(model)
        if status != registry.RUNTIME_LIVE:
            broken.append(f"{provider.slug}:{model.model_id} → {status} {detail}")
    assert not broken, "; ".join(broken)


def test_azure_tts_binds_the_keepalive_subclass():
    """Pipecat's base class opens the synthesis websocket lazily on the first
    turn. The pipeline pays to avoid that (voice/tts_pool.py), so naming the
    base class here would make binding Azure a silent latency regression."""
    model = registry.find_model("azure", "azure-neural")
    assert model is not None
    assert model.service_class == "voice.tts_pool.KeepAliveAzureTTSService"


def test_preview_only_models_are_declared_not_inferred():
    """OpenRouter has no streaming integration and raises on construction. The
    flag has to be declared, because detecting it means constructing it."""
    model = registry.find_model("openrouter", "fish-audio/s2.1-pro")
    assert model is not None
    assert model.live_capable is False
    assert registry.runtime_status(model)[0] == registry.RUNTIME_PREVIEW_ONLY


@pytest.mark.skipif(
    not registry.can_host_calls(),
    reason="the probe only runs where an import proves something",
)
def test_a_live_capable_model_that_raises_on_construction_is_still_a_lie():
    """Guard the guard: the probe must resolve the attribute, not just import
    the module, or a missing class would read as healthy."""
    spec = registry.ModelSpec(
        kind="tts",
        model_id="ghost",
        display_name="Ghost",
        service_class="agent_core.providers.fish_service.NoSuchService",
    )
    registry._RUNTIME_CACHE.pop(spec.service_class, None)
    status, detail = registry.runtime_status(spec)
    assert status == registry.RUNTIME_UNAVAILABLE
    assert "NoSuchService" in detail or "attribute" in detail.lower()


# ------------------------------------------ the probe answers for one machine


def test_a_non_call_host_never_reports_its_own_missing_dependency(monkeypatch):
    """The bug: the API answered "can *I* import this?" to a screen asking
    "can the thing that runs calls import this?".

    Only the voice image installs Pipecat — requirements-voice.txt is kept out
    of requirements.txt so CRM upgrades are not coupled to onnxruntime / aiortc
    / av. So collections_api has no ``azure.cognitiveservices.speech``, and
    every one of the thirteen seeded models read ``unavailable`` there while the
    voice container reported the same models ``live`` off the same commit. The
    studio refused to bind any provider and told the operator Azure could not
    take a call, on a stack whose calls were running Azure.
    """
    monkeypatch.setattr(registry, "can_host_calls", lambda: False)
    model = registry.find_model("azure", "azure-neural")
    assert model is not None

    status, detail = registry.runtime_status(model)
    assert status == registry.RUNTIME_UNKNOWN
    assert detail, "an unknown state still owes the operator a reason"
    assert "azure" not in detail.lower(), "a local import failure is not the model's verdict"


def test_a_non_call_host_reports_what_the_call_host_published(monkeypatch):
    """Which is the whole point of the column: the answer travels."""
    monkeypatch.setattr(registry, "can_host_calls", lambda: False)
    model = registry.find_model("azure", "azure-neural")
    assert model is not None

    assert registry.runtime_status(model, (registry.RUNTIME_LIVE, "")) == (
        registry.RUNTIME_LIVE,
        "",
    )
    assert registry.runtime_status(
        model, (registry.RUNTIME_UNAVAILABLE, "ModuleNotFoundError: No module named 'azure'")
    )[0] == registry.RUNTIME_UNAVAILABLE


def test_preview_only_survives_off_the_call_host(monkeypatch):
    """It is declared, not probed, so it is the same answer in every process —
    and it must not be flattened into "unknown" by the host check."""
    monkeypatch.setattr(registry, "can_host_calls", lambda: False)
    model = registry.find_model("openrouter", "fish-audio/s2.1-pro")
    assert model is not None
    assert registry.runtime_status(model)[0] == registry.RUNTIME_PREVIEW_ONLY


def test_the_report_covers_every_seeded_model():
    """What the call host publishes. A model missing from it keeps whatever the
    last runtime wrote, which is how a stale verdict would outlive its cause."""
    report = registry.runtime_report()
    assert len(report) == len(registry.model_specs())
    keyed = {(r["provider_id"], r["kind"], r["model_id"]) for r in report}
    assert keyed == {(p.slug, m.kind, m.model_id) for p, m in registry.model_specs()}
    assert all(r["runtime"] for r in report)


# --------------------------------------------------------- params vs. the API


def test_fish_param_bounds_match_the_vendor_contract():
    """Bounds came from api.fish.audio/openapi.json. temperature and top_p cap
    at 1.0 and chunk_length is 100-300 there; a slider offering 2.0 or 1000 was
    offering a 422."""
    model = registry.find_model("fish", "s2.1-pro")
    assert model is not None
    by_key = {p["key"]: p for p in model.params_schema}
    assert by_key["temperature"]["max"] == 1.0
    assert by_key["top_p"]["max"] == 1.0
    assert by_key["chunk_length"]["min"] == 100
    assert by_key["chunk_length"]["max"] == 300


def test_every_param_declares_a_transport():
    """A control with nowhere to go is decoration. This is the check that keeps
    the inspector from growing knobs that move and change nothing."""
    missing = []
    for provider, model in registry.model_specs():
        for param in model.params_schema:
            if not param.get("transport"):
                missing.append(f"{provider.slug}:{model.model_id}:{param.get('key')}")
    assert not missing, f"params with no transport: {missing}"


def test_seed_ids_are_unique():
    """as_rows() keys on (provider, kind, model_id); a collision would make one
    model silently overwrite another at seed time."""
    from agent_core.providers.registry import as_rows

    ids = [r["id"] for r in as_rows()]
    assert len(ids) == len(set(ids))


# ------------------------------------------------------------ payload clamping


@pytest.mark.parametrize(
    "params,field,expected",
    [
        ({"temperature": 2.0}, "temperature", 1.0),
        ({"temperature": -5}, "temperature", 0.0),
        ({"top_p": 9}, "top_p", 1.0),
        ({"chunk_length": 5000}, "chunk_length", 300),
        ({"chunk_length": 1}, "chunk_length", 100),
        ({"temperature": "nonsense"}, "temperature", 0.7),
    ],
)
def test_fish_payload_is_clamped_to_the_vendor_range(params, field, expected):
    """params_schema constrains a *picker*. Anything arriving through the API,
    a stored binding or a replayed request never saw that picker, and an
    out-of-range value is a 422 — a silent turn on the live audio path."""
    from agent_core.providers.fish_tts import build_payload

    assert build_payload("hello", params)[field] == expected


def test_fish_payload_rejects_an_unknown_format():
    from agent_core.providers.fish_tts import build_payload

    assert build_payload("hi", {"format": "flac"})["format"] == "mp3"
    assert build_payload("hi", {"format": "pcm"})["format"] == "pcm"


def test_fish_prosody_is_nested_and_clamped():
    from agent_core.providers.fish_tts import build_payload

    payload = build_payload("hi", {"speed": 99, "volume": -99})
    assert payload["prosody"] == {"speed": 2.0, "volume": -20.0}


def test_emotion_markers_are_not_metered_as_speech():
    """A tag steers synthesis but is never spoken. Counting it as a character
    would overstate usage on every expressive turn."""
    from agent_core.providers.fish_tts import find_tags, strip_tags

    text = "[angry] Pay now. [sighing] Please."
    assert strip_tags(text) == "Pay now.  Please."
    assert find_tags(text) == ["angry", "sighing"]


# ------------------------------------------------------------ fish model id


def test_fish_defaults_to_the_paid_model():
    """Fish selects the model with a ``model:`` HEADER, and the free tier was a
    *separate model id* rather than a discount on the paid one.

    The free promo lapsed 2026-08-31. Leaving the default on ``s2.1-pro-free``
    (and the OpenRouter fallback on the same promotion) made every preview a
    402 that could not rescue itself. API credit is a distinct balance from
    the platform wallet; the paid id needs that balance funded.
    """
    from agent_core.providers import fish_tts, openrouter_tts

    assert fish_tts.DEFAULT_MODEL == "s2.1-pro"
    assert openrouter_tts.DEFAULT_MODEL == "fish-audio/s2.1-pro"
    assert "s2.1-pro-free" not in openrouter_tts.DEFAULT_MODEL
    assert ":free" not in openrouter_tts.DEFAULT_MODEL


def test_fish_model_is_env_overridable(monkeypatch):
    """The paid default can still be overridden; the env var is the escape."""
    from agent_core.providers import fish_tts

    monkeypatch.setenv("FISH_TTS_MODEL", "s2.1-pro-free")
    assert fish_tts.default_model() == "s2.1-pro-free"
    monkeypatch.delenv("FISH_TTS_MODEL")
    assert fish_tts.default_model() == "s2.1-pro"


def test_fish_pcm_payload_carries_the_pipeline_sample_rate():
    """The live service asks for raw PCM at the transport's rate. Fish honours
    sample_rate (measured: 24k vs 16k returned bytes in a 1.335 ratio), so
    dropping it would hand the mixer audio at the wrong speed."""
    from agent_core.providers.fish_tts import build_payload

    payload = build_payload("hi", {"format": "pcm", "sample_rate": 24000})
    assert payload["format"] == "pcm"
    assert payload["sample_rate"] == 24000
    # mp3_bitrate is meaningless for pcm and must not be sent.
    assert "mp3_bitrate" not in payload
