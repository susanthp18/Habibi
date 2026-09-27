"""Consent screen: bulk import validation, dry run, the servicing/promotional split.

No database: the planner and the grouping are pure, and the import's writes
are swapped for recorders so a dry run can be shown to write nothing.
"""

from __future__ import annotations

import contextlib
import csv
import io
from types import SimpleNamespace

import db_consent

STATE = {
    "C-1": {"dnd": False, "status": {("call", "servicing"): "opted_out", ("whatsapp", "servicing"): "opted_in"}},
    "C-2": {"dnd": True, "status": {}},
}


def _row(**kw):
    return {"customer_id": "C-1", "channel": "voice", "status": "opted_in", **kw}


def test_rows_are_validated_one_by_one() -> None:
    results = db_consent._plan_import(
        [
            _row(channel="fax"),
            _row(customer_id="C-404"),
            _row(status="maybe"),
            _row(purpose="upsell"),
            _row(dnd="perhaps"),
            _row(),
            _row(),  # duplicate of the row above
        ],
        STATE,
    )
    errors = [r["error"] for r in results]
    assert "Unknown channel" in errors[0]
    assert errors[1] == "Customer C-404 not found"
    assert "Unknown status" in errors[2]
    assert "Unknown purpose" in errors[3]
    assert "dnd must be true or false" in errors[4]
    assert errors[5] is None and results[5]["ok"] and results[5]["change"] == "opt_in"
    assert errors[6] == "Duplicate of row 6"


def test_change_is_computed_against_the_stored_row() -> None:
    results = db_consent._plan_import(
        [
            {"customer_id": "C-1", "channel": "whatsapp", "status": "opted_in"},  # already in
            {"customer_id": "C-1", "channel": "whatsapp", "status": "opted_in", "purpose": "promotional"},
            {"customer_id": "C-2", "channel": "sms", "status": "opted_out", "dnd": "false"},
            {"customer_id": "C-2", "channel": "email", "status": "opted_out", "dnd": "true"},  # contradicts
        ],
        STATE,
    )
    assert [r["change"] for r in results[:3]] == ["none", "opt_in", "opt_out"]
    assert results[2]["dndChange"] == "dnd_off"
    assert results[3]["error"] == "dnd contradicts row 3"


class _Engine:
    def begin(self):
        return contextlib.nullcontext(object())


def _wire(monkeypatch) -> list[tuple]:
    calls: list[tuple] = []
    monkeypatch.setattr(db_consent, "_db", lambda: SimpleNamespace(engine=_Engine()))
    monkeypatch.setattr(db_consent, "_import_state", lambda conn, ids: STATE)
    monkeypatch.setattr(db_consent, "_patch_consent_tx", lambda conn, cid, p: calls.append(("patch", cid, p)))
    monkeypatch.setattr(db_consent, "_opt_out_tx", lambda conn, cid, p: calls.append(("opt_out", cid, p)))
    return calls


ROWS = [
    {"customer_id": "C-1", "channel": "voice", "status": "opted_in", "note": "re-consented"},
    {"customer_id": "C-1", "channel": "whatsapp", "status": "opted_out"},
    {"customer_id": "C-2", "channel": "email", "status": "opted_in", "purpose": "promotional", "dnd": "no"},
    {"customer_id": "C-9", "channel": "sms", "status": "opted_in"},
]


def test_dry_run_writes_nothing(monkeypatch) -> None:
    calls = _wire(monkeypatch)
    summary = db_consent.import_consent(ROWS, dry_run=True)
    assert calls == []
    assert (summary["valid"], summary["invalid"], summary["applied"]) == (3, 1, 0)
    assert summary["changes"]["opt_in"] == 2 and summary["changes"]["opt_out"] == 1
    assert summary["changes"]["dnd_off"] == 1


def test_apply_goes_through_the_drawer_write_paths(monkeypatch) -> None:
    calls = _wire(monkeypatch)
    summary = db_consent.import_consent(ROWS, dry_run=False)
    assert summary["applied"] == 4
    assert ("opt_out", "C-1", {"channel": "whatsapp", "source": "Bulk Import", "note": "Bulk import"}) in calls
    patches = {cid: p for kind, cid, p in calls if kind == "patch"}
    assert patches["C-1"]["channels"] == [
        {"channel": "call", "status": "opted_in", "purpose": "servicing", "source": "Bulk Import"}
    ]
    assert "re-consented" in patches["C-1"]["note"]
    assert patches["C-2"]["dnd"] is False
    assert patches["C-2"]["channels"][0]["purpose"] == "promotional"
    # the opt-out lands before the same customer's consent save
    kinds = [k for k, cid, _ in calls if cid == "C-1"]
    assert kinds == ["opt_out", "patch"]


def _cc(channel, purpose, status, at):
    return {
        "consent_id": "consent-C-1",
        "channel": channel,
        "purpose": purpose,
        "status": status,
        "source": "Agent",
        "captured_at": at,
        "created_at": at,
        "weekly_frequency_cap": 3,
        "used_this_week": 0,
    }


