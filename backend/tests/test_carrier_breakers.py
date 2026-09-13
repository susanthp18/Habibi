"""The TTS preview vendors and Key Vault sit behind breakers.

Their HTTP calls ran bare: a vendor that was down was retried on every
preview and every secret resolution. A transport fault counts; a rejected
key is the pool's business and does not.
"""

from __future__ import annotations

import httpx
import pytest

import circuit_breaker


@pytest.fixture(autouse=True)
def _fresh_breakers():
    for name in ("fish_tts", "openrouter_tts", "azure_key_vault"):
        circuit_breaker._breakers.pop(name, None)
    yield
    for name in ("fish_tts", "openrouter_tts", "azure_key_vault"):
        circuit_breaker._breakers.pop(name, None)


def test_fish_transport_faults_open_the_breaker(monkeypatch) -> None:
    from agent_core.providers import fish_tts, pool as pool_mod

    monkeypatch.setenv("CIRCUIT_FAILURE_THRESHOLD", "2")
    monkeypatch.setattr(pool_mod, "call_with_rotation", lambda _p, fn, **_k: fn("key"))

    def _down(*_a, **_k):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "post", _down)
    for _ in range(2):
        with pytest.raises(fish_tts.FishTTSError, match="transport error"):
            fish_tts.synthesize("hello", reference_id="v1")
    with pytest.raises(fish_tts.FishTTSError, match="unavailable"):
        fish_tts.synthesize("hello", reference_id="v1")
    assert circuit_breaker.get_breaker("fish_tts").snapshot()["state"] == "open"


def test_a_rejected_key_does_not_count_against_the_vendor(monkeypatch) -> None:
    from agent_core.providers import fish_tts, pool as pool_mod

    monkeypatch.setenv("CIRCUIT_FAILURE_THRESHOLD", "1")

    def _rotation(_p, fn, **_k):
        with pytest.raises(pool_mod.KeyRejected):
            fn("dead-key")
        raise pool_mod.NoKeysAvailable("fish: no keys")

    monkeypatch.setattr(pool_mod, "call_with_rotation", _rotation)
    monkeypatch.setattr(httpx, "post", lambda *_a, **_k: httpx.Response(401, request=httpx.Request("POST", "x")))
    with pytest.raises(fish_tts.FishTTSError):
        fish_tts.synthesize("hello", reference_id="v1")
    assert circuit_breaker.get_breaker("fish_tts").snapshot()["state"] == "closed"


def test_key_vault_runs_through_its_breaker(monkeypatch) -> None:
    from agent_core.vault import persist

    monkeypatch.setenv("CIRCUIT_FAILURE_THRESHOLD", "1")
    monkeypatch.setenv("AZURE_KEY_VAULT_TOKEN", "t")
    monkeypatch.setattr(persist, "_azure_url", lambda: "https://vault.example")

    def _down(*_a, **_k):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "get", _down)
    with pytest.raises(httpx.ConnectError):
        persist._get_azure("s1")
    with pytest.raises(circuit_breaker.CircuitOpenError):
        persist._get_azure("s1")


def test_a_carrier_stop_reaches_the_opt_out_ledger(db_tx, monkeypatch) -> None:
    """Twilio 21610 is the recipient replying STOP. It used to surface as a
    plain CarrierRejected -- a bad number to every sender -- and the consent
    ledger never heard of it. Every SMS leaves through twilio_sms.send, so
    that is where the STOP is written down: sms opted out, the event naming
    the carrier as its source, and the send still fails to its caller."""
    from sqlalchemy import text
    from twilio.base.exceptions import TwilioRestException

    import actor_context
    import twilio_sms
    from voice import twilio_ops

    customer = db_tx.execute(
        text("SELECT id FROM customers WHERE id <> 'UNKNOWN-CALLER' ORDER BY id LIMIT 1")
    ).scalar()
    if customer is None:
        pytest.skip("no customers seeded")
    circuit_breaker._breakers.pop("twilio", None)

    class _Messages:
        def create(self, **_kw):
            raise TwilioRestException(400, "/Messages", msg="STOP", code=21610)

    class _Client:
        messages = _Messages()

    monkeypatch.setattr(twilio_sms, "configured", lambda: True)
    monkeypatch.setattr(twilio_sms, "from_number", lambda: "+15005550006")
    monkeypatch.setattr(twilio_sms, "status_callback_url", lambda: None)
    monkeypatch.setattr(twilio_ops, "rest_client", lambda: _Client())
    monkeypatch.setattr("agent_core.carrier_guard.refuse_real_carrier", lambda _n: None)
    monkeypatch.setattr(actor_context, "get_actor_kind", lambda: "system")

    with pytest.raises(twilio_ops.CarrierOptOut):
        twilio_sms.send(to_phone="+919876543210", body="hi", customer_id=customer)

    status = db_tx.execute(
        text(
            """
            SELECT cc.status FROM channel_consents cc
            JOIN consent_records cr ON cr.id = cc.consent_id
            WHERE cr.customer_id = :c AND cc.channel = 'sms' AND cc.purpose = 'servicing'
            """
        ),
        {"c": customer},
    ).scalar()
    assert status == "opted_out"
    event = db_tx.execute(
        text(
            """
            SELECT oe.source, oe.actor_kind, oe.actor_user_id FROM optout_events oe
            JOIN consent_records cr ON cr.id = oe.consent_id
            WHERE cr.customer_id = :c ORDER BY oe.created_at DESC LIMIT 1
            """
        ),
        {"c": customer},
    ).mappings().first()
    assert event["source"] == "carrier"
    assert event["actor_kind"] == "system" and event["actor_user_id"] is None
    # a STOP is the recipient's decision, not a carrier fault
    assert circuit_breaker.get_breaker("twilio").snapshot()["state"] == "closed"


def test_a_minio_delete_runs_through_the_breaker(monkeypatch) -> None:
    """Reads and writes were behind the MinIO breaker; the delete was not,
    so a recording purge against a MinIO that is down was retried at full
    rate by every sweep."""
    import storage

    circuit_breaker._breakers.pop("minio", None)
    monkeypatch.setenv("CIRCUIT_FAILURE_THRESHOLD", "1")
    monkeypatch.setattr(storage, "is_configured", lambda: True)

    class _Client:
        def remove_object(self, bucket, key):
            raise ConnectionError("minio down")

    monkeypatch.setattr(storage, "get_client", lambda: _Client())
    assert storage.delete_object("minio://recordings/x.wav") is False
    assert circuit_breaker.get_breaker("minio").snapshot()["state"] == "open"
    assert storage.delete_object("minio://recordings/y.wav") is False  # open circuit, no call


def test_tenant_contacts_reads_on_the_callers_connection(db_tx) -> None:
    """Both senders call it inside a transaction; it used to open a second
    pool connection per message and could not see a row the caller's own
    transaction had just written."""
    from sqlalchemy import text

    import compliance_copy
    import db

    db_tx.execute(
        text("UPDATE tenants SET name = 'Savepoint Bank' WHERE id = :t"), {"t": db.TENANT_ID}
    )
    assert compliance_copy.tenant_contacts(db.TENANT_ID, conn=db_tx)["issuer"] == "Savepoint Bank"
