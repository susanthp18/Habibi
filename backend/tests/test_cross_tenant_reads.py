"""Another tenant's records must not appear, by list or by id.

Pass 1 bounded the list accessors and recorded them as "bounded and
tenant-scoped". The bounding happened; for seven of them the tenant predicate
did not, and nothing tested it — the tenancy tests written at the time covered
the *configuration* tables (products, rubrics, personas) and never the
collections work queues. `list_callbacks` had no ``WHERE`` clause at all.

So this file tests the property directly instead of by reading the SQL: seed a
second tenant with a complete customer graph, then assert that every accessor
which could return one of those rows does not.

Two shapes, and the second matters more. A list leak shows another tenant's
rows to whoever opens the screen. A by-id leak answers a question the caller
asked on purpose — supply someone else's id and read, or write, that record. The
first is a mistake; the second is what a probe looks like.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

import db

RIVAL = "rival.bank"

#: A whole customer graph under a second tenant. Ordered by dependency; the
#: CHECK constraints on promises/interactions require the owner columns, so the
#: rival user has to exist before either.
_SEED = (
    "INSERT INTO tenants (id,name) VALUES (:t,'Rival Bank')",
    "INSERT INTO users (id,tenant_id,name) VALUES ('rv-user',:t,'Rival Agent')",
    "INSERT INTO products (id,tenant_id,name,type,is_active)"
    " VALUES ('rv-prod',:t,'Rival Card','card',true)",
    "INSERT INTO customers (id,tenant_id,name,risk)"
    " VALUES ('rv-cust',:t,'Rival Customer','low')",
    "INSERT INTO accounts (id,customer_id,product_id,status)"
    " VALUES ('rv-acct','rv-cust','rv-prod','active')",
    "INSERT INTO promises (id,customer_id,account_id,owner_kind,owner_user_id,amount,"
    "promised_at,status,reminder_status)"
    " VALUES ('rv-promise','rv-cust','rv-acct','human','rv-user',1000,now(),'upcoming','off')",
    "INSERT INTO callbacks (id,customer_id,reason,scheduled_at,status)"
    " VALUES ('rv-callback','rv-cust','Rival callback',now(),'scheduled')",
    "INSERT INTO disputes (id,customer_id,account_id,type,status)"
    " VALUES ('rv-dispute','rv-cust','rv-acct','fee_waiver','new')",
    "INSERT INTO payment_plans (id,customer_id,account_id,total_amount)"
    " VALUES ('rv-plan','rv-cust','rv-acct',5000)",
    "INSERT INTO leads (id,customer_id,stage) VALUES ('rv-lead','rv-cust','interested')",
    "INSERT INTO document_requests (id,customer_id,account_id,doc_type,delivery_channel,status)"
    " VALUES ('rv-doc','rv-cust','rv-acct','noc','email','requested')",
    "INSERT INTO consent_records (id,customer_id) VALUES ('rv-consent','rv-cust')",
    "INSERT INTO interactions (id,tenant_id,customer_id,handler_kind,handler_user_id,"
    "channel,status) VALUES ('rv-ix',:t,'rv-cust','human','rv-user','voice','completed')",
    "INSERT INTO conversations (id,customer_id,interaction_id,channel,status)"
    " VALUES ('rv-conv','rv-cust','rv-ix','whatsapp','bot')",
    "INSERT INTO treatment_holds (id,tenant_id,customer_id,kind,reason,source)"
    " VALUES ('rv-hold',:t,'rv-cust','hardship','Rival hardship','manual')",
    "INSERT INTO treatment_decisions (id,tenant_id,customer_id,account_id,trigger_kind,"
    "trigger_ref,mode,recommender,recommender_version,feature_schema_version,chosen_action)"
    " VALUES ('rv-td',:t,'rv-cust','rv-acct','bounce','rv-case','shadow','ev','1','v2','whatsapp')",
)


@pytest.fixture
def rival(db_tx):
    """A second tenant's customer graph, rolled back with the fixture."""
    for statement in _SEED:
        db_tx.execute(text(statement), {"t": RIVAL})
    return db_tx


# ---------------------------------------------------------------------------
# List accessors
# ---------------------------------------------------------------------------

#: ``(accessor, id that must not appear)``. Every entry here returned the rival
#: row before this file existed, except the two marked scoped in pass 1.
_LISTS = [
    ("list_customers", "rv-cust"),
    ("list_promises", "rv-promise"),
    ("list_callbacks", "rv-callback"),
    ("list_disputes", "rv-dispute"),
    ("list_payment_plans", "rv-plan"),
    ("list_leads", "rv-lead"),
    ("list_documents", "rv-doc"),
    ("list_consent", "rv-consent"),
    ("list_calls", "rv-ix"),
    # Found by test_every_customer_derived_list_is_covered below, not by
    # inspection: its own docstring called it "the unfiltered tenant queue"
    # while it carried no tenant predicate, and it was unbounded besides.
    ("list_work_items", "rv-callback"),
    ("list_treatment_holds", "rv-hold"),
    ("list_treatment_cases", "rv-case"),
    # Returns {items, activeInteractionId} rather than a bare list — see
    # _row_ids. Flagged by the coverage test below, not by inspection: it was
    # added with the bounce work and nothing here had been taught about it.
    ("list_handoff_queue", "rv-ix"),
]


