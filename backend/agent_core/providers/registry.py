"""The provider capability matrix, and what seeds it.

``providers`` already held credentials. This module holds the other half: what
each provider can actually *do*, per model, so binding can be a per-locale
decision rather than a per-product one.

Every ``service_class`` below was read off the installed Pipecat package, not
inferred from a provider slug. A wrong class path here is an ImportError on the
audio path of a live call, which is the one failure mode a registry must not
introduce.

Three honesty rules are baked into the seed data:

``code_switch`` means *within one sentence*.
    Language-ID routing does not qualify. Azure's continuous LID explicitly does
    not detect a language change inside a sentence, so ``azure`` is False even
    though it "supports multiple languages". Marking it True would let the
    binding layer route Gulf-Arabic traffic — which code-switches constantly —
    to a model that cannot follow it.

``locales = []`` means auto-detect, not "all locales well".
    Whisper-family models take ``language=None`` and detect. That is a different
    claim from "serves ar-AE at production quality", and the tier gate in the
    multilingual design is what turns one into the other.

``cost_per_unit`` is published pricing; ``measured_latency_*`` stays NULL.
    Vendor latency benchmarks are run on vendor audio. Ours get written by our
    own shadow runs against our own calls. NULL reads as "not measured yet",
    which is true and useful; a copied number would read as measured and be
    neither.
"""

from __future__ import annotations

import importlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Literal

logger = logging.getLogger(__name__)

# Emotion palette lives with the client that knows the syntax; the registry only
# re-exports it as data for the UI.
from agent_core.providers.fish_emotions import (  # noqa: E402
    EMOTION_TAGS_ADVANCED,
    EMOTION_TAGS_EFFECT,
    EMOTION_TAGS_EMOTION,
    EMOTION_TAGS_SCENE,
    EMOTION_TAGS_TONE,
)

Kind = Literal["stt", "tts", "llm"]


@dataclass(frozen=True)
class ModelSpec:
    """One (provider, kind, model) row of the capability matrix."""

    model_id: str
    display_name: str
    service_class: str
    kind: Kind
    locales: tuple[str, ...] = ()
    streaming: bool = True
    code_switch: bool = False
    on_prem: bool = False
    diarization: bool = False
    styles: tuple[str, ...] = ()
    cost_per_unit: float | None = None
    cost_unit: str | None = None
    notes: str = ""
    #: Controls this model actually honours. See PARAM_* below — every entry
    #: was confirmed against the live endpoint, not read off a vendor page.
    params_schema: tuple[dict[str, Any], ...] = ()
    #: False when the model can be auditioned but not run on a call — a
    #: request/response endpoint with no streaming integration behind it.
    #: Declared rather than inferred: the only way to detect it otherwise is to
    #: construct the service, and construction is what fails.
    live_capable: bool = True
    #: True when the same request twice gives a *different performance* — not
    #: encoder noise, but different pacing and emphasis. Sampling-based
    #: generative models do; parametric ones do not.
    #:
    #: This is the flag the studio uses to decide whether offering "new take"
    #: means anything. Offering it on a deterministic engine would be a control
    #: that visibly does nothing, which is the failure this file exists to stop.
    #:
    #: Measured 2026-08-22 — same voice, same text, three calls, spread in
    #: returned audio length:
    #:   azure     0%     (85248 bytes exactly, three times, cache cleared)
    #:   cartesia  6%     (90324 / 89070 / 85308)
    #:   fish      23%    (81919 / 87770 / 100727)
    #:   deepgram  39%    (29088 / 26784 / 37296)
    #: Fish cannot be pinned: its OpenAPI has no `seed` on TTSRequest, and
    #: temperature only narrows the spread (24.8% at 0.7 → 8.6% at 0.0).
    sampling: bool = False


def _num(key, label, *, lo, hi, step, default, transport, help=""):
    """One numeric control descriptor.

    ``transport`` is load-bearing: ``body`` is a top-level JSON field on the
    speech request, ``ssml`` is an Azure prosody attribute. A control with no
    transport has nowhere to go, which is what stops a knob being decoration.
    """
    return {
        "key": key, "label": label, "kind": "number", "min": lo, "max": hi,
        "step": step, "default": default, "transport": transport, "help": help,
    }


