"""Which surface owns the neural voice.

Two pickers can name a voice: Prompt Studio (``voice_config.voiceId``, reaching
the runtime as ``voice_name``) and the Sandbox Tuning Studio
(``AgentTuning.tts.voice``). ``resolve_session_tuning`` applied ``voice_name``
unconditionally, so the Tuning Studio choice was discarded on every call —
selecting William in the sandbox and hearing the published version's voice
answer instead.

Ground truth from the database at the time:

* ``prompt_versions.v1_4`` (published) — ``voice.voiceId = 'en-IN-AartiNeural'``,
  ``tuning.tts.voice`` NULL
* ``prompt_versions.v1_5`` (draft) — ``voice.voiceId = 'priya'``,
  ``tuning.tts.voice = 'en-IN-AartiNeural'``

The sandbox merges its own tuning over the version's, so ``tts.voice`` held the
picked voice — and then the overlay put the version's voice back.
"""

from __future__ import annotations

import pytest

from voice.tuning_apply import resolve_session_tuning

WILLIAM = "en-GB-RyanNeural"  # any voice that is not the Prompt Studio default
AARTI = "en-IN-AartiNeural"


def _voice(tuning: dict) -> str:
    return tuning["tts"]["voice"]


def test_tuning_studio_selection_beats_the_prompt_studio_voice() -> None:
    """The reported bug, directly."""
    resolved = resolve_session_tuning({"tts": {"voice": WILLIAM}}, voice_name=AARTI)
    assert _voice(resolved) == WILLIAM


def test_prompt_studio_voice_applies_when_tuning_names_none() -> None:
    """Unchanged path: a version published from Prompt Studio still picks its
    voice, because nothing more specific has claimed one."""
    resolved = resolve_session_tuning({"llm": {"temperature": 0.3}}, voice_name=AARTI)
    assert _voice(resolved) == AARTI


def test_an_empty_voice_string_does_not_count_as_a_choice() -> None:
    """Persisted jsonb carries "" and null for "not set" — neither is a pick."""
    for blank in ("", "   ", None):
        resolved = resolve_session_tuning({"tts": {"voice": blank}}, voice_name=AARTI)
        assert _voice(resolved) == AARTI


def test_no_voice_anywhere_falls_back_to_the_product_default() -> None:
    resolved = resolve_session_tuning({}, voice_name=None)
    assert _voice(resolved) == AARTI


def test_prosody_still_comes_from_tuning_not_the_overlay() -> None:
    """The precedence change must not disturb the style/rate/pitch contract —
    AgentTuning owns those, and the voice bot passes speed/pitch/warmth as None."""
    resolved = resolve_session_tuning(
        {"tts": {"voice": WILLIAM, "style": "serious", "rate": "0.98"}},
        voice_name=AARTI,
    )
    assert resolved["tts"]["style"] == "serious"
    assert resolved["tts"]["rate"] == "0.98"


@pytest.mark.parametrize("same", [AARTI, f"  {AARTI}  "])
def test_agreement_between_the_two_sources_is_a_no_op(same: str) -> None:
    """After a Prompt Studio publish the two agree — folding happens at publish
    time — so the runtime must behave identically whichever branch it takes."""
    assert _voice(resolve_session_tuning({"tts": {"voice": same}}, voice_name=AARTI)) == AARTI
