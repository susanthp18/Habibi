"""Real SIP calls through the Asterisk stack, driven by scripted test phones.

Needs the stack up with the telephony and e2e overlays (see
docker-compose.telephony-e2e.yml) and runs in a container on its network:

    docker run --rm --network backend_default -v <backend>:/app -w /app \\
      --env-file <voice env> -e TELEPHONY_E2E=1 -e ASTERISK_RING_TIMEOUT=12 \\
      collections-voice:local python -m pytest -q tests/e2e_telephony

Every attempt it places is tagged ``context.source = "telephony_e2e"``. The calls
reach the real bot, models and database -- this is the point, and why it is off
by default.
"""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable
from typing import Any

import pytest

if os.getenv("TELEPHONY_E2E") != "1":
    collect_ignore_glob = ["test_*.py"]

PHONES_ARI = os.getenv("PHONES_ARI_URL", "http://sip_test_phones:8088/ari")
BORROWER, AGENT, BOT = "1001", "1002", os.getenv("ASTERISK_BOT_EXTENSION", "1000")
CUSTOMER = os.getenv("TELEPHONY_E2E_CUSTOMER", "cust-susanth")
SOURCE = "telephony_e2e"


def wait_for(check: Callable[[], Any], *, timeout: float, every: float = 1.0, what: str = "condition") -> Any:
    deadline = time.monotonic() + timeout
    while True:
        value = check()
        if value:
            return value
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out after {timeout:.0f}s waiting for {what}")
        time.sleep(every)


def phone(method: str, path: str, *, query: dict | None = None, body: dict | None = None, raw: bool = False) -> Any:
    url = PHONES_ARI + path + ("?" + urllib.parse.urlencode(query) if query else "")
    req = urllib.request.Request(url, method=method, data=None if body is None else json.dumps(body).encode())
    req.add_header("Authorization", "Basic " + base64.b64encode(b"phones:phones").decode())
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=10) as resp:
        payload = resp.read()
    return payload if raw else (json.loads(payload) if payload else {})


def pbx(method: str, path: str, **kwargs: Any) -> Any:
    from voice import asterisk_ops

    return asterisk_ops.ari(method, path, **kwargs)


def sql(query: str, **params: Any) -> list[dict[str, Any]]:
    import db
    from sqlalchemy import text

    with db.engine.connect() as conn:
        return [dict(r) for r in conn.execute(text(query), params).mappings()]


def alive(channel_id: str) -> bool:
    try:
        phone("GET", f"/channels/{channel_id}")
        return True
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False
        raise


class Call:
    """One call the borrower phone placed to the bot."""

    def __init__(self, script: str) -> None:
        self.rec = f"e2e-{script}-{uuid.uuid4().hex[:8]}"
        before = {c["id"] for c in pbx("GET", "/channels")}
        self.phone_channel = phone(
            "POST",
            "/channels",
            query={
                "endpoint": f"PJSIP/{BOT}@pbx-{BORROWER}",
                "context": script,
                "extension": "s",
                "priority": 1,
                "callerId": BORROWER,
            },
            body={"variables": {"REC": self.rec}},
        )["id"]
        # The PBX's SIP leg for this call: the new channel that is not a media leg.
        self.sip_id = wait_for(
            lambda: next(
                (
                    c["id"]
                    for c in pbx("GET", "/channels")
                    if c["id"] not in before and c["name"].startswith(f"PJSIP/{BORROWER}-")
                ),
                None,
            ),
            timeout=15,
            what="the PBX leg of the test call",
        )

    def wait_ended(self, timeout: float = 150) -> None:
        wait_for(lambda: not alive(self.phone_channel), timeout=timeout, every=2, what="the call to end")

    def interaction(self, timeout: float = 60) -> str:
        return wait_for(
            lambda: next(
                iter(r["interaction_id"] for r in sql(
                    "SELECT interaction_id FROM voice_sessions WHERE provider_call_id = :sid", sid=self.sip_id
                )),
                None,
            ),
            timeout=timeout,
            what=f"voice_sessions row for {self.sip_id}",
        )

    def heard(self) -> bytes:
        return phone("GET", f"/recordings/stored/{self.rec}-heard/file", raw=True)


def transcript(interaction_id: str) -> list[dict[str, Any]]:
    return sql(
        "SELECT turn_index, speaker, text FROM interaction_transcript WHERE interaction_id = :ix ORDER BY turn_index",
        ix=interaction_id,
    )


@pytest.fixture(autouse=True)
def _dial_through_asterisk(monkeypatch: pytest.MonkeyPatch) -> None:
    """These tests are the Asterisk path.

    The suite-wide default pins the provider to Twilio so the carrier-contract
    tests patch the adapter they mean; here that would send the dial into the
    Twilio adapter, which refuses to run under pytest.
    """
    monkeypatch.setenv("TELEPHONY_PROVIDER", "asterisk")


@pytest.fixture(scope="session", autouse=True)
def phones_registered() -> None:
    for ext in (BORROWER, AGENT):
        wait_for(
            lambda ext=ext: pbx("GET", f"/endpoints/PJSIP/{ext}").get("state") == "online",
            timeout=60,
            what=f"test phone {ext} to register",
        )


@pytest.fixture
def dial() -> Callable[..., dict[str, Any]]:
    """Place a real outbound attempt to the borrower phone in a given mode."""
    placed: list[str] = []

    def _dial(mode: str = "talk") -> dict[str, Any]:
        import db
        import outbound

        phone("POST", "/asterisk/variable", query={"variable": "BORROWER_MODE", "value": mode})
        with db.engine.begin() as conn:
            attempt = outbound.reserve(
                conn,
                customer_id=CUSTOMER,
                to_phone=BORROWER,
                objective="dpd_reminder",
                context={"source": SOURCE},
                idempotency_key=f"{SOURCE}-{uuid.uuid4().hex}",
            )
        result = outbound.place(db.engine, attempt, to_phone=BORROWER)
        placed.append(attempt["id"])
        return {"attempt": attempt, "result": result}

    yield _dial

    import db
    import outbound

    with db.engine.begin() as conn:
        for attempt_id in placed:
            outbound.mark(conn, attempt_id, state=outbound.STATE_CANCELED)


def attempt_row(attempt_id: str) -> dict[str, Any]:
    return sql("SELECT * FROM call_attempts WHERE id = :id", id=attempt_id)[0]
