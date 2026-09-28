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


# --- The bag itself ---------------------------------------------------------


# --- The overlay ------------------------------------------------------------


# --- What the provider is handed -------------------------------------------


# --- Persistence ------------------------------------------------------------


def test_source_payload_carries_the_idle_clamp_note():
    from voice.persist import _voice_source_payload

    payload = _voice_source_payload(
        transport="twilio",
        bot_id="BOT-1",
        accountable_user_id=None,
        tuning_clamp=[{"field": "idle_timeout_secs", "requested": 28, "clamped": 20.0}],
    )
    assert payload["tuningClamp"] == [
        {"field": "idle_timeout_secs", "requested": 28, "clamped": 20.0},
    ]


