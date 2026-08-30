"""The Studio's language list and the runtime's must be the same list.

`Habibi/src/data/prompt-studio-seed.ts` offers the languages an operator can
pick; `agent_core/languages.py` owns the BCP-47 tag each one binds. They are
hand-written mirrors across a JSON boundary no type system spans — the same
situation as the Agent Card, and guarded the same way.

Drift is silent in both directions and neither is harmless. A name only the
frontend knows is a language you can select and publish that binds no
recogniser; a name only the backend knows is a supported language nobody can
choose. The tags matter as much as the names: "Bengali" is bn-IN here and bn-BD
one border away, so the pairing is the fact, not the name.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent_core import languages

_TS_SEED = (
    Path(__file__).resolve().parents[2]
    / "Habibi"
    / "src"
    / "data"
    / "prompt-studio-seed.ts"
)


def _ts_entries() -> list[tuple[str, str]]:
    """Name/tag pairs from the exported `LANGUAGE_ENTRIES` constant."""
    if not _TS_SEED.exists():  # pragma: no cover - frontend not checked out
        pytest.skip(f"frontend seed not present at {_TS_SEED}")
    src = _TS_SEED.read_text(encoding="utf-8")
    match = re.search(r"LANGUAGE_ENTRIES\s*=\s*\[(.*?)\]\s*as const", src, re.S)
    assert match, "LANGUAGE_ENTRIES not found in prompt-studio-seed.ts"
    return re.findall(r'name:\s*"([^"]+)",\s*tag:\s*"([^"]+)"', match.group(1))


def test_the_two_lists_pair_the_same_names_with_the_same_tags() -> None:
    assert _ts_entries() == [(e.name, e.tag) for e in languages.LANGUAGES]


def test_every_tag_binds_a_real_recogniser_language() -> None:
    """A tag with no pipecat member falls back to en-IN, silently."""
    from voice.tuning_apply import normalize_language

    default = normalize_language(languages.DEFAULT_TAG)
    for entry in languages.LANGUAGES:
        if entry.tag == languages.DEFAULT_TAG:
            continue
        assert normalize_language(entry.tag) != default, entry


def test_the_default_is_one_of_the_offered_languages() -> None:
    assert languages.name_for(languages.DEFAULT_TAG) == languages.DEFAULT_NAME
    assert languages.DEFAULT_NAME in languages.names()
