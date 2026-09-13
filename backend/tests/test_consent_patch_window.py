"""A channel-only PATCH must not rewrite the stored consent window.

``patch_consent`` used to persist whatever the GET serializer emitted, so a save
that only toggled a channel reformatted ``allowed_days`` / ``allowed_hours`` /
``customers.preferred_window``. An en-dash ``Mon–Sat`` became ``Mon-Mon``; a
NULL window became ``Mon-Fri`` / ``10:00-19:00 IST``. After the first rewrite
both parsers agreed, and the original consent was unrecoverable.

WP-030 consolidates the parser. This file only pins that the write does not
happen.
"""

from __future__ import annotations

import uuid

from sqlalchemy import text

import db

# The GET serializer's hyphen-only parser sees this as Monday. Sending that
# parse back is the write this package has to refuse.
EN_DASH_DAYS = "Mon–Sat"


def _get_echo(days_raw: str | None, hours_raw: str | None) -> dict:
    """What ``list_consent`` puts in ``allowedWindow`` for these stored strings."""
    start, end = db._parse_allowed_hours(hours_raw)
    return {"days": db._parse_allowed_days(days_raw), "startHour": start, "endHour": end}


def _fresh(db_tx, *, days: str | None, hours: str | None, preferred: str | None) -> str:
    cid = f"wp002-{uuid.uuid4().hex[:10]}"
    cr_id = f"cr-{cid}"
    db_tx.execute(
        text(
            """
            INSERT INTO customers (id, tenant_id, name, risk, preferred_window)
            VALUES (:id, :t, 'WP-002', 'low', :w)
            """
        ),
        {"id": cid, "t": db.current_tenant(), "w": preferred},
    )
    db_tx.execute(
        text(
            """
            INSERT INTO consent_records (id, customer_id, allowed_days, allowed_hours)
            VALUES (:id, :cid, :days, :hours)
            """
        ),
        {"id": cr_id, "cid": cid, "days": days, "hours": hours},
    )
    db_tx.execute(
        text(
            """
            INSERT INTO channel_consents
              (id, consent_id, channel, purpose, status, source, captured_at)
            VALUES
              (:id, :cr, 'sms', 'servicing', 'opted_in', 'Agent', now())
            """
        ),
        {"id": f"{cr_id}-sms-servicing", "cr": cr_id},
    )
    return cid


def _stored(db_tx, customer_id: str) -> dict:
    row = db_tx.execute(
        text(
            """
            SELECT cr.allowed_days, cr.allowed_hours, c.preferred_window
            FROM consent_records cr
            JOIN customers c ON c.id = cr.customer_id
            WHERE c.id = :id
            """
        ),
        {"id": customer_id},
    ).mappings().first()
    assert row is not None
    return dict(row)


def _sms_status(db_tx, customer_id: str) -> str | None:
    return db_tx.execute(
        text(
            """
            SELECT cc.status
            FROM channel_consents cc
            JOIN consent_records cr ON cr.id = cc.consent_id
            WHERE cr.customer_id = :id AND cc.channel = 'sms' AND cc.purpose = 'servicing'
            """
        ),
        {"id": customer_id},
    ).scalar()


def test_a_channel_toggle_leaves_an_en_dash_window_byte_identical(db_tx) -> None:
    """``Mon–Sat`` survives a save that only opted SMS out.

    The screen used to PATCH the GET payload, whose parser yielded Monday-only
    for an en-dash range. Writing that parse produced ``Mon-Mon``.

    WP-030 has since landed, so the parser reads all six days and the echo is
    faithful. That removes the *source* of the artefact; this test keeps
    guarding the second half — that a save touching only channels does not
    rewrite the window at all — which is a different guarantee and still the
    one that protects the borrower's recorded consent.
    """
    hours = "08:00-17:00 IST"
    cid = _fresh(db_tx, days=EN_DASH_DAYS, hours=hours, preferred=hours)
    echo = _get_echo(EN_DASH_DAYS, hours)
    assert echo["days"] == [1, 2, 3, 4, 5, 6], "WP-030: the en-dash range parses to six days"
    before = _stored(db_tx, cid)
    assert _sms_status(db_tx, cid) == "opted_in"

    db.patch_consent(
        cid,
        {
            "channels": [{"channel": "sms", "status": "opted_out"}],
            "allowedWindow": echo,
        },
    )

    after = _stored(db_tx, cid)
    assert after["allowed_days"] == EN_DASH_DAYS
    assert after["allowed_hours"] == hours
    assert after["preferred_window"] == hours
    assert after == before
    assert _sms_status(db_tx, cid) == "opted_out"


def test_a_channel_toggle_leaves_a_null_window_null(db_tx) -> None:
    """NULL stays NULL. The serializer defaults (Mon–Fri and the gate's 09–20
    bounds, `contact_window.window_hours`) must not land."""
    cid = _fresh(db_tx, days=None, hours=None, preferred=None)
    echo = _get_echo(None, None)
    assert echo == {"days": [1, 2, 3, 4, 5], "startHour": 9, "endHour": 20}
    before = _stored(db_tx, cid)
    assert _sms_status(db_tx, cid) == "opted_in"

    db.patch_consent(
        cid,
        {
            "channels": [{"channel": "sms", "status": "opted_out"}],
            "allowedWindow": echo,
        },
    )

    after = _stored(db_tx, cid)
    assert after["allowed_days"] is None
    assert after["allowed_hours"] is None
    assert after["preferred_window"] is None
    assert after == before
    assert _sms_status(db_tx, cid) == "opted_out"


