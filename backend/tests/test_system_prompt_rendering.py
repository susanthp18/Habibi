"""One authored prompt, one rendering rule, across every runtime.

The Studio's System Prompt tab writes a single string. Three runtimes read it —
live voice, live WhatsApp text, and the sandbox — and they used to disagree
about what it means. Rehearsing a prompt therefore told you nothing about what
would ship.
"""

from __future__ import annotations

import pytest

from agent_core.prompt import default_context
from prompt_render import (
    KNOWN_VARIABLES,
    SYSTEM_SAFE_VARIABLES,
    format_untrusted_crm_card,
    render_system_prompt,
    strip_unrendered_crm_tokens,
)

AUTHORED = (
    "You are {agent_name}, an inbound collections voice agent for {bank_name}.\n"
    "Greet {customer_name} warmly and acknowledge their situation.\n"
    "Reference their account {account_no} and the overdue amount of "
    "{overdue_amount} due on {due_date}.\n"
    "Speak in {language}. Be patient and non-judgemental."
)

# What bot_runtime builds before a WhatsApp caller has been identified.
UNIDENTIFIED = default_context(
    {
        "customer_name": "Customer",
        "account_no": "XXXX",
        "overdue_amount": "0",
        "due_date": "",
        "language": "English",
    }
)


def _render_like_a_runtime(template: str, ctx: dict) -> str:
    """The one rule all three paths now share."""
    return strip_unrendered_crm_tokens(render_system_prompt(template, ctx))


def test_operator_tokens_resolve_and_crm_tokens_never_reach_the_model() -> None:
    rendered = _render_like_a_runtime(AUTHORED, UNIDENTIFIED)

    assert "Priya" in rendered and "HDFC Bank" in rendered and "English" in rendered
    for crm in KNOWN_VARIABLES - SYSTEM_SAFE_VARIABLES:
        assert "{" + crm + "}" not in rendered


def test_call_start_defaults_never_become_policy() -> None:
    """render_prompt substituted the placeholders, so the live system prompt read
    "Reference their account XXXX and the overdue amount of 0 due on ." — a
    policy string asserting the account number is XXXX and nothing is owed."""
    rendered = _render_like_a_runtime(AUTHORED, UNIDENTIFIED)

    assert "XXXX" not in rendered
    assert "overdue amount of 0" not in rendered
    assert "due on ." not in rendered


def test_a_real_customer_name_is_not_spliced_into_the_system_prompt() -> None:
    """The values are known here, and they still do not belong in the policy —
    that is the whole point of the untrusted card."""
    identified = default_context(
        {"customer_name": "Susanth", "account_no": "AC-1029", "overdue_amount": "18450"}
    )

    rendered = _render_like_a_runtime(AUTHORED, identified)

    assert "Susanth" not in rendered
    assert "AC-1029" not in rendered
    assert "18450" not in rendered
    # ...and they are present on the card the model also receives.
    card = format_untrusted_crm_card(identified)
    assert "Susanth" in card and "AC-1029" in card and "18450" in card


def test_a_prompt_without_crm_tokens_survives_intact() -> None:
    """Stripping is line-scoped, so an author who follows the lint keeps every
    line they wrote."""
    clean = (
        "You are {agent_name} for {bank_name}.\n"
        "Speak in {language}.\n"
        "Never threaten legal action."
    )

    rendered = _render_like_a_runtime(clean, UNIDENTIFIED)

    assert rendered.splitlines() == [
        "You are Priya for HDFC Bank.",
        "Speak in English.",
        "Never threaten legal action.",
    ]


@pytest.mark.parametrize(
    "module_path, attr",
    [
        ("voice.bot", "_system_instruction_from_bundle"),
        ("bot_runtime", "_build_messages"),
    ],
)
def test_no_runtime_still_reaches_for_render_prompt(module_path: str, attr: str) -> None:
    """render_prompt substitutes CRM fields and belongs to developer/user cards.
    A system-prompt builder importing it is the bug this file exists for."""
    import importlib
    import inspect

    module = importlib.import_module(module_path)
    assert hasattr(module, attr), f"{module_path}.{attr} moved — update this test"
    source = inspect.getsource(module)
    assert "render_prompt(" not in source.replace("render_system_prompt(", "")


def test_the_seeded_presets_do_not_teach_unrenderable_tokens() -> None:
    """Every preset template wrote {customer_name} / {account_no} into a system
    prompt. With unresolved lines now dropped, applying one would have deleted
    half its own instructions."""
    import importlib.util
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "20260819_0084_persona_presets_crm_free.py"
    )
    spec = importlib.util.spec_from_file_location("_preset_templates", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    for preset_id, template in module.TEMPLATES.items():
        rendered = _render_like_a_runtime(template, UNIDENTIFIED)
        dropped = len(template.splitlines()) - len(rendered.splitlines())
        assert dropped == 0, f"{preset_id} loses {dropped} line(s) to CRM tokens"


def test_the_editor_variable_palette_matches_the_renderer() -> None:
    """The System Prompt tab splits its palette into "safe here" and "CRM
    fields", and the split has to be the renderer's, not a second opinion.

    Read out of the TypeScript source rather than duplicated as a literal: a
    hand-copied list is exactly what let the editor offer {account_no} as an
    ordinary variable while the runtime deleted every line it appeared on.
    """
    import re
    from pathlib import Path

    from prompt_render import KNOWN_VARIABLES, SYSTEM_SAFE_VARIABLES

    seed = (
        Path(__file__).resolve().parents[2]
        / "Habibi"
        / "src"
        / "data"
        / "prompt-studio-seed.ts"
    ).read_text(encoding="utf-8")

    def names(const: str) -> set[str]:
        block = re.search(rf"export const {const} = \[(.*?)\]", seed, re.S)
        assert block, f"{const} not found in prompt-studio-seed.ts"
        return set(re.findall(r'"([a-z_]+)"', block.group(1)))

    assert names("SYSTEM_SAFE_VARIABLES") == set(SYSTEM_SAFE_VARIABLES)
    assert names("CRM_VARIABLES") == set(KNOWN_VARIABLES - SYSTEM_SAFE_VARIABLES)
