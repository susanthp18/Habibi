"""The audit chain covers consent and money, not only bot configuration.

`change_log` kept one chain per tenant with `entity_type = 'bot'`; consent
edits, opt-outs and ledger postings -- the records a regulator actually asks
about -- sat outside every chain, so a consent window or a waiver could be
edited in place under a green "chain intact" banner. Each entity now has its
own chain and head, and the writers put every change on it.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import text

from agent_core import change_log


def _customer(db_tx) -> str:
    row = db_tx.execute(
        text("SELECT id FROM customers WHERE id <> 'UNKNOWN-CALLER' ORDER BY id LIMIT 1")
    ).scalar()
    if not row:
        pytest.skip("no customers seeded")
    return str(row)


def _entries(db_tx, entity: str) -> list[dict]:
    import db

    rows = db_tx.execute(
        text(
            "SELECT payload FROM audit_log WHERE tenant_id = :t AND entity_type = :e"
            " ORDER BY COALESCE((payload->>'seq')::bigint, 0)"
        ),
        {"t": db.current_tenant(), "e": entity},
    ).scalars().all()
    return [r if isinstance(r, dict) else json.loads(r) for r in rows]


def test_an_opt_out_lands_on_the_consent_chain(db_tx) -> None:
    import db

    cid = _customer(db_tx)
    bot_before = len(_entries(db_tx, change_log.ENTITY_BOT))
    before = len(_entries(db_tx, change_log.ENTITY_CONSENT))

    db.opt_out(cid, {"channel": "sms", "source": "Agent", "note": "asked on call"})

    entries = _entries(db_tx, change_log.ENTITY_CONSENT)
    assert len(entries) == before + 1
    last = entries[-1]
    assert last["action"] == change_log.CONSENT_CHANGE
    assert last["customerId"] == cid
    assert last["change"] == {"kind": "opt_out", "channel": "sms", "source": "Agent"}
    assert change_log.verify_chain(db_tx, tenant_id=db.current_tenant(), entity="consent")["ok"]
    # The bot chain is a different chain.
    assert len(_entries(db_tx, change_log.ENTITY_BOT)) == bot_before


def test_a_consent_edit_is_hashed_and_a_later_edit_of_the_entry_is_visible(db_tx) -> None:
    import db

    cid = _customer(db_tx)
    db.patch_consent(cid, {"dndRegistry": True, "note": "registry match"})
    tenant = db.current_tenant()
    ok = change_log.verify_chain(db_tx, tenant_id=tenant, entity="consent")
    assert ok["ok"], ok
    entry = _entries(db_tx, change_log.ENTITY_CONSENT)[-1]
    assert entry["change"]["kind"] in {"dnd_updated", "consent_updated"}
    assert entry["change"]["fields"] == {"dndRegistry": True}

    # Rewrite history -- as the owner, the only role that can (sql/43); the
    # app role's attempt is refused outright. The digest no longer matches.
    from sqlalchemy.exc import DBAPIError

    tamper = text(
        "UPDATE audit_log SET payload = jsonb_set(payload, '{change,fields,dndRegistry}', 'false')"
        " WHERE tenant_id = :t AND entity_type = 'consent'"
        "   AND (payload->>'seq')::bigint = :seq"
    )
    params = {"t": tenant, "seq": int(entry["seq"])}
    nested = db_tx.begin_nested()
    with pytest.raises(DBAPIError, match="append-only"):
        db_tx.execute(tamper, params)
    nested.rollback()
    # The entry is uncommitted (db_tx); tamper the payload in memory instead
    # and verify the way the owner would have made it look.
    body = {k: v for k, v in entry.items() if k != "entryHash"}
    body["change"]["fields"]["dndRegistry"] = False
    assert change_log._digest(body) != entry["entryHash"]


def test_a_ledger_posting_lands_on_the_ledger_chain(db_tx) -> None:
    import db
    import payments

    row = {
        "id": db._id("LED"),
        "account_id": db_tx.execute(text("SELECT id FROM accounts ORDER BY id LIMIT 1")).scalar(),
        "type": "fee",
        "description": "test fee",
        "amount": 10.0,
        "posted_at": "2026-09-11T00:00:00+00:00",
    }
    before = len(_entries(db_tx, change_log.ENTITY_LEDGER))
    payments._chain_ledger(db_tx, row, tenant_id=None)
    entries = _entries(db_tx, change_log.ENTITY_LEDGER)
    assert len(entries) == before + 1
    assert entries[-1]["action"] == change_log.LEDGER_ENTRY
    assert entries[-1]["entry"]["id"] == row["id"]
    assert change_log.verify_chain(db_tx, tenant_id=db.current_tenant(), entity="ledger")["ok"]


def test_every_money_writer_is_on_the_chain() -> None:
    """The three INSERT INTO ledger_entries sites outside seeds each chain."""
    from pathlib import Path

    backend = Path(__file__).resolve().parents[1]
    for rel in ("payments.py", "payment_events.py", "agent_core/authority/enact.py"):
        src = (backend / rel).read_text(encoding="utf-8")
        assert src.count("INSERT INTO ledger_entries") == 1, rel
        assert "_chain_ledger(" in src, rel