def test_an_operator_changing_the_window_still_writes(db_tx) -> None:
    """The echo guard must not freeze an actual edit."""
    cid = _fresh(
        db_tx,
        days="Mon-Fri",
        hours="10:00-19:00 IST",
        preferred="10:00-19:00 IST",
    )

    db.patch_consent(
        cid,
        {"allowedWindow": {"days": [1, 2, 3, 4, 5, 6], "startHour": 9, "endHour": 18}},
    )

    after = _stored(db_tx, cid)
    assert after["allowed_days"] == "Mon-Sat"
    assert after["allowed_hours"] == "09:00-18:00 IST"
    assert after["preferred_window"] == "09:00-18:00 IST"


def test_an_hours_edit_leaves_an_en_dash_days_string_byte_identical(db_tx) -> None:
    """Changing hours must not reformat days.

    The GET parse of ``Mon–Sat`` used to be Monday-only, and writing that parse
    is how six days became ``Mon-Mon``. WP-030 fixed the parser, so the echo now
    round-trips; the field-by-field decision is still what stops an hours edit
    from rewriting the days text at all.
    """
    hours = "08:00-17:00 IST"
    cid = _fresh(db_tx, days=EN_DASH_DAYS, hours=hours, preferred=hours)
    echo = _get_echo(EN_DASH_DAYS, hours)
    assert echo["days"] == [1, 2, 3, 4, 5, 6]

    db.patch_consent(
        cid,
        {"allowedWindow": {**echo, "startHour": 9, "endHour": 18}},
    )

    after = _stored(db_tx, cid)
    assert after["allowed_days"] == EN_DASH_DAYS
    assert after["allowed_hours"] == "09:00-18:00 IST"
    assert after["preferred_window"] == "09:00-18:00 IST"


def test_a_days_edit_leaves_stored_hours_byte_identical(db_tx) -> None:
    """Changing days must not reformat hours. The GET parser keeps only the
    hour numbers, so writing that parse would turn ``08:30-17:45 IST`` into
    ``08:00-17:00 IST``.
    """
    hours = "08:30-17:45 IST"
    cid = _fresh(db_tx, days="Mon-Fri", hours=hours, preferred=hours)
    echo = _get_echo("Mon-Fri", hours)
    assert echo["startHour"] == 8 and echo["endHour"] == 17

    db.patch_consent(
        cid,
        {"allowedWindow": {**echo, "days": [1, 2, 3, 4, 5, 6]}},
    )

    after = _stored(db_tx, cid)
    assert after["allowed_days"] == "Mon-Sat"
    assert after["allowed_hours"] == hours
    assert after["preferred_window"] == hours


def test_an_hours_edit_leaves_null_days_null(db_tx) -> None:
    """A NULL days column is not a Mon–Fri artefact. An hours edit must not
    stamp the serializer default onto it.
    """
    cid = _fresh(db_tx, days=None, hours=None, preferred=None)
    echo = _get_echo(None, None)

    db.patch_consent(
        cid,
        {"allowedWindow": {**echo, "startHour": 9, "endHour": 18}},
    )

    after = _stored(db_tx, cid)
    assert after["allowed_days"] is None
    assert after["allowed_hours"] == "09:00-18:00 IST"
    assert after["preferred_window"] == "09:00-18:00 IST"


def test_a_first_write_records_no_window_the_borrower_never_gave(db_tx) -> None:
    """The consent row a channel toggle creates carries no window.

    ``_ensure_consent_record`` used to insert ``Mon-Fri`` / ``10:00-19:00 IST``
    for a borrower with no row -- a preference nobody recorded, written by the
    first operator to toggle a channel and indistinguishable afterwards from
    one the borrower gave. Nothing on file stays nothing on file; the readers
    fall back to the platform default and the statutory bound.
    """
    cid = f"wp002-{uuid.uuid4().hex[:10]}"
    db_tx.execute(
        text("INSERT INTO customers (id, tenant_id, name, risk) VALUES (:id, :t, 'WP-002', 'low')"),
        {"id": cid, "t": db.current_tenant()},
    )
    assert (
        db_tx.execute(
            text("SELECT count(*) FROM consent_records WHERE customer_id = :id"), {"id": cid}
        ).scalar()
        == 0
    )

    db.patch_consent(cid, {"channels": [{"channel": "sms", "status": "opted_out"}]})

    stored = _stored(db_tx, cid)
    assert stored["allowed_days"] is None
    assert stored["allowed_hours"] is None
    assert stored["preferred_window"] is None
    assert _sms_status(db_tx, cid) == "opted_out"


def test_a_whatsapp_first_contact_records_no_window_either(db_tx) -> None:
    """Same fabrication, second site: the customer row WhatsApp creates for an
    unknown number carried ``preferred_window = '10:00-19:00 IST'``."""
    import db_whatsapp

    phone = "+9199" + uuid.uuid4().hex[:8].translate(str.maketrans("abcdef", "123456"))
    customer, recognised = db_whatsapp._ensure_whatsapp_customer(db_tx, phone, "Window Test")
    assert recognised is False
    window = db_tx.execute(
        text("SELECT preferred_window FROM customers WHERE id = :id"), {"id": customer["id"]}
    ).scalar()
    assert window is None
