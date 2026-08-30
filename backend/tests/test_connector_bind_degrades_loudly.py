"""A registry blip must not silently produce a connector-less card.

``intersect.effective_tools`` binds the card's ``ext.*`` tool names by reading
the connector registry. That read was wrapped in ``except Exception: pass``, so
a transient DB error compiled the card with *every* connector tool missing and
nothing recorded anywhere — no log line, no compile issue. The resulting card is
indistinguishable from one whose author never attached a connector, and it would
have published and answered calls with the connector tools quietly absent.

The compile still succeeds — a connector outage is not an authoring error, and
failing the publish would be a worse outage — but it now says so: an error in
the log, and a G10 ``warn`` carrying the connector ids in the report the studio
renders.
"""

from __future__ import annotations

import logging

import pytest

from agent_core.cards.compile import compile_card
from agent_core.cards.defaults import COLLECTIONS_BOT_ID, card_dump
from voice.flow_export import built_in_collections_graph
from agent_core.cards.schema import AgentCard
from agent_core.skills.intersect import CONNECTOR_BIND_FAILED, effective_tools
from agent_core.tools.catalog import CATALOG

CATALOG_NAMES = set(CATALOG.specs)


def _card_with_connector() -> dict:
    dumped = card_dump(COLLECTIONS_BOT_ID)
    dumped["connectors"] = [{"connector_id": "paylink", "allow_prefixes": ["ext.paylink."]}]
    return dumped


def _healthy_connector(_cid: str) -> dict:
    return {
        "status": "approved",
        "kind": "remote_mcp",
        "url": "https://paylink.example/mcp",
        "dataClass": ["money"],
        "health": "healthy",
    }


def _explode(*_args, **_kwargs):
    raise RuntimeError("connection to server at 127.0.0.1 failed")


@pytest.fixture()
def _client_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_CLIENT_ENABLED", "true")


@pytest.fixture()
def _binding_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("agent_core.connectors.persist.bound_tool_names", _explode)


# --- the tool intersection itself -------------------------------------------


def test_the_compile_still_produces_a_usable_tool_set(_client_on, _binding_fails) -> None:
    """Degrade, do not fail: the non-connector tools are still there."""
    card = AgentCard.model_validate(_card_with_connector())
    issues: list[dict] = []
    names = effective_tools(card, catalog_names=CATALOG_NAMES, issues=issues)

    assert names, "a registry failure must not empty the tool set"
    assert not [n for n in names if n.startswith("ext.")]


def test_the_failure_is_appended_to_the_issue_sink(_client_on, _binding_fails) -> None:
    card = AgentCard.model_validate(_card_with_connector())
    issues: list[dict] = []
    effective_tools(card, catalog_names=CATALOG_NAMES, issues=issues)

    assert len(issues) == 1
    issue = issues[0]
    assert issue["problem"] == CONNECTOR_BIND_FAILED
    assert issue["connectors"] == ["paylink"]
    assert "connection to server" in issue["detail"]


def test_the_failure_is_logged_with_the_card_and_connector(
    _client_on, _binding_fails, caplog: pytest.LogCaptureFixture
) -> None:
    card = AgentCard.model_validate(_card_with_connector())
    with caplog.at_level(logging.ERROR, logger="agent_core.skills.intersect"):
        effective_tools(card, catalog_names=CATALOG_NAMES)

    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors, "a swallowed connector failure is the bug this closes"
    message = errors[0].getMessage()
    assert COLLECTIONS_BOT_ID in message
    assert "paylink" in message


def test_a_caller_without_a_sink_still_does_not_raise(_client_on, _binding_fails) -> None:
    """``runtime``/``bot_runtime`` pass no sink — they must keep working."""
    card = AgentCard.model_validate(_card_with_connector())
    assert effective_tools(card, catalog_names=CATALOG_NAMES)


def test_nothing_is_appended_when_binding_works(
    _client_on, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "agent_core.connectors.persist.bound_tool_names",
        lambda _refs: ["ext.paylink.get_status"],
    )
    card = AgentCard.model_validate(_card_with_connector())
    issues: list[dict] = []
    names = effective_tools(card, catalog_names=CATALOG_NAMES, issues=issues)

    assert issues == []
    assert "ext.paylink.get_status" in names


# --- what the studio renders ------------------------------------------------


def _compile(card_raw: dict):
    return compile_card(
        bot_id=COLLECTIONS_BOT_ID,
        card_raw=card_raw,
        flow=built_in_collections_graph(),
        catalog_names=CATALOG_NAMES,
        known_bot_ids={COLLECTIONS_BOT_ID, "intake-v1", "insurance-v1", "supervisor-brief"},
    )


def test_g10_warns_rather_than_staying_silent(
    _client_on, _binding_fails, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("agent_core.connectors.persist.get_connector", _healthy_connector)
    report = _compile(_card_with_connector())

    g10 = next(g for g in report.gates if g.gate == "G10")
    assert g10.status == "warn"
    assert "connector tools unavailable" in g10.detail
    assert any(issue.get("problem") == CONNECTOR_BIND_FAILED for issue in g10.issues)


def test_the_warning_does_not_block_a_publish(
    _client_on, _binding_fails, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("agent_core.connectors.persist.get_connector", _healthy_connector)
    report = _compile(_card_with_connector())

    assert "G10" not in {g.gate for g in report.blocking}


def test_a_real_bind_failure_rides_along_with_a_genuine_g10_failure(
    _client_on, _binding_fails, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unapproved connector still fails; the bind failure is not lost."""
    monkeypatch.setattr(
        "agent_core.connectors.persist.get_connector",
        lambda _cid: {**_healthy_connector(_cid), "status": "draft"},
    )
    report = _compile(_card_with_connector())

    g10 = next(g for g in report.gates if g.gate == "G10")
    assert g10.status == "fail"
    assert any("not_approved" in str(issue) for issue in g10.issues)
    assert any(issue.get("problem") == CONNECTOR_BIND_FAILED for issue in g10.issues)


def test_g10_passes_when_the_registry_is_healthy(
    _client_on, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("agent_core.connectors.persist.get_connector", _healthy_connector)
    monkeypatch.setattr(
        "agent_core.connectors.persist.bound_tool_names",
        lambda _refs: ["ext.paylink.get_status"],
    )
    report = _compile(_card_with_connector())

    g10 = next(g for g in report.gates if g.gate == "G10")
    assert g10.status == "pass"
    assert g10.issues == []
