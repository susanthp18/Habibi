"""The /ws/asterisk route: reachable, and only with the media credentials."""

from __future__ import annotations

import base64

import pytest

pytest.importorskip("pipecat")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from starlette.websockets import WebSocketDisconnect  # noqa: E402

from voice import asterisk_ws  # noqa: E402


def _basic(user: str, password: str) -> dict[str, str]:
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()}


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("ASTERISK_WS_USER", "media")
    monkeypatch.setenv("ASTERISK_WS_PASSWORD", "s3cret")
    served: list[bool] = []

    async def fake_session(websocket) -> None:
        served.append(True)
        await websocket.accept()
        await websocket.close()

    monkeypatch.setattr(asterisk_ws, "run_asterisk_websocket_session", fake_session)
    app = FastAPI()
    asterisk_ws.register_asterisk_runner_routes(app)
    c = TestClient(app)
    c.served = served  # type: ignore[attr-defined]
    return c


def test_the_route_accepts_the_media_credentials(client: TestClient) -> None:
    """Before the fix FastAPI read `websocket` as a required query field and every
    Asterisk connection, right secret or not, got 403."""
    with client.websocket_connect("/ws/asterisk", headers=_basic("media", "s3cret")):
        pass
    assert client.served == [True]  # type: ignore[attr-defined]


@pytest.mark.parametrize("headers", [{}, _basic("media", "wrong"), {"Authorization": "Bearer s3cret"}])
def test_the_route_refuses_anything_else(client: TestClient, headers: dict[str, str]) -> None:
    with pytest.raises(WebSocketDisconnect) as closed:
        with client.websocket_connect("/ws/asterisk", headers=headers):
            pass
    assert closed.value.code == 1008
    assert client.served == []  # type: ignore[attr-defined]


def test_the_secret_is_not_a_path_segment(client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/asterisk/s3cret"):
            pass