def test_screen_status_is_the_servicing_row() -> None:
    # After an opt-out (both purposes closed) the servicing row was re-opted in.
    grouped = db_consent._group_channel_rows(
        [
            _cc("voice", "servicing", "opted_in", "2026-09-02"),
            _cc("voice", "promotional", "opted_out", "2026-09-01"),
            _cc("sms", "promotional", "opted_in", "2026-09-01"),
            _cc("email", "servicing", "opted_out", "2026-09-01"),
        ]
    )
    by_ch = {c["channel"]: c for c in grouped["consent-C-1"]}
    assert len(grouped["consent-C-1"]) == 3
    assert (by_ch["call"]["status"], by_ch["call"]["promotional"]) == ("opted_in", "opted_out")
    # promotional only: no servicing consent, but the promotional fact survives
    assert (by_ch["sms"]["status"], by_ch["sms"]["promotional"]) == ("opted_out", "opted_in")
    assert by_ch["email"]["promotional"] is None


def test_registry_csv_shape() -> None:
    body = db_consent._registry_csv(
        [
            {
                "id": "C-1", "name": "=HYPERLINK(1)", "segment": "sme", "customer_dnd": False,
                "dnd_registry": True, "preferred_window": None, "consent_id": "k1",
                "allowed_days": "Mon-Fri", "allowed_hours": "10:00-19:00 IST", "expires_at": None,
            },
            {
                "id": "C-2", "name": "B", "segment": None, "customer_dnd": False, "dnd_registry": None,
                "preferred_window": None, "consent_id": None, "allowed_days": None,
                "allowed_hours": None, "expires_at": None,
            },
        ],
        {("k1", "voice", "servicing"): "opted_in", ("k1", "voice", "promotional"): "opted_out"},
        {("k1", "voice"): "2026-09-01T00:00:00", ("k1", "all"): "2026-09-05T00:00:00"},
    )
    rows = list(csv.DictReader(io.StringIO(body)))
    assert rows[0]["customer_name"] == "'=HYPERLINK(1)"
    assert (rows[0]["segment"], rows[0]["dnd"]) == ("SME", "true")
    assert rows[0]["allowed_window"] == "Mon-Fri 10:00-19:00"
    assert (rows[0]["voice_servicing"], rows[0]["voice_promotional"]) == ("opted_in", "opted_out")
    assert rows[0]["voice_last_opt_out_at"] == "2026-09-05T00:00:00"
    assert rows[0]["sms_servicing"] == "not_captured"
    assert rows[1]["email_promotional"] == "not_captured" and rows[1]["dnd"] == "false"


# ---------------------------------------------------------------------------
# Against the database: the SQL behind the above
# ---------------------------------------------------------------------------


def test_import_round_trip_against_the_database(db_tx) -> None:
    import uuid

    from sqlalchemy import text

    import db

    cid = f"imp-{uuid.uuid4().hex[:10]}"
    cr_id = f"cr-{cid}"
    db_tx.execute(
        text("INSERT INTO customers (id, tenant_id, name, risk) VALUES (:id, :t, 'Import Probe', 'low')"),
        {"id": cid, "t": db.current_tenant()},
    )
    db_tx.execute(text("INSERT INTO consent_records (id, customer_id) VALUES (:id, :cid)"), {"id": cr_id, "cid": cid})
    db_tx.execute(
        text(
            "INSERT INTO channel_consents (id, consent_id, channel, purpose, status, source, captured_at) "
            "VALUES (:id, :cr, 'sms', 'servicing', 'opted_in', 'Agent', now())"
        ),
        {"id": f"{cr_id}-sms-servicing", "cr": cr_id},
    )

    def optouts() -> int:
        return db_tx.execute(text("SELECT count(*) FROM optout_events WHERE consent_id = :cr"), {"cr": cr_id}).scalar()

    out = [{"customer_id": cid, "channel": "sms", "status": "opted_out", "note": "regulator list"}]
    assert db_consent.import_consent(out, dry_run=True)["changes"]["opt_out"] == 1
    assert optouts() == 0

    assert db_consent.import_consent(out, dry_run=False)["applied"] == 1
    assert optouts() == 1
    back_in = [{"customer_id": cid, "channel": "sms", "status": "opted_in"}]
    assert db_consent.import_consent(back_in, dry_run=False)["applied"] == 1

    # Both purposes were closed by the opt-out; the re-opt-in is what shows.
    sms = next(c for c in db_consent._consent_channels_grouped(db_tx, [cr_id])[cr_id] if c["channel"] == "sms")
    assert (sms["status"], sms["promotional"]) == ("opted_in", "opted_out")
    kinds = db_tx.execute(
        text("SELECT kind FROM activity_events WHERE entity_id = :cid ORDER BY at, id"), {"cid": cid}
    ).scalars().all()
    assert "opt_out" in kinds and "consent_updated" in kinds

    rows = {r["customer_id"]: r for r in csv.DictReader(io.StringIO(db_consent.export_consent_csv()))}
    assert (rows[cid]["sms_servicing"], rows[cid]["sms_promotional"]) == ("opted_in", "opted_out")
    assert rows[cid]["sms_last_opt_out_at"]


def test_drawer_patch_keeps_the_promotional_purpose() -> None:
    """The drawer's PATCH used to drop `purpose`, so a promotional consent saved
    from the screen landed as servicing -- the offer gate could never pass."""
    from schemas.compliance import ConsentPatchRequest

    body = ConsentPatchRequest.model_validate(
        {"channels": [{"channel": "whatsapp", "status": "opted_in", "purpose": "promotional"}]}
    ).model_dump(exclude_unset=True)
    assert body["channels"][0]["purpose"] == "promotional"