#: Azure: a parametric synthesiser. Prosody rides in the SSML envelope.
PARAM_AZURE_TTS: tuple[dict[str, Any], ...] = (
    _num("rate", "Speed", lo=0.5, hi=2.0, step=0.01, default=1.0, transport="ssml",
         help="SSML prosody rate."),
    _num("pitch", "Pitch", lo=-50, hi=50, step=1, default=0, transport="ssml",
         help="Semitone offset, rendered as an SSML percentage."),
    _num("warmth", "Warmth", lo=0, hi=100, step=1, default=62, transport="ssml",
         help="Drives mstts:express-as style degree where the voice supports it."),
    _num("pause_ms", "Sentence pause", lo=0, hi=1200, step=10, default=320,
         transport="ssml", help="Break inserted between sentences."),
)

#: Fish S2.1 Pro via OpenRouter. A *generative* TTS — it has no pitch or style
#: knob at all; you steer the sampler. Every entry below was measured against
#: the live endpoint on 2026-08-21:
#:   speed 0.5 -> 1.94x duration, speed 2.0 -> 0.51x  (works)
#:   provider.options.prosody and X-Fish-* headers   (silently ignored)
#: The ignored paths are Fish's native API and do not survive the OpenRouter
#: hop, so they are deliberately absent rather than present-and-dead.
PARAM_FISH_TTS: tuple[dict[str, Any], ...] = (
    _num("speed", "Speed", lo=0.25, hi=4.0, step=0.05, default=1.0, transport="body",
         help="OpenAI-standard speed. Verified: 0.5 nearly doubles duration."),
    _num("temperature", "Temperature", lo=0.1, hi=2.0, step=0.05, default=0.7,
         transport="body",
         help="Higher is more expressive and less repeatable between takes."),
    _num("top_p", "Top-p", lo=0.1, hi=1.0, step=0.05, default=0.9, transport="body",
         help="Nucleus sampling over the acoustic tokens."),
    _num("repetition_penalty", "Repetition penalty", lo=1.0, hi=2.0, step=0.05,
         default=1.1, transport="body",
         help="Discourages the stutter/loop failure generative TTS is prone to."),
)

#: Fish Audio direct API. Verified against api.fish.audio/openapi.json — this is
#: a strictly larger surface than the OpenRouter passthrough: prosody and
#: latency are real here, and the voice library exists.
PARAM_FISH_DIRECT: tuple[dict[str, Any], ...] = (
    _num("speed", "Speed", lo=0.5, hi=2.0, step=0.05, default=1.0, transport="body",
         help="prosody.speed. 1.0 is normal; the vendor's documented range."),
    _num("volume", "Volume", lo=-20, hi=20, step=1, default=0, transport="body",
         help="prosody.volume in dB."),
    # Bounds below are the vendor's own, read from api.fish.audio/openapi.json
    # (TTSRequest) rather than estimated. temperature and top_p are capped at
    # 1.0 there, and chunk_length is 100-300 — a slider that let an operator
    # send 2.0 or 1000 was offering settings the endpoint rejects with a 422.
    _num("temperature", "Temperature", lo=0.0, hi=1.0, step=0.05, default=0.7,
         transport="body", help="Expressiveness. Higher varies more between takes."),
    _num("top_p", "Top-p", lo=0.0, hi=1.0, step=0.05, default=0.7, transport="body"),
    _num("repetition_penalty", "Repetition penalty", lo=1.0, hi=2.0, step=0.05,
         default=1.2, transport="body",
         help="Above 1.0 reduces the stutter/loop failure generative TTS is prone to."),
    _num("chunk_length", "Chunk length", lo=100, hi=300, step=10, default=300,
         transport="body", help="Characters per synthesis segment."),
    {
        "key": "latency", "label": "Latency mode", "kind": "enum",
        "options": ["low", "normal", "balanced"], "default": "normal",
        "transport": "body",
        "help": "low trades stability for time-to-first-audio.",
    },
    {
        "key": "normalize", "label": "Normalize text", "kind": "bool",
        "default": True, "transport": "body",
        "help": "Improves stability on numbers and dates in English/Chinese.",
    },
    {
        # Not a slider. S2 takes free-form [bracket] directions anywhere in the
        # text and accepts ~any description, so the control is an insert-into-
        # text palette, not a closed dropdown. Tags are never spoken.
        "key": "emotion_tags", "label": "Emotion & effect markers", "kind": "tag_palette",
        "syntax": "[tag]", "max_per_sentence": 3, "transport": "text",
        "groups": {
            "emotion": list(EMOTION_TAGS_EMOTION),
            "advanced": list(EMOTION_TAGS_ADVANCED),
            "tone": list(EMOTION_TAGS_TONE),
            "effect": list(EMOTION_TAGS_EFFECT),
            "scene": list(EMOTION_TAGS_SCENE),
        },
        "help": "Inserted into the text as [tag]. Placement is meaning: a tag applies from where it sits onward.",
    },
)


