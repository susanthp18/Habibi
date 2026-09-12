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

def test_reachability_labels_have_one_ts_owner_and_match_the_literal() -> None:
    """`ROUTING` in lib/agent-roster.ts is the one TS owner; the fleet index and
    the Agent Graph tab both read it. Its keys are `schemas.AgentStudioReachability`."""
    import schemas

    src = _src("src", "lib", "agent-roster.ts")
    match = re.search(r"export const ROUTING: Record<.*?\n> = \{(.*?)\n\};", src, re.S)
    assert match, "ROUTING not found in agent-roster.ts"
    keys = set(re.findall(r"^\s{2}(\w+):\s*\{", match.group(1), re.M))
    assert keys == set(get_args(schemas.AgentStudioReachability))
    # No second copy anywhere the fleet renders it.
    graph_tab = _src("src", "components", "prompt-studio", "panels", "AgentGraphTab.tsx")
    assert "ROUTE_TONE" not in graph_tab and "ROUTE_HELP" not in graph_tab
    assert 'import { ROUTING } from "@/lib/agent-roster"' in graph_tab


# 2. prompt tokens -----------------------------------------------------------

def _ts_regex_source(src: str, name: str) -> str:
    match = re.search(rf"export const {name} = /(.*)/g;", src)
    assert match, f"{name} not found"
    return match.group(1)


def test_prompt_token_regexes_match() -> None:
    import prompt_lint
    import prompt_render
    from flow_vars import TEMPLATE_RE

    seed = _src("src", "lib", "prompt-studio.ts")
    assert _ts_regex_source(seed, "FLOW_TOKEN_RE") == TEMPLATE_RE.pattern
    assert prompt_lint._FLOW_TOKEN_RE is TEMPLATE_RE
    assert _ts_regex_source(seed, "PROMPT_TOKEN_RE") == prompt_render.TOKEN_RE.pattern


# 3. mouth defaults ----------------------------------------------------------

def test_mouth_defaults_are_the_backend_export() -> None:
    import db_prompt_studio as d

    assert _vocabulary()["mouthDefaults"] == {
        "persona": d._DEFAULT_PERSONA,
        "voice": d._DEFAULT_VOICE,
        "guardrails": d._DEFAULT_GUARDRAILS,
    }, "regenerate Habibi/src/lib/studio-vocabulary.json from db_prompt_studio._DEFAULT_*"
    seed = _src("src", "lib", "prompt-studio.ts")
    for name in ("DEFAULT_GUARDRAILS", "DEFAULT_VOICE", "DEFAULT_PERSONA"):
        assert re.search(rf"export const {name}: \w+ = STUDIO_VOCABULARY\.mouthDefaults\.\w+;", seed), name


def test_the_seed_migration_guardrails_are_the_code_default() -> None:
    """0018 seeded rows with a literal copy. Drift here means the seeded fleet
    and a fresh card disagree about what "default" means — decide, do not edit
    the migration."""
    import db_prompt_studio as d

    tree = ast.parse(
        (BACKEND / "alembic" / "versions" / "20260722_0018_prompt_studio_schema_seed.py").read_text(encoding="utf-8")
    )
    seeded = next(
        ast.literal_eval(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", None) == "DEFAULT_GUARDRAILS"
    )
    assert seeded == d._DEFAULT_GUARDRAILS


# 4. tuning presets ----------------------------------------------------------

def test_the_browser_holds_no_tuning_presets() -> None:
    """`GET /sandbox/tuning/presets` is the owner. The browser's four had drifted
    (idle_timeout_secs 5 vs 10, style empathetic vs serious)."""
    assert "AGENT_TUNING_PRESETS" not in _src("src", "data", "agent-tuning.ts")
    assert "AGENT_TUNING_PRESETS" not in _src("src", "components", "sandbox", "TuningStudio.tsx")
    assert '"/sandbox/tuning/presets"' in _src("src", "api", "voice-sandbox.ts")


# 5. objectives --------------------------------------------------------------

def test_objectives_match_the_graph() -> None:
    import flow_graph

    card = _src("src", "api", "agent-card.ts")
    assert _ts_const_list(card, "OBJECTIVES") == set(flow_graph.OBJECTIVES)
    assert "export type Objective = (typeof OBJECTIVES)[number];" in card


# 6. eval requirements -------------------------------------------------------

def test_eval_requires_match() -> None:
    from agent_core.cards.schema import EvalRequire

    card = _src("src", "api", "agent-card.ts")
    py = set(get_args(EvalRequire))
    assert _ts_const_list(card, "EVAL_REQUIRES") == py
    tab = _src("src", "components", "prompt-studio", "panels", "EvalsTab.tsx")
    match = re.search(r"const EVAL_REQUIRE:.*?= \[(.*?)\n\];", tab, re.S)
    assert match, "EVAL_REQUIRE not found in EvalsTab.tsx"
    assert set(re.findall(r'key: "([^"]+)"', match.group(1))) == py


# 7. locked engines ----------------------------------------------------------

def test_locked_policy_engines_match() -> None:
    from agent_core.cards.schema import LOCKED_POLICY_ENGINES

    card = _src("src", "api", "agent-card.ts")
    assert _ts_const_list(card, "LOCKED_POLICY_ENGINES") == set(LOCKED_POLICY_ENGINES)


# stripped globals (G16) -----------------------------------------------------

def test_the_inspector_names_the_globals_the_runtime_strips() -> None:
    import flow_graph

    assert set(_vocabulary()["globalToolsStrippedAtRuntime"]) == set(flow_graph.GLOBAL_TOOLS_STRIPPED_AT_RUNTIME)
    inspector = _src("src", "components", "flow", "inspector", "GraphInspector.tsx")
    assert "STUDIO_VOCABULARY.globalToolsStrippedAtRuntime" in inspector


def test_connector_data_classes_are_the_backend_vocabulary() -> None:
    """The register-connector dialog offers these; a hardcoded ["pii"] stamped
    every connector as personal data whatever it served."""
    from agent_core.connectors.persist import DATA_CLASSES

    assert _vocabulary()["connectorDataClasses"] == list(DATA_CLASSES)
    panel = _src("src", "components", "integrations", "ConnectorsPanel.tsx")
    assert "STUDIO_VOCABULARY.connectorDataClasses" in panel


def test_the_whatsapp_history_check_is_the_same_detector() -> None:
    """bot_runtime kept a fourth copy -- four substrings -- that accepted
    "recorded for quality" and rejected the wording the pattern accepts.
    One detector: whatever mentions_recording_disclosure says, the history
    check says."""
    import bot_runtime
    from agent_core.guardrails import mentions_recording_disclosure

    said = "This conversation may be recorded for training and quality purposes."
    assert mentions_recording_disclosure(said)
    assert bot_runtime._history_already_disclosed_recording(
        [{"role": "assistant", "content": said}]
    )
    assert not bot_runtime._history_already_disclosed_recording(
        [{"role": "user", "content": said}, {"role": "assistant", "content": "I'll record that in the CRM."}]
    )
