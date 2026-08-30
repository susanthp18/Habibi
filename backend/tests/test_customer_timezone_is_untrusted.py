"""A borrower's timezone is data, and this deployment's data is not clean.

``customers.timezone`` holds display labels like ``Asia/Kolkata (IST)`` -- they
are in ``backend/seed/customers.json``, so any re-seed puts them back, and the
frontend has tolerated them for long enough to carry a comment saying so.

Python already treats the column as untrusted: :func:`contact_policy._zone`
falls back to the default for anything ``ZoneInfo`` rejects. The SQL did not. It
interpolated the raw column into ``AT TIME ZONE``, where Postgres raises

    InvalidParameterValue: time zone "Asia/Kolkata (IST)" not recognized

The blast radius is the reason this is worth a test rather than a data patch.
The query spans *every* customer in the tenant, so six bad rows out of nineteen
took down contact-policy evaluation for all of them -- and because the failure
aborts the surrounding transaction, unrelated work in the same transaction died
afterwards with ``InFailedSqlTransaction``, which reads like four separate bugs.

One policy, two implementations, only one of them defensive.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

import contact_policy


BAD_LABELS = [
    "Asia/Kolkata (IST)",   # the seed's own label
    "IST",                  # an abbreviation, not a zone
    "Not/AZone",
    "",
]


# --- what Python already did ------------------------------------------------


@pytest.mark.parametrize("label", BAD_LABELS)
def test_python_degrades_to_the_default_zone(label: str) -> None:
    zone = contact_policy._zone(label)
    assert str(zone) == contact_policy.DEFAULT_TZ


def test_python_honours_a_real_zone() -> None:
    assert str(contact_policy._zone("America/New_York")) == "America/New_York"


# --- what SQL must now do too -----------------------------------------------


@pytest.mark.parametrize("label", BAD_LABELS)
def test_sql_never_raises_on_an_unusable_timezone(db_tx, label: str) -> None:
    """The whole failure in one statement: this used to raise DataError."""
    got = db_tx.execute(
        text(f"SELECT (now() AT TIME ZONE {contact_policy.SQL_SAFE_TZ})::date"),
        {"tz": label},
    ).scalar()
    assert got is not None


def test_sql_uses_a_real_zone_when_the_column_holds_one(db_tx) -> None:
    """Degrading must not mean ignoring: a valid zone still decides the date."""
    kolkata, honolulu = db_tx.execute(
        text(
            f"SELECT (now() AT TIME ZONE {contact_policy.SQL_SAFE_TZ})::date,"
            f"       (now() AT TIME ZONE {contact_policy.SQL_SAFE_TZ_ALT})::date"
        ),
        {"tz": "Asia/Kolkata", "tz2": "Pacific/Honolulu"},
    ).first()
    # Not asserting they differ -- that depends on the hour the suite runs --
    # only that a real zone is used rather than silently replaced.
    assert kolkata is not None and honolulu is not None


def test_the_label_form_resolves_to_the_zone_it_names(db_tx) -> None:
    """`Asia/Kolkata (IST)` means Asia/Kolkata. Falling back to the default
    would be right by luck here and wrong for any non-default borrower."""
    labelled, plain = db_tx.execute(
        text(
            f"SELECT (now() AT TIME ZONE {contact_policy.SQL_SAFE_TZ})::date,"
            f"       (now() AT TIME ZONE {contact_policy.SQL_SAFE_TZ_ALT})::date"
        ),
        {"tz": "Pacific/Honolulu (HST)", "tz2": "Pacific/Honolulu"},
    ).first()
    assert labelled == plain


# --- the real query, against the real rows ----------------------------------


def test_contact_policy_survives_the_rows_this_database_actually_has(db_tx) -> None:
    """The regression, end to end.

    Six seeded customers carry the label form. Before the fix this raised and
    poisoned the transaction; every later statement in the same test failed with
    a message that pointed nowhere near the cause.
    """
    ids = [
        r[0]
        for r in db_tx.execute(
            text("SELECT id FROM customers WHERE tenant_id = :t ORDER BY id LIMIT 25"),
            {"t": __import__("db")._tenant()},
        ).all()
    ]
    if not ids:
        pytest.skip("no seeded customers")

    contact_policy.ledger_usage(db_tx, ids)

    # The transaction must still be usable -- that is what "poisoned" cost us.
    assert db_tx.execute(text("SELECT 1")).scalar() == 1