#: Cartesia exposes no working prosody control on sonic-3.5.
#:
#: This schema used to carry a slow/normal/fast "Pace" enum, measured on
#: sonic-2 where it moved duration ~6%. That model is now **sunsetted**, and on
#: sonic-3.5 the control is accepted-and-ignored, which is worse than rejected:
#: the API validates ``__experimental_controls.speed`` to a float in [-1.0, 1.0]
#: and then produces the same audio either way. Measured 2026-08-22, n=5 per
#: setting on identical text (mp3 CBR, so bytes track duration):
#:
#:   speed=-1.0  78119 +/- 1682
#:   baseline    78370 +/- 1635
#:   speed=+1.0  79708 +/- 2874
#:
#: Fully overlapping, and the extremes run the wrong way round. A knob the
#: vendor validates but ignores is the hardest kind to catch, so the honest
#: schema is empty: the inspector then says this model exposes no tunable
#: controls, which is true, instead of offering a pace that does nothing.
PARAM_CARTESIA_TTS: tuple[dict[str, Any], ...] = ()

#: Deepgram Aura-2 exposes encoding and sample rate, not prosody — there is no
#: speed or pitch control on this model. An empty-ish schema is the honest
#: answer; inventing sliders would give the operator controls that do nothing.
PARAM_DEEPGRAM_TTS: tuple[dict[str, Any], ...] = (
    {
        "key": "encoding", "label": "Encoding", "kind": "enum",
        "options": ["mp3", "linear16", "opus"], "default": "mp3",
        "transport": "query",
        "help": "Container/codec. Aura-2 has no prosody controls.",
    },
)


@dataclass(frozen=True)
class ProviderSpec:
    """A vendor, its credential env var, and the models it exposes."""

    slug: str
    name: str
    category: str
    #: Env var holding the comma-separated key pool. None = no key needed.
    key_env: str | None
    models: tuple[ModelSpec, ...] = field(default_factory=tuple)
    #: Extra non-secret config the service constructor needs (e.g. region).
    extra_env: tuple[str, ...] = ()


# --------------------------------------------------------------------- the seed

