"""One authored prompt, one rendering rule, across every runtime.

The Studio's System Prompt tab writes a single string. Three runtimes read it —
live voice, live WhatsApp text, and the sandbox — and they used to disagree
about what it means. Rehearsing a prompt therefore told you nothing about what
would ship.
"""

from __future__ import annotations

import pytest

from agent_core.prompt import default_context

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


@pytest.mark.parametrize(
    "module_path, attr",
    [
        ("voice.bot_flow", "_system_instruction_from_bundle"),
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


