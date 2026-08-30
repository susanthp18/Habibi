"""Provider-specific TTS controls reach a real call.

The Prompt Studio Voice tab renders whatever the selected model declares in
``provider_models.params_schema`` — nine controls for Fish S2.1 Pro, four for
Azure, almost none for Deepgram Aura-2. Those controls changed the preview and
nothing else, and the reason was structural rather than a bug anyone wrote:

* they lived in ``VoicePanel``'s React state, not on ``VoiceConfig``, so they
  did not mark the editor dirty, did not autosave, did not survive a tab
  switch and were not published;
* ``AgentTuning.tts`` is Azure/SSML-shaped (voice, style, style_degree, rate,
  pitch, volume, emphasis) with no slot for anything else;
* ``apply_voice_config_overlay`` accepted exactly four scalars.

So an operator could tune a Fish temperature, hear the difference, publish, and
get the vendor default on every call — with nothing on screen to say so.

The path this pins: ``VoiceConfig.params`` → ``db._prompt_voice`` →
``apply_voice_config_overlay`` → ``AgentTuning.tts.params`` →
``tts_settings_kwargs`` → the bound provider's ``Settings``. Nothing here
decides which keys a given vendor accepts; ``providers.factory.build`` filters
against that model's own ``Settings`` class, which is the only thing that knows.
"""

from __future__ import annotations

import math

import pytest

import db
from agent_core.tuning import (
    MAX_TTS_PARAMS,
    apply_voice_config_overlay,
    default_tuning,
    live_delta_only,
    normalize_tts_params,
    normalize_tuning,
)
from voice.tuning_apply import tts_settings_kwargs


# --- The bag itself ---------------------------------------------------------


def test_a_param_survives_normalization():
    """The plain case, and the one that used to be impossible: a key
    ``AgentTuning`` has never heard of is carried rather than dropped."""
    tuning = normalize_tuning({"tts": {"params": {"temperature": 0.7, "normalize": True}}})
    assert tuning["tts"]["params"] == {"temperature": 0.7, "normalize": True}


def test_an_empty_bag_leaves_no_trace():
    """Every tuning stored before this key existed has no ``params``. Inventing
    ``{}`` on all of them would rewrite each one on first read and surface as a
    diff on versions nobody edited."""
    assert "params" not in normalize_tuning({})["tts"]
    assert "params" not in normalize_tuning({"tts": {"params": {}}})["tts"]
    assert "params" not in default_tuning()["tts"]


@pytest.mark.parametrize(
    "value",
    [{"nested": {"no": 1}}, {"listy": [1, 2]}, {"nothing": None}],
)
def test_only_scalars_are_kept(value):
    """A provider setting is a scalar. A dict or a list here is a hand-edited
    row or a client bug, and splatting one into a constructor is a TypeError in
    the middle of call setup."""
    assert normalize_tts_params(value) == {}


def test_a_nan_never_reaches_a_vendor():
    """``float("nan")`` round-trips through JSON in some clients. It compares
    false against everything, so nothing downstream clamps it — it arrives at
    the provider as a 422 mid-call, or worse, silently."""
    assert normalize_tts_params({"temperature": math.nan}) == {}
    assert normalize_tts_params({"temperature": math.inf}) == {}


def test_the_bag_cannot_name_the_voice_or_the_language():
    """``voice`` is resolved by a precedence rule between the Tuning Studio and
    the Prompt Studio picker, and ``language`` comes from the STT locale.
    Letting a param win either would make that rule unreachable and the chosen
    voice silently wrong."""
    cleaned = normalize_tts_params({"voice": "en-US-Somebody", "language": "fr-FR", "top_p": 0.9})
    assert cleaned == {"top_p": 0.9}


def test_the_bag_is_bounded():
    """Read off a jsonb column and splatted into a constructor. Unbounded is a
    way to turn one hand-edited row into a memory problem."""
    cleaned = normalize_tts_params({f"k{i}": i for i in range(MAX_TTS_PARAMS + 25)})
    assert len(cleaned) == MAX_TTS_PARAMS


# --- The overlay ------------------------------------------------------------


def test_the_overlay_carries_params_alongside_the_sliders():
    folded = apply_voice_config_overlay(
        default_tuning(),
        voice_name="en-IN-AartiNeural",
        speed=1.0,
        pitch=0,
        warmth=80,
        params={"temperature": 0.65, "chunk_length": 200},
    )
    assert folded["tts"]["params"] == {"temperature": 0.65, "chunk_length": 200}
    # The Azure-shaped half still works — warmth 80 is the "friendly" band.
    assert folded["tts"]["style"] == "friendly"


def test_params_replace_rather_than_merge():
    """The Voice tab shows one model's controls, so a key that is no longer on
    screen is one the operator can neither see nor clear. Merging would leave a
    Fish temperature bound to an Azure voice with nothing in the UI to show it.
    """
    fish = apply_voice_config_overlay(default_tuning(), params={"temperature": 0.9, "top_p": 0.8})
    azure = apply_voice_config_overlay(fish, params={"style_degree_hint": 1})
    assert azure["tts"]["params"] == {"style_degree_hint": 1}