SEED: tuple[ProviderSpec, ...] = (
    ProviderSpec(
        slug="azure",
        name="Microsoft Azure",
        category="speech",
        key_env="AZURE_SPEECH",
        extra_env=("AZURE_SPEECH_REGION",),
        models=(
            ModelSpec(
                kind="stt",
                model_id="azure-stt",
                display_name="Azure Speech-to-Text",
                service_class="pipecat.services.azure.stt.AzureSTTService",
                # At-start LID takes <=4 candidates, continuous LID <=10, and
                # neither follows a switch inside a sentence.
                code_switch=False,
                on_prem=True,
                notes="Container deployment available from MCR for disconnected use.",
            ),
            ModelSpec(
                kind="tts",
                model_id="azure-neural",
                display_name="Azure Neural TTS",
                # Deliberately our subclass, not Pipecat's base class. The base
                # opens the synthesis websocket lazily on the first turn, which
                # measured as a per-call cold start the pipeline already pays to
                # avoid (voice/tts_pool.py). Naming the base class here would
                # have made binding Azure through the registry a silent latency
                # regression against constructing it directly.
                service_class="voice.tts_pool.KeepAliveAzureTTSService",
                on_prem=True,
                styles=("friendly", "serious", "empathetic", "cheerful", "calm"),
                cost_per_unit=15.0,
                cost_unit="usd_per_1m_chars",
                params_schema=PARAM_AZURE_TTS,
                notes="~400 voices / 140 locales, including ~20 Arabic regional locales.",
            ),
        ),
    ),
    ProviderSpec(
        slug="deepgram",
        name="Deepgram",
        category="speech",
        key_env="DEEPGRAM",
        models=(
            ModelSpec(
                kind="stt",
                model_id="nova-3-general",
                display_name="Nova-3",
                service_class="pipecat.services.deepgram.stt.DeepgramSTTService",
                diarization=True,
                notes="Real-time multilingual mode via language='multi'. No Arabic code-switching.",
            ),
            ModelSpec(
                kind="tts",
                model_id="aura-2-thalia-en",
                display_name="Aura-2",
                service_class="pipecat.services.deepgram.tts.DeepgramTTSService",
                locales=("en-US",),
                params_schema=PARAM_DEEPGRAM_TTS,
                # Widest spread of any provider measured — 39%. Aura-2 re-paces
                # the whole line between takes.
                sampling=True,
                cost_per_unit=30.0,
                cost_unit="usd_per_1m_chars",
            ),
        ),
    ),
    ProviderSpec(
        slug="cartesia",
        name="Cartesia",
        category="speech",
        key_env="CARTESIA",
        models=(
            ModelSpec(
                kind="tts",
                model_id="sonic-3.5",
                display_name="Sonic 3.5",
                service_class="pipecat.services.cartesia.tts.CartesiaTTSService",
                styles=("neutral", "excited", "calm"),
                params_schema=PARAM_CARTESIA_TTS,
                sampling=True,
                notes="Lowest time-to-first-audio of the hosted options. Free tier is "
                "~20k credits/month and is personal/non-commercial use only.",
            ),
            ModelSpec(
                kind="stt",
                model_id="ink-whisper",
                display_name="Cartesia STT",
                service_class="pipecat.services.cartesia.stt.CartesiaSTTService",
            ),
        ),
    ),
    ProviderSpec(
        slug="elevenlabs",
        name="ElevenLabs",
        category="speech",
        key_env="ELEVENLABS",
        models=(
            ModelSpec(
                kind="tts",
                model_id="eleven_multilingual_v2",
                display_name="Multilingual v2",
                service_class="pipecat.services.elevenlabs.tts.ElevenLabsTTSService",
                notes="70+ locales including Arabic. Free tier ~10k credits/month "
                "(~10 min) — bind to demo voices, never to a default.",
            ),
            ModelSpec(
                kind="tts",
                model_id="eleven_flash_v2_5",
                display_name="Flash v2.5",
                service_class="pipecat.services.elevenlabs.tts.ElevenLabsTTSService",
                notes="Lower latency than Multilingual v2; Arabic not in this model.",
            ),
            ModelSpec(
                kind="stt",
                model_id="scribe_v2_realtime",
                display_name="Scribe v2 Realtime",
                service_class="pipecat.services.elevenlabs.stt.ElevenLabsRealtimeSTTService",
                notes="Strongest published code-switching WER of the hosted options.",
            ),
        ),
    ),
    ProviderSpec(
        slug="groq",
        name="Groq",
        category="speech",
        key_env="GROQ",
        models=(
            ModelSpec(
                kind="stt",
                model_id="whisper-large-v3-turbo",
                display_name="Whisper large-v3 turbo",
                service_class="pipecat.services.groq.stt.GroqSTTService",
                # Whisper auto-detects; that is detection, not production quality.
                locales=(),
                notes="Rate-limited rather than credit-limited, so it cannot exhaust "
                "quota mid-demo. Good default fallback in the failover chain.",
            ),
        ),
    ),
    ProviderSpec(
        slug="gladia",
        name="Gladia",
        category="speech",
        key_env="GLADIA",
        models=(
            ModelSpec(
                kind="stt",
                model_id="solaria-1",
                display_name="Solaria-1",
                service_class="pipecat.services.gladia.stt.GladiaSTTService",
                code_switch=True,
                cost_per_unit=0.75,
                cost_unit="usd_per_hour",
                notes="100+ languages with real-time code-switching in one session. "
                "Free tier ~10 hrs/month, recurring.",
            ),
        ),
    ),
    ProviderSpec(
        slug="fish",
        name="Fish Audio",
        category="speech",
        key_env="FISH",
        extra_env=("FISH_BASE_URL", "FISH_TTS_MODEL"),
        models=(
            ModelSpec(
                kind="tts",
                model_id="s2.1-pro",
                display_name="Fish S2.1 Pro",
                service_class="agent_core.providers.fish_service.FishTTSService",
                locales=(),
                streaming=False,
                params_schema=PARAM_FISH_DIRECT,
                # Autoregressive with temperature/top_p sampling and no seed in
                # the API, so a take is not reproducible even at temperature 0.
                sampling=True,
                notes=(
                    "Direct API: 1,000-voice library via GET /model, real prosody "
                    "and latency controls, and free-form [bracket] emotion markers. "
                    "Synthesis needs API credit (billed separately from platform "
                    "credit); listing voices does not. When the direct call 402s, "
                    "the binding chain falls through to the OpenRouter route, which "
                    "accepts the same library voice ids and the same emotion tags."
                ),
            ),
        ),
    ),
    ProviderSpec(
        slug="openrouter",
        name="OpenRouter",
        category="speech",
        key_env="OPENROUTER",
        extra_env=("OPENROUTER_BASE_URL",),
        models=(
            ModelSpec(
                kind="tts",
                model_id="fish-audio/s2.1-pro-free:free",
                display_name="Fish Audio S2.1 Pro",
                # No Pipecat integration ships for OpenRouter audio, so this is
                # served by our own OpenAI-compatible client rather than a
                # pipecat.services.* class. The registry stores the real path so
                # the factory does not have to special-case a provider slug.
                service_class="agent_core.providers.openrouter_tts.OpenRouterTTSService",
                # 80+ languages, auto-detected from the text — no locale field.
                locales=(),
                streaming=False,
                # Request/response only: OpenRouterTTSService raises on
                # construction rather than returning a service that yields no
                # frames. Declared here so the studio can say "audition only"
                # instead of offering a binding that silently falls back.
                live_capable=False,
                params_schema=PARAM_FISH_TTS,
                notes=(
                    "Generative TTS: steered by sampler settings, not a prosody "
                    "envelope. One default voice — OpenRouter exposes no voice "
                    "list, and sending voice:\"\" is a 400, so the field is "
                    "omitted entirely. Free tier is rate-limited and carries no "
                    "latency or availability guarantee, so bind it as a "
                    "fallback or for auditioning, never as a production default."
                ),
            ),
        ),
    ),
    ProviderSpec(
        slug="speechmatics",
        name="Speechmatics",
        category="speech",
        key_env="SPEECHMATICS",
        models=(
            ModelSpec(
                kind="stt",
                model_id="ursa-2",
                display_name="Ursa 2",
                service_class="pipecat.services.speechmatics.stt.SpeechmaticsSTTService",
                on_prem=True,
                diarization=True,
                cost_per_unit=0.129,
                cost_unit="usd_per_hour",
            ),
            ModelSpec(
                kind="stt",
                model_id="bilingual-ar-en",
                display_name="Arabic–English bilingual",
                service_class="pipecat.services.speechmatics.stt.SpeechmaticsSTTService",
                locales=("ar-AE", "ar-SA", "ar-EG", "en-GB", "en-US"),
                code_switch=True,
                on_prem=True,
                notes="Handles Arabic/English switching inside one sentence. "
                "On-prem requires the GPU container (>=16GB VRAM, CUDA 7.5+); "
                "verify CPU-container availability with the vendor before planning.",
            ),
        ),
    ),
)

