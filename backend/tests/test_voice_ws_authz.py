"""The Media Stream WebSocket must survive the global authz dependency.

The symptom was a call that connected and then sat in silence. Twilio dialled,
the customer answered, `/twilio/voice/call-status` reported progress happily —
and the audio socket never opened:

    GET /ws/<secret>  500 Internal Server Error
    TypeError: _authz_guard() missing 1 required positional argument: 'request'
    Twilio Stream status event=stream-error

`_authz_guard` is a *global* dependency, so it runs for websocket routes too.
It asked FastAPI for a ``Request``, and a websocket scope has no ``Request`` to
give — so the dependency solver could not build its arguments and raised before
a single line of the guard ran. Being in ``_AUTH_EXEMPT_PREFIXES`` did not help:
that list is read inside the middleware, which is not where this failed.

The failure is worth naming precisely because of where it lands. Everything
that reports on a call — the status callbacks, the attempt state machine, the
inbox — said the call was fine. The only thing that knew otherwise was the
person holding the phone.
"""

from __future__ import annotations

import pytest


def _websocket_routes() -> list[str]:
    from starlette.routing import WebSocketRoute

    import main as app_main

    return [r.path for r in app_main.app.routes if isinstance(r, WebSocketRoute)]


def test_the_guard_accepts_a_websocket_scope() -> None:
    """It must be *callable* for a socket, not merely tolerant of one.

    The bug was never in the guard's logic — it was that FastAPI could not
    construct the argument the signature demanded. So this asserts on the
    annotation: it has to be a type that exists in both scopes.
    """
    import typing

    from starlette.requests import HTTPConnection

    import main as app_main

    # `main` uses `from __future__ import annotations`, so the raw annotation is
    # a string. Resolve it — FastAPI resolves it the same way, and the resolved
    # type is what decides whether a websocket scope can be served.
    hints = typing.get_type_hints(app_main._authz_guard)
    hints.pop("return", None)
    assert list(hints.values()) == [HTTPConnection], (
        "a websocket scope cannot supply a Request; the shared base class can"
    )


def test_a_websocket_connection_passes_the_guard() -> None:
    """A socket carries no method, so there is nothing for the registry to key on."""
    import asyncio

    from starlette.requests import HTTPConnection

    import main as app_main

    conn = HTTPConnection(
        {
            "type": "websocket",
            "path": "/ws/whatever",
            "headers": [],
            "query_string": b"",
        }
    )
    # Must simply return. Raising here is a 500 on the upgrade, which is the bug.
    assert asyncio.run(app_main._authz_guard(conn)) is None


def test_only_the_voice_media_stream_routes_are_websockets() -> None:
    """The exemption above is safe only while these two are the only sockets.

    They authenticate themselves with ``VOICE_WS_PROXY_SECRET``
    (``_voice_ws_upgrade_authorized``, fail-closed in production). A websocket
    route added later would inherit the exemption silently and be gated by
    nothing at all, so it has to fail here first and be given its own check.
    """
    assert sorted(_websocket_routes()) == ["/ws", "/ws/{proxy_secret}"]


def test_http_routes_are_still_checked(monkeypatch: pytest.MonkeyPatch) -> None:
    """The whole point of the guard survives the websocket carve-out."""
    import asyncio

    from starlette.requests import HTTPConnection

    import authz
    import main as app_main

    called: list[tuple[str, str]] = []

    def _fake_check(method: str, path: str, actor: object) -> None:
        called.append((method, path))

    monkeypatch.setattr(authz, "check", _fake_check)
    conn = HTTPConnection(
        {
            "type": "http",
            "method": "GET",
            "path": "/customers",
            "headers": [],
            "query_string": b"",
        }
    )
    asyncio.run(app_main._authz_guard(conn))
    assert called == [("GET", "/customers")]