def test_none_means_leave_it_alone():
    """Every caller that does not author voice params — Sandbox Promote, the
    legacy prosody path — passes nothing, and must not thereby erase them."""
    seeded = apply_voice_config_overlay(default_tuning(), params={"temperature": 0.5})
    untouched = apply_voice_config_overlay(seeded, speed=1.1)
    assert untouched["tts"]["params"] == {"temperature": 0.5}


# --- What the provider is handed -------------------------------------------


def test_params_are_handed_to_the_provider():
    """The step that was missing entirely. ``provider_bind.bind`` passes these
    kwargs to ``factory.build_first_available``, which merges them over the
    binding's stored settings and filters them against the bound model's own
    ``Settings`` class."""
    kwargs = tts_settings_kwargs(
        normalize_tuning({"tts": {"params": {"temperature": 0.7, "latency": "balanced"}}})
    )
    assert kwargs["temperature"] == 0.7
    assert kwargs["latency"] == "balanced"


def test_the_sliders_win_over_the_bag():
    """``rate`` is both an Azure control and a ``VoiceConfig`` column, and the
    column is what ``apply_voice_config_overlay`` derives from ``speed``. One
    control with two authorities that can disagree is the bug this ordering
    exists to prevent — after a Tuning Studio edit, the tuning is right."""
    tuning = apply_voice_config_overlay(
        default_tuning(), speed=1.0, params={"rate": "9.99", "temperature": 0.3}
    )
    kwargs = tts_settings_kwargs(tuning)
    assert kwargs["rate"] == "1.03"  # 1.0 nudged for the phone, not 9.99
    assert kwargs["temperature"] == 0.3


def test_the_azure_fallback_survives_another_vendors_params():
    """A card authored against a Fish voice whose binding is missing at call
    time still reaches the pre-registry Azure path. An undeclared kwarg there is
    a ``TypeError`` during pipeline construction, which drops the *call* rather
    than the setting."""
    pytest.importorskip("pipecat.services.azure.tts")
    from voice.tuning_apply import build_tts_settings

    settings = build_tts_settings(
        normalize_tuning({"tts": {"params": {"temperature": 0.7, "chunk_length": 200}}})
    )
    assert settings is not None


def test_the_provider_filter_can_read_a_dataclass_settings_class():
    """The filter every provider's construction depends on, and it was a no-op.

    ``factory.build`` narrowed settings with ``getattr(cls, "model_fields", {})``
    — a pydantic idiom — and Pipecat 1.6.0's Settings classes are dataclasses.
    The lookup returned ``{}`` for every provider, the ``if not allowed`` guard
    read that as "unknown class, pass everything", and the filter passed every
    key straight through to the constructor for as long as it existed.

    Nothing depended on it while only Azure's own settings were in play. It
    becomes load-bearing the moment a card can carry another vendor's params.
    """
    pytest.importorskip("pipecat.services.azure.tts")
    from pipecat.services.azure.tts import AzureTTSService

    from agent_core.providers.factory import settings_field_names

    allowed = settings_field_names(AzureTTSService.Settings)
    assert "rate" in allowed and "style" in allowed and "voice" in allowed
    assert "temperature" not in allowed


def test_the_filter_falls_back_rather_than_refusing():
    """An empty answer means "could not tell", and callers pass everything
    through. Refusing to construct a service because this helper did not
    recognise its Settings class would be worse than the bug it fixes."""
    from agent_core.providers.factory import settings_field_names

    class Pydanticish:
        model_fields = {"alpha": object(), "beta": object()}

    @__import__("dataclasses").dataclass
    class Dataish:
        gamma: int = 1

    class Plain:
        def __init__(self, delta=None, **kwargs):
            self.delta = delta

    assert settings_field_names(Pydanticish) == frozenset({"alpha", "beta"})
    assert settings_field_names(Dataish) == frozenset({"gamma"})
    # **kwargs is not a declared name, so it must not be offered as one.
    assert settings_field_names(Plain) == frozenset({"delta"})
    assert settings_field_names(None) == frozenset()


def test_a_mid_call_param_change_is_live_tunable():
    """``tts`` is in ``LIVE_TUNABLE_SECTIONS``, so a Studio delta touching a
    param should reach the running pipeline rather than waiting for the next
    call."""
    live = live_delta_only({"tts": {"params": {"temperature": 0.2}}, "vad": {"confidence": 0.9}})
    assert live == {"tts": {"params": {"temperature": 0.2}}}


# --- Persistence ------------------------------------------------------------


def test_the_voice_column_keeps_params():
    """``_prompt_voice`` is a whitelist: a key it does not name is dropped on
    the way into ``prompt_versions.voice``. That is precisely how the Voice
    tab's model controls used to reach the preview and nothing else."""
    stored = db._prompt_voice({"voiceId": "en-IN-AartiNeural", "params": {"temperature": 0.4}})
    assert stored["params"] == {"temperature": 0.4}


def test_the_voice_column_sanitizes_what_it_keeps():
    """Same helper as the tuning path, so what is stored on the version and what
    is folded into the deployment cannot disagree about what a param is."""
    stored = db._prompt_voice({"params": {"ok": 1, "nested": {"no": True}, "voice": "hijack"}})
    assert stored["params"] == {"ok": 1}