SEED_BY_SLUG: dict[str, ProviderSpec] = {p.slug: p for p in SEED}


def model_specs(kind: Kind | None = None) -> list[tuple[ProviderSpec, ModelSpec]]:
    """Flatten the seed to (provider, model) pairs, optionally filtered by kind."""
    out: list[tuple[ProviderSpec, ModelSpec]] = []
    for provider in SEED:
        for model in provider.models:
            if kind is None or model.kind == kind:
                out.append((provider, model))
    return out


def find_model(provider_slug: str, model_id: str) -> ModelSpec | None:
    provider = SEED_BY_SLUG.get(provider_slug)
    if provider is None:
        return None
    return next((m for m in provider.models if m.model_id == model_id), None)


#: Probe results, cached: importing a Pipecat service module is slow and its
#: outcome cannot change without a restart.
_RUNTIME_CACHE: dict[str, tuple[str, str]] = {}

#: Runtime states a model can be in.
RUNTIME_LIVE = "live"
RUNTIME_PREVIEW_ONLY = "preview_only"
RUNTIME_UNAVAILABLE = "unavailable"


def runtime_status(model: ModelSpec) -> tuple[str, str]:
    """Whether ``model`` can actually be constructed for a call, and why not.

    The registry is a set of claims about what the system can do, and until this
    existed nothing checked them. Three of the seeded models could not be built
    at all — Fish named a class that did not exist, and the Deepgram and
    Speechmatics recognisers need Pipecat extras that are not installed — yet
    all three were offered in the Agent Studio as freely as the working ones.
    Binding one produced a call that quietly ran Azure instead.

    Imports the module and resolves the class; deliberately does *not*
    instantiate, because construction needs credentials and, for a preview-only
    model, is exactly what raises.
    """
    cached = _RUNTIME_CACHE.get(model.service_class)
    if cached is not None:
        return cached

    if not model.live_capable:
        result = (RUNTIME_PREVIEW_ONLY, "No streaming integration — audition only.")
    else:
        module_path, _, cls_name = model.service_class.rpartition(".")
        try:
            module = importlib.import_module(module_path)
            getattr(module, cls_name)
            result = (RUNTIME_LIVE, "")
        except Exception as exc:  # noqa: BLE001 - any failure is unavailability
            result = (RUNTIME_UNAVAILABLE, f"{type(exc).__name__}: {exc}"[:200])
            logger.warning(
                "model not constructable · provider=%s · model=%s · %s",
                model.model_id,
                model.service_class,
                result[1],
            )

    _RUNTIME_CACHE[model.service_class] = result
    return result