def _row_ids(result: object) -> set[str]:
    """Every id an accessor's payload exposes, whatever shape it returns.

    Most accessors return a list of row dicts; the handoff queue returns an
    envelope with the rows under ``items``. Normalising here rather than
    special-casing keeps the coverage test below able to demand that *any* new
    accessor is listed, without also demanding it return a particular shape.
    """
    rows: list = []
    if isinstance(result, dict):
        for value in result.values():
            if isinstance(value, list):
                rows.extend(value)
    elif isinstance(result, list):
        rows = result
    ids: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key in ("id", "interactionId", "handoffId", "triggerRef"):
            if row.get(key) is not None:
                ids.add(str(row[key]))
    return ids


@pytest.mark.parametrize("accessor,rival_id", _LISTS)
def test_list_accessor_excludes_another_tenant(rival, accessor: str, rival_id: str) -> None:
    kwargs = {"assignee": None} if accessor == "list_work_items" else {}
    ids = _row_ids(getattr(db, accessor)(**kwargs))
    assert rival_id not in ids, (
        f"{accessor}() returned {rival_id!r}, which belongs to {RIVAL}. "
        "Every one of these joins customers — the predicate belongs on that join."
    )


def test_every_customer_derived_list_is_covered() -> None:
    """Stops the coverage of this file from silently falling behind.

    The gap being tested for was not that a predicate was written wrongly — it
    was that seven accessors nobody had thought to check were missing one.
    """
    import inspect

    customer_screens = {
        name
        for name, fn in inspect.getmembers(db, inspect.isfunction)
        if name.startswith("list_")
        and getattr(fn, "__module__", "") == "db"
        and "customers" in (inspect.getsource(fn) or "")
    }
    covered = {accessor for accessor, _ in _LISTS}
    missing = customer_screens - covered
    assert not missing, (
        "these list accessors read customer data and no test here proves they "
        f"scope it to one tenant: {sorted(missing)}"
    )


# ---------------------------------------------------------------------------
# By-id paths — the ones a caller drives with an id they chose
# ---------------------------------------------------------------------------

#: ``(function, args)`` where the first argument is another tenant's row id.
_BY_ID = [
    ("patch_callback", ("rv-callback", {"status": "completed"})),
    ("add_callback_reminder", ("rv-callback", {"channel": "sms"})),
    ("patch_dispute", ("rv-dispute", {"status": "resolved"})),
    ("add_dispute_note", ("rv-dispute", {"note": "probe"})),
    ("patch_document_request", ("rv-doc", {"status": "sent"})),
    ("add_document_delivery_attempt", ("rv-doc", {"channel": "email"})),
    ("patch_lead", ("rv-lead", {"stage": "won"})),
    ("add_lead_followup", ("rv-lead", {"note": "probe"})),
    ("patch_promise", ("rv-promise", {"status": "kept"})),
    ("wrap_up_interaction", ("rv-ix", {"disposition": "resolved"})),
    ("takeover_conversation", ("rv-conv",)),
    ("return_conversation_to_bot", ("rv-conv",)),
    ("patch_consent", ("rv-cust", {"dndRegistry": True})),
    ("release_treatment_hold", ("rv-hold", {"reason": "probe"})),
    # A hold on somebody else's borrower is a write against that borrower, so
    # it must 404 on the customer id rather than succeed against a customer the
    # caller cannot see.
    ("create_treatment_hold", ({"customerId": "rv-cust", "kind": "hardship"},)),
    ("next_treatment", ()),
]


#: Keyword-only entry points cannot be driven positionally.
_BY_ID_KWARGS = {"next_treatment": {"customer_id": "rv-cust"}}


@pytest.mark.parametrize("fn_name,args", _BY_ID)
def test_by_id_write_refuses_another_tenants_row(rival, fn_name: str, args: tuple) -> None:
    """Must raise KeyError — which the API layer turns into 404.

    Deliberately not a distinct 403: telling the caller the record exists but
    belongs to someone else confirms the id, and these ids are guessable.
    """
    with pytest.raises(KeyError):
        getattr(db, fn_name)(*args, **_BY_ID_KWARGS.get(fn_name, {}))


def test_the_guard_still_allows_this_tenants_rows(db_tx) -> None:
    """The other half — a guard that refuses everything would pass every test
    above and break the application."""
    own = db_tx.execute(
        text(
            "SELECT cb.id FROM callbacks cb JOIN customers c ON c.id = cb.customer_id "
            " WHERE c.tenant_id = :t LIMIT 1"
        ),
        {"t": db.current_tenant()},
    ).scalar()
    if own is None:
        pytest.skip("no callback in the seed for this tenant")
    db._assert_tenant_owns(db_tx, "callbacks", own)  # must not raise


def test_guard_rejects_a_table_outside_the_allow_list(db_tx) -> None:
    """The table name is interpolated into SQL, so the allow-list is load-bearing."""
    with pytest.raises(ValueError, match="allow-listed"):
        db._assert_tenant_owns(db_tx, "users; DROP TABLE customers", "x")
