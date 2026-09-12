"""Two answers with one owner each: where the customer is, and whether we are live.

`"Asia/Kolkata"` was written in thirteen production modules -- four of them as
their own `DEFAULT_TZ`, four inside SQL -- so `APP_TIMEZONE` moved some clocks
and not others. `"production"` was the default in five places while the text
mouth read `BOT_ENVIRONMENT`, so one process could serve production text and
sandbox voice. `agent_core.clock` owns the first; `agent_core.deployment.
active_environment` owns the second.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]

#: Modules allowed to spell the zone: the owner, and seed data that describes
#: customers rather than deciding for them.
_TZ_OWNERS = {"agent_core/clock.py", "seed_postgres.py", "seed_susanth.py"}
_SKIP_DIRS = {"tests", "scripts", "alembic", ".venv", "__pycache__", "node_modules"}


def _production_modules() -> list[Path]:
    out = []
    for path in BACKEND.rglob("*.py"):
        rel = path.relative_to(BACKEND)
        if rel.parts[0] in _SKIP_DIRS:
            continue
        out.append(path)
    return out


def test_the_tenant_zone_is_spelled_once() -> None:
    offenders = []
    for path in _production_modules():
        rel = str(path.relative_to(BACKEND)).replace("\\", "/")
        if rel in _TZ_OWNERS:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                # SQL strings included: `AT TIME ZONE 'Asia/Kolkata'` is a
                # literal too, and the one `APP_TIMEZONE` could not reach.
                if "Asia/Kolkata" in node.value and "(IST)" not in node.value:
                    offenders.append(f"{rel}:{node.lineno}")
    assert not offenders, offenders


def test_the_zone_follows_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    from agent_core import clock
    import contact_policy
    import payment_events

    assert contact_policy.DEFAULT_TZ == clock.DEFAULT_TIMEZONE == payment_events.DEFAULT_TZ
    monkeypatch.setenv("APP_TIMEZONE", "Asia/Dubai")
    assert clock.timezone_name() == "Asia/Dubai"
    assert str(clock.tenant_tz()) == "Asia/Dubai"


def test_the_environment_has_one_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    import bot_jobs
    from agent_core import deployment

    monkeypatch.delenv("BOT_ENVIRONMENT", raising=False)
    assert deployment.active_environment() == "production"
    monkeypatch.setenv("BOT_ENVIRONMENT", "sandbox")
    assert deployment.active_environment() == "sandbox"
    assert bot_jobs.bot_environment() == "sandbox"

    # The voice mouth no longer writes "production" into its bundle load.
    import inspect

    from voice import bot_flow

    src = inspect.getsource(bot_flow.resolve_call)
    assert 'load_active_bundle(\n                "production"' not in src


# --- a third answer with one owner: where the audio goes -----------------------

#: Modules allowed to spell an Azure region: the owner (azure_speech reads the
#: variable), and seed data that describes a provider rather than choosing one.
_REGION_OWNERS = {"azure_speech.py"}
_REGION_LITERALS = {"eastus", "eastus2", "centralindia", "westeurope", "southeastasia"}


def test_the_azure_region_is_spelled_nowhere() -> None:
    """Three modules used to answer "which region": the provider factory fell
    back to ``eastus2`` (a borrower's audio leaving the country the moment the
    variable was unset), the ops screen displayed ``centralindia`` (a residency
    claim the runtime did not honour), and ``voice/config.py`` required the
    variable. One owner now, and no default anywhere."""
    offenders = []
    for path in _production_modules():
        rel = str(path.relative_to(BACKEND)).replace("\\", "/")
        if rel in _REGION_OWNERS:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and node.value in _REGION_LITERALS:
                offenders.append(f"{rel}:{node.lineno}")
    assert not offenders, offenders


def test_a_missing_region_is_an_error_where_the_provider_is_built(monkeypatch) -> None:
    from agent_core.providers import factory, pool
    from azure_speech import AzureSpeechConfigError

    monkeypatch.delenv("AZURE_SPEECH_REGION", raising=False)
    monkeypatch.setenv("AZURE_SPEECH_KEY", "k")

    class _Pool:
        def acquire(self, session_id, *, tenant_id=None):
            return "k"

    monkeypatch.setattr(pool, "get_pool", lambda provider_id: _Pool())
    with pytest.raises(AzureSpeechConfigError):
        factory._credentials("azure", None, None)