def configured_providers() -> set[str]:
    """Slugs whose key pool is non-empty, i.e. actually usable right now.

    The Agent Studio shows every seeded provider, but marks the unconfigured
    ones — a picker that silently hides a provider makes "why can't I choose
    ElevenLabs?" unanswerable from the screen.
    """
    from agent_core.providers import pool as pool_mod

    live: set[str] = set()
    for provider in SEED:
        if provider.key_env is None:
            live.add(provider.slug)
            continue
        if len(pool_mod.get_pool(provider.slug)) > 0:
            live.add(provider.slug)
    return live


def as_rows() -> list[dict[str, Any]]:
    """Seed rendered for the upsert in :mod:`agent_core.providers.persist`."""
    rows: list[dict[str, Any]] = []
    for provider, model in model_specs():
        rows.append(
            {
                "id": f"pm-{provider.slug}-{model.kind}-{model.model_id}",
                "provider_id": provider.slug,
                "kind": model.kind,
                "model_id": model.model_id,
                "display_name": model.display_name,
                "service_class": model.service_class,
                "locales": list(model.locales),
                "streaming": model.streaming,
                "code_switch": model.code_switch,
                "on_prem": model.on_prem,
                "diarization": model.diarization,
                "styles": list(model.styles),
                "cost_per_unit": model.cost_per_unit,
                "cost_unit": model.cost_unit,
                "params_schema": json.dumps(list(model.params_schema)),
                "notes": model.notes,
            }
        )
    return rows
