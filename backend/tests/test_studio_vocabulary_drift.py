"""Seven vocabularies the studio restates from the backend, each pinned to its owner.

Same idea as `test_agent_card_schema_drift`: two type systems on opposite sides
of a JSON boundary, so no compiler spans them and a hand-written mirror rots
quietly. Each test here fails when either side is edited alone. Where the TS
side can import a value, it imports `src/lib/studio-vocabulary.json`, which is
the Python owner's export; where it cannot (a `Literal`, a `Record` key set), the
TS source is read as text.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import get_args

from tests.conftest import frontend_file

BACKEND = Path(__file__).resolve().parents[1]


def _src(*parts: str) -> str:
    return frontend_file(*parts).read_text(encoding="utf-8")


def _ts_const_list(src: str, name: str) -> set[str]:
    match = re.search(rf"\b{name}\s*=\s*\[(.*?)\]\s*as const", src, re.S)
    assert match, f"{name} not found"
    return set(re.findall(r'"([^"]+)"', match.group(1)))


def _vocabulary() -> dict:
    return json.loads(_src("src", "lib", "studio-vocabulary.json"))


# 1. reachability ------------------------------------------------------------


# 2. prompt tokens -----------------------------------------------------------

def _ts_regex_source(src: str, name: str) -> str:
    match = re.search(rf"export const {name} = /(.*)/g;", src)
    assert match, f"{name} not found"
    return match.group(1)


# 3. mouth defaults ----------------------------------------------------------


# 4. tuning presets ----------------------------------------------------------

def test_the_browser_holds_no_tuning_presets() -> None:
    """`GET /sandbox/tuning/presets` is the owner. The browser's four had drifted
    (idle_timeout_secs 5 vs 10, style empathetic vs serious)."""
    assert "AGENT_TUNING_PRESETS" not in _src("src", "data", "agent-tuning.ts")
    assert "AGENT_TUNING_PRESETS" not in _src("src", "components", "sandbox", "TuningStudio.tsx")
    assert '"/sandbox/tuning/presets"' in _src("src", "api", "voice-sandbox.ts")


# 5. objectives --------------------------------------------------------------


# 6. eval requirements -------------------------------------------------------


# 7. locked engines ----------------------------------------------------------


# stripped globals (G16) -----------------------------------------------------


def test_the_whatsapp_history_check_is_the_same_detector() -> None:
    """bot_runtime kept a fourth copy -- four substrings -- that accepted
    "recorded for quality" and rejected the wording the pattern accepts.
    One detector: whatever mentions_recording_disclosure says, the history
    check says."""
    import bot_conversation
    from agent_core.guardrails import mentions_recording_disclosure

    said = "This conversation may be recorded for training and quality purposes."
    assert mentions_recording_disclosure(said)
    assert bot_conversation.history_already_disclosed_recording(
        [{"role": "assistant", "content": said}]
    )
    assert not bot_conversation.history_already_disclosed_recording(
        [{"role": "user", "content": said}, {"role": "assistant", "content": "I'll record that in the CRM."}]
    )


# 7. eval suite kinds --------------------------------------------------------

