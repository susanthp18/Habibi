"""A connector-registry outage must not take down every publish.

Cycle 14 wrapped the ``bound_tool_names`` read that binds ``ext.*`` tool names
(see ``test_connector_bind_degrades_loudly``) but left G10's own read — the one
that checks each connector is approved, https, classified and healthy — outside
any ``try``. So a DB error in ``get_connector`` propagated straight out of
``compile_card``: the studio got a 500, and every dry-run compile and every
publish of a card that merely *mentions* a connector failed until the registry
came back. The card itself was fine.

Now the lookup degrades the same way the binding does: an error in the log, a
non-blocking G10 ``warn`` naming the connectors, and a finished compile that
says the ext.* checks did not run rather than implying they passed. The
distinction that matters is ``warn`` vs ``fail`` — a registry outage is not an
authoring error, and reporting it as one ("this connector does not exist") sends
the author looking for a mistake they did not make.
"""

from __future__ import annotations

import logging

import pytest

from agent_core.cards.compile import CONNECTOR_LOOKUP_UNAVAILABLE, compile_card
from agent_core.cards.defaults import COLLECTIONS_BOT_ID, card_dump
from voice.flow_export import built_in_collections_graph
from agent_core.skills.intersect import CONNECTOR_BIND_FAILED
from agent_core.tools.catalog import CATALOG

CATALOG_NAMES = set(CATALOG.specs)


def _card_with_connector(connector_id: str = "paylink", prefix: str = "ext.paylink.") -> dict:
    dumped = card_dump(COLLECTIONS_BOT_ID)
    dumped["connectors"] = [{"connector_id": connector_id, "allow_prefixes": [prefix]}]
    return dumped


def _compile(card_raw: dict):
    return compile_card(
        bot_id=COLLECTIONS_BOT_ID,
        card_raw=card_raw,
        flow=built_in_collections_graph(),
        catalog_names=CATALOG_NAMES,
        known_bot_ids={COLLECTIONS_BOT_ID, "intake-v1", "insurance-v1", "supervisor-brief"},
    )


def _g10(report):
    return next(g for g in report.gates if g.gate == "G10")


def _explode(*_args, **_kwargs):
    raise RuntimeError("connection to server at 127.0.0.1 failed")


@pytest.fixture()
def _client_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_CLIENT_ENABLED", "true")


@pytest.fixture()
def _binding_works(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate G10's own lookup from the cycle-14 binding failure."""
    monkeypatch.setattr(
        "agent_core.connectors.persist.bound_tool_names",
        lambda _refs: ["ext.paylink.get_status"],
    )


@pytest.fixture()
def _lookup_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("agent_core.connectors.persist.get_connector", _explode)


# --- the crash this closes --------------------------------------------------


def test_the_compile_finishes_instead_of_raising(
    _client_on, _binding_works, _lookup_fails
) -> None:
    """The whole bug: this used to propagate out of ``compile_card``."""
    report = _compile(_card_with_connector())
    assert {g.gate for g in report.gates} >= {"G0", "G4", "G9", "G10", "G12"}


def test_every_other_gate_still_reaches_a_verdict(
    _client_on, _binding_works, _lookup_fails
) -> None:
    report = _compile(_card_with_connector())
    assert _g10(report).status == "warn"
    assert next(g for g in report.gates if g.gate == "G0").status == "pass"


def test_the_compiled_tool_set_survives(_client_on, _binding_works, _lookup_fails) -> None:
    """G10's lookup is a *check*. It failing must not strip the tools."""
    report = _compile(_card_with_connector())
    assert report.effective_tools
    assert "ext.paylink.get_status" in report.effective_tools


# --- what the author is told ------------------------------------------------


def test_g10_warns_and_says_the_gates_were_skipped(
    _client_on, _binding_works, _lookup_fails
) -> None:
    g10 = _g10(_compile(_card_with_connector()))
    assert g10.status == "warn"
    assert "connector lookup unavailable" in g10.detail
    assert "ext.* gates skipped" in g10.detail


def test_the_issue_names_the_connector_and_the_cause(
    _client_on, _binding_works, _lookup_fails
) -> None:
    g10 = _g10(_compile(_card_with_connector()))
    issue = next(i for i in g10.issues if i.get("problem") == CONNECTOR_LOOKUP_UNAVAILABLE)
    assert issue["connectors"] == ["paylink"]
    assert "connection to server" in issue["detail"]


def test_it_is_not_reported_as_an_unresolved_connector(
    _client_on, _binding_works, _lookup_fails
) -> None:
    """An "unresolved" issue means the author named a connector that does not exist."""
    g10 = _g10(_compile(_card_with_connector()))
    assert not any("unresolved" in str(issue) for issue in g10.issues)


def test_the_warning_does_not_block_a_publish(
    _client_on, _binding_works, _lookup_fails
) -> None:
    report = _compile(_card_with_connector())
    assert "G10" not in {g.gate for g in report.blocking}


def test_the_failure_is_logged_with_the_card_and_connector(
    _client_on, _binding_works, _lookup_fails, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR, logger="agent_core.cards.compile"):
        _compile(_card_with_connector())

    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors, "a swallowed registry failure is the bug this closes"
    message = errors[0].getMessage()
    assert COLLECTIONS_BOT_ID in message
    assert "paylink" in message
    assert "connection to server" in message


# --- what must still fail ---------------------------------------------------


def test_a_bad_prefix_still_fails_without_the_registry(
    _client_on, _binding_works, _lookup_fails
) -> None:
    """Pure card validation needs no registry, so an outage cannot excuse it."""
    report = _compile(_card_with_connector(prefix="crm.paylink."))
    g10 = _g10(report)
    assert g10.status == "fail"
    assert any("bad_prefix" in str(issue) for issue in g10.issues)
    # ...and the outage still rides along rather than being dropped.
    assert any(i.get("problem") == CONNECTOR_LOOKUP_UNAVAILABLE for i in g10.issues)


def test_a_genuinely_missing_connector_still_fails(
    _client_on, _binding_works, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``None`` from a working registry is an authoring error, and still blocks."""
    monkeypatch.setattr("agent_core.connectors.persist.get_connector", lambda _cid: None)
    g10 = _g10(_compile(_card_with_connector()))
    assert g10.status == "fail"
    assert any("unresolved" in str(issue) for issue in g10.issues)


def test_nothing_is_warned_about_when_the_registry_is_healthy(
    _client_on, _binding_works, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "agent_core.connectors.persist.get_connector",
        lambda _cid: {
            "status": "approved",
            "kind": "remote_mcp",
            "url": "https://paylink.example/mcp",
            "dataClass": ["money"],
            "health": "healthy",
        },
    )
    g10 = _g10(_compile(_card_with_connector()))
    assert g10.status == "pass"
    assert g10.issues == []


# --- both registry reads failing at once ------------------------------------


def test_a_bind_failure_and_a_lookup_failure_are_both_reported(
    _client_on, _lookup_fails, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One DB outage takes out both reads. Neither report may hide the other."""
    monkeypatch.setattr("agent_core.connectors.persist.bound_tool_names", _explode)
    g10 = _g10(_compile(_card_with_connector()))

    assert g10.status == "warn"
    assert "connector tools unavailable" in g10.detail
    assert "connector lookup unavailable" in g10.detail
    problems = {i.get("problem") for i in g10.issues}
    assert problems == {CONNECTOR_BIND_FAILED, CONNECTOR_LOOKUP_UNAVAILABLE}
