"""The persona-preset templates, held together across the three copies of them.

A preset is the one button in Prompt Studio that writes the whole system prompt
for you, so a preset carrying a token the renderer cannot substitute is worse
than a bad prompt: ``render_system_prompt`` only fills SYSTEM_SAFE_VARIABLES and
``strip_unrendered_crm_tokens`` then deletes the entire LINE any other token sits
on. "Greet {customer_name} warmly and acknowledge their situation" does not greet
anyone — it removes itself, silently, after the author has clicked the button and
moved on.

There are three copies of these strings and they had already drifted:

* ``sql/09_bot_config.sql``  — seeds a fresh install.
* ``alembic/versions/20260819_0084_persona_presets_crm_free.py`` — repairs a
  database that already holds the old rows.
* ``seed_postgres.py``      — upserts on every seed run.

The first two were rewritten to be CRM-free; the third was not, and the third is
the one that decides what is actually in the table. A migration only performs its
UPDATE when it is replayed, and this project stamps rather than replays, so a
database can sit at head and still serve the pre-repair text forever. That is not
a hypothetical either: the live database was at 20260823_0100 and still returned
"Reference their account {account_no}" to the studio.

These tests do not care what the wording is. They care that the three agree and
that none of them can substitute a token the runtime will delete.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from prompt_render import KNOWN_VARIABLES, SYSTEM_SAFE_VARIABLES, TOKEN_RE

BACKEND = Path(__file__).resolve().parents[1]

#: sql/ keys presets by their id; the seeder names them by local variable.
SEED_VARIABLES = {
    "empathetic": "_emp_prompt",
    "firm": "_firm_prompt",
    "compliance": "_comp_prompt",
    "upsell": "_upsell_prompt",
}

CRM_ONLY = KNOWN_VARIABLES - SYSTEM_SAFE_VARIABLES


def _sql_templates() -> dict[str, str]:
    """promptTemplate per preset id, as sql/09_bot_config.sql seeds them."""
    text = (BACKEND / "sql" / "09_bot_config.sql").read_text(encoding="utf-8")
    found: dict[str, str] = {}
    pattern = re.compile(
        r"INSERT INTO persona_presets .*?VALUES\s*\n\s*"
        r"\('([a-z]+)', '[^']*', '[^']*', '(.*?)'::jsonb\)",
        re.S,
    )
    for match in pattern.finditer(text):
        # SQL doubles a quote to escape it; JSON does not.
        blob = match.group(2).replace("''", "'")
        found[match.group(1)] = json.loads(blob)["promptTemplate"]
    return found


def _seed_templates() -> dict[str, str]:
    """The same four strings as ``seed_postgres`` upserts them.

    Parsed rather than imported: importing the seeder runs module-level work and
    wants a database, and the only thing under test here is four string literals.
    """
    tree = ast.parse((BACKEND / "seed_postgres.py").read_text(encoding="utf-8"))
    by_variable: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or target.id not in SEED_VARIABLES.values():
            continue
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            by_variable[target.id] = node.value.value
    return {pid: by_variable[var] for pid, var in SEED_VARIABLES.items() if var in by_variable}


def _migrated_templates() -> dict[str, str]:
    """sql/'s templates put through the latest repair migration's transform.

    Not a third literal copy any more. 20260819_0084 holds the templates as they
    were *then*; 20260825_0101 removes the redundant disclosure line from
    whatever it finds. Asserting sql/ still equalled 0084 would pin sql/ to a
    superseded revision — the useful invariant is that a database which has run
    every migration ends up where a fresh install starts, so this applies the
    newest migration's own transform and checks it is a no-op against sql/.
    """
    import importlib.util

    path = (
        BACKEND
        / "alembic"
        / "versions"
        / "20260825_0101_persona_presets_drop_redundant_disclosure.py"
    )
    spec = importlib.util.spec_from_file_location("_preset_migration_0101", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return {pid: module._strip(t) for pid, t in _sql_templates().items()}


ALL_SOURCES = {
    "sql/09_bot_config.sql": _sql_templates,
    "seed_postgres.py": _seed_templates,
    "migrated": _migrated_templates,
}


@pytest.mark.parametrize("source", sorted(ALL_SOURCES))
def test_every_source_defines_all_four_presets(source: str) -> None:
    assert set(ALL_SOURCES[source]()) == set(SEED_VARIABLES)


@pytest.mark.parametrize("source", sorted(ALL_SOURCES))
@pytest.mark.parametrize("preset_id", sorted(SEED_VARIABLES))
def test_no_preset_interpolates_a_token_the_runtime_deletes(source: str, preset_id: str) -> None:
    """The whole point. A CRM token here deletes the line it was written on.

    Checked against ``prompt_render`` itself rather than a copied list, so
    promoting a field into SYSTEM_SAFE_VARIABLES relaxes this automatically and
    adding a new CRM field tightens it.
    """
    template = ALL_SOURCES[source]()[preset_id]
    offenders = sorted({m.group(1) for m in TOKEN_RE.finditer(template)} & CRM_ONLY)
    assert not offenders, (
        f"{source} preset {preset_id!r} interpolates {offenders}, which "
        "render_system_prompt does not substitute — strip_unrendered_crm_tokens "
        "deletes the whole line each one sits on."
    )


@pytest.mark.parametrize("preset_id", sorted(SEED_VARIABLES))
def test_no_preset_invents_a_variable(preset_id: str) -> None:
    """Every token used is one the platform actually knows about."""
    template = _sql_templates()[preset_id]
    unknown = sorted({m.group(1) for m in TOKEN_RE.finditer(template)} - set(KNOWN_VARIABLES))
    assert not unknown, f"preset {preset_id!r} references unknown variable(s) {unknown}"


@pytest.mark.parametrize("preset_id", sorted(SEED_VARIABLES))
def test_the_three_copies_say_exactly_the_same_thing(preset_id: str) -> None:
    """Byte-for-byte, because the difference between them was the bug.

    sql/ and the migration were repaired together and the seeder was left
    behind, so a fresh install and a re-seeded install disagreed about what
    "Empathetic Collector" means — and the re-seeded one won, because it runs
    last and upserts.
    """
    sql = _sql_templates()[preset_id]
    seed = _seed_templates()[preset_id]
    migrated = _migrated_templates()[preset_id]
    assert seed == sql, f"seed_postgres.py has drifted from sql/ for {preset_id!r}"
    # A migrated database and a fresh install must land in the same place. If
    # this fails, sql/ was edited without a migration to carry existing rows
    # there — the exact gap that left the live database serving pre-0084 text
    # while sitting at head.
    assert migrated == sql, (
        f"running the latest preset migration over sql/'s own text changes "
        f"{preset_id!r} — a fresh install and a migrated one would disagree"
    )


@pytest.mark.parametrize("source", sorted(ALL_SOURCES))
@pytest.mark.parametrize("preset_id", sorted(SEED_VARIABLES))
def test_no_preset_restates_a_guardrail_the_platform_injects(
    source: str, preset_id: str
) -> None:
    """The disclosure belongs to the guardrail, not to the preset.

    ``guardrail_rules`` appends "State once, at the very start ... never say it
    again" whenever alwaysDiscloseRecording is on, and every render path calls
    it. A preset that also says "Always disclose that the call is recorded" puts
    "always" and "once, then never again" in one system message, which is what
    made a live call disclose three times over.

    Checked with the runtime's own detector rather than a string match, so a
    preset cannot reintroduce it in different words.
    """
    from agent_core.guardrails import mentions_recording_disclosure

    template = ALL_SOURCES[source]()[preset_id]
    offenders = [ln for ln in template.split("\n") if mentions_recording_disclosure(ln)]
    assert not offenders, (
        f"{source} preset {preset_id!r} states the recording disclosure itself: "
        f"{offenders!r}. The alwaysDiscloseRecording guardrail already supplies "
        "it, worded to be said once."
    )
