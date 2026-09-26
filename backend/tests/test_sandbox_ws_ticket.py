"""The browser's Sandbox Live socket opens once, for one session, briefly.

The ticket in ``/ws-sandbox/{session}/{ticket}`` is the only credential a
browser WebSocket can carry. It is redeemed inside the session store's
exclusive section; this pins the rules, not the store.
"""

from __future__ import annotations

import time

import pytest

import voice_session_store
from voice import sandbox_ws


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> dict:
    sessions: dict[str, dict] = {}

    def mutate(session_id, fn):
        if session_id not in sessions:
            return None
        sessions[session_id] = fn(dict(sessions[session_id]))
        return sessions[session_id]

    monkeypatch.setattr(voice_session_store, "mutate", mutate)
    return sessions


def test_a_ticket_opens_its_session_once(store) -> None:
    ticket, fields = sandbox_ws.mint_ticket()
    store["VS-ABCDEF1234"] = {"status": "starting", **fields}
    assert sandbox_ws.consume_ticket("VS-ABCDEF1234", ticket) is None
    assert sandbox_ws.consume_ticket("VS-ABCDEF1234", ticket) == "ticket_invalid_or_used"


def test_a_ticket_does_not_open_another_session(store) -> None:
    ticket, fields = sandbox_ws.mint_ticket()
    store["VS-ABCDEF1234"] = {"status": "starting", **fields}
    store["VS-0000000000"] = {"status": "starting", **sandbox_ws.mint_ticket()[1]}
    assert sandbox_ws.consume_ticket("VS-0000000000", ticket) == "ticket_invalid_or_used"
    assert sandbox_ws.consume_ticket("VS-NOSUCH0000", ticket) == "session_not_found"


def test_an_expired_or_stopped_session_refuses_and_burns_the_ticket(store) -> None:
    ticket, fields = sandbox_ws.mint_ticket()
    store["VS-ABCDEF1234"] = {"status": "starting", **fields, "wsTicketExpiresAt": time.time() - 1}
    assert sandbox_ws.consume_ticket("VS-ABCDEF1234", ticket) == "ticket_expired"
    assert store["VS-ABCDEF1234"]["wsTicketHash"] is None

    ticket, fields = sandbox_ws.mint_ticket()
    store["VS-ABCDEF1234"] = {"status": "stopped", **fields}
    assert sandbox_ws.consume_ticket("VS-ABCDEF1234", ticket) == "session_stopped"


def test_the_raw_ticket_is_never_stored(store) -> None:
    ticket, fields = sandbox_ws.mint_ticket()
    assert ticket not in str(fields)


def test_the_route_reaches_the_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    """The first deploy refused every handshake 403 before the handler ran:
    the ``WebSocket`` annotation did not resolve, so FastAPI treated the
    socket as a missing query parameter."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    seen: list[tuple[str, str]] = []

    async def fake_run(websocket, session_id, ticket):
        seen.append((session_id, ticket))
        await websocket.accept()
        await websocket.close()

    monkeypatch.setattr(sandbox_ws, "run_sandbox_ws_session", fake_run)
    app = FastAPI()
    sandbox_ws.register_sandbox_ws_route(app)
    with TestClient(app).websocket_connect("/ws-sandbox/VS-ABCDEF1234/tkt"):
        pass
    assert seen == [("VS-ABCDEF1234", "tkt")]
