"""List endpoints must be bounded and tenant-scoped.

Both properties were missing on the calls list: it selected every interaction
the deployment had ever recorded and then loaded every transcript turn of every
one of them. Neither the row cap nor the tenant predicate can be expressed as
"usually true" — an accessor with an unbounded branch grows one caller that
uses it.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

import db


# ---------------------------------------------------------------------------
# Clamping
# ---------------------------------------------------------------------------


def test_none_limit_means_default_not_unbounded() -> None:
    assert db.clamp_list_limit(None) == min(db.DEFAULT_LIST_LIMIT, db.MAX_LIST_LIMIT)
    assert db.clamp_list_limit(None, 25) == 25


def test_limit_is_capped_at_the_ceiling() -> None:
    assert db.clamp_list_limit(10**9) == db.MAX_LIST_LIMIT
    assert db.clamp_list_limit(db.MAX_LIST_LIMIT + 1) == db.MAX_LIST_LIMIT


def test_limit_is_floored_at_one() -> None:
    assert db.clamp_list_limit(0) == 1
    assert db.clamp_list_limit(-5) == 1


def test_garbage_limit_falls_back_to_default() -> None:
    assert db.clamp_list_limit("banana") == min(db.DEFAULT_LIST_LIMIT, db.MAX_LIST_LIMIT)  # type: ignore[arg-type]


def test_offset_is_non_negative() -> None:
    assert db.clamp_offset(None) == 0
    assert db.clamp_offset(-3) == 0
    assert db.clamp_offset("nope") == 0  # type: ignore[arg-type]
    assert db.clamp_offset(7) == 7


def test_calls_default_is_tighter_than_the_flat_list_default() -> None:
    """Call rows carry full transcripts — they must not share the flat cap."""
    assert db.DEFAULT_CALLS_LIMIT <= db.DEFAULT_LIST_LIMIT


# ---------------------------------------------------------------------------
# The accessors actually honour it
# ---------------------------------------------------------------------------


def test_list_calls_honours_limit() -> None:
    assert len(db.list_calls(limit=1)) <= 1
    assert len(db.list_calls(limit=2)) <= 2


def test_list_calls_offset_pages_without_repeating() -> None:
    first = db.list_calls(limit=1, offset=0)
    if not first:
        pytest.skip("no interactions seeded")
    second = db.list_calls(limit=1, offset=1)
    if second:
        assert first[0]["id"] != second[0]["id"]


def test_list_calls_is_bounded_by_default() -> None:
    assert len(db.list_calls()) <= db.DEFAULT_CALLS_LIMIT


def test_list_customers_honours_limit() -> None:
    assert len(db.list_customers(limit=1)) <= 1


def test_list_customers_is_bounded_by_default() -> None:
    assert len(db.list_customers()) <= db.DEFAULT_LIST_LIMIT


def test_list_customers_offset_pages_without_repeating() -> None:
    first = db.list_customers(limit=1, offset=0)
    if not first:
        pytest.skip("no customers seeded")
    second = db.list_customers(limit=1, offset=1)
    if second:
        assert first[0]["id"] != second[0]["id"]


def test_get_customer_still_returns_the_single_row() -> None:
    """The paging branch must not apply to a by-id lookup."""
    rows = db.list_customers(limit=1)
    if not rows:
        pytest.skip("no customers seeded")
    found = db.get_customer(rows[0]["id"])
    assert found is not None
    assert found["id"] == rows[0]["id"]


# ---------------------------------------------------------------------------
# Tenant scoping
# ---------------------------------------------------------------------------


def _seed_foreign_tenant_interaction(conn, suffix: str) -> tuple[str, str]:
    """A complete interaction belonging to a tenant that is not ours.

    Returns ``(customer_id, interaction_id)``. Every column the schema requires
    is supplied — an insert that silently violated a CHECK would make these
    tests pass for the wrong reason.
    """
    tenant = f"other.tenant.{suffix}"
    customer_id = f"cust-other-{suffix}"
    bot_id = f"bot-other-{suffix}"
    interaction_id = f"INT-OTHER-{suffix.upper()}"

    conn.execute(
        text("INSERT INTO tenants (id, name) VALUES (:t, 'Other Bank')"), {"t": tenant}
    )
    conn.execute(
        text(
            "INSERT INTO bots (id, tenant_id, name, version) "
            "VALUES (:b, :t, 'Other Bot', '1.0')"
        ),
        {"b": bot_id, "t": tenant},
    )
    conn.execute(
        text(
            "INSERT INTO customers (id, tenant_id, name, phone_primary, risk) "
            "VALUES (:c, :t, 'Someone Else', '+91 90000 00001', 'low')"
        ),
        {"c": customer_id, "t": tenant},
    )
    conn.execute(
        text(
            "INSERT INTO interactions "
            "  (id, tenant_id, customer_id, channel, direction, handler_kind, "
            "   handler_bot_id, status, started_at) "
            "VALUES (:i, :t, :c, 'voice', 'outbound', 'bot', :b, 'completed', now())"
        ),
        {"i": interaction_id, "t": tenant, "c": customer_id, "b": bot_id},
    )
    return customer_id, interaction_id


def test_list_calls_excludes_another_tenants_interactions(db_tx) -> None:
    """The regression this locks shut: interactions were selected with no
    tenant predicate at all."""
    _customer_id, interaction_id = _seed_foreign_tenant_interaction(db_tx, "a")

    ids = {row["id"] for row in db.list_calls(limit=db.MAX_LIST_LIMIT)}
    assert interaction_id not in ids


def test_interaction_contracts_is_tenant_scoped(db_tx) -> None:
    customer_id, _interaction_id = _seed_foreign_tenant_interaction(db_tx, "b")

    # Even asked for that customer by id, the other tenant's rows stay invisible.
    rows = db._interaction_contracts(db_tx, customer_id=customer_id)
    assert rows == []


def test_interaction_contracts_has_no_unbounded_branch(db_tx) -> None:
    """limit=None must still page, because each row pulls a full transcript."""
    rows = db._interaction_contracts(db_tx)
    assert len(rows) <= db.DEFAULT_CALLS_LIMIT


# ---------------------------------------------------------------------------
# The accessors that grow with traffic all take a page
# ---------------------------------------------------------------------------

#: Accessors whose row count grows with customers, calls or knowledge-base size.
#: Deliberately not every list function in the module: `list_staff`,
#: `list_teams`, `list_products` and the TTS/persona catalogs are bounded by
#: headcount or by configuration, and paging them would add a control nobody
#: uses. The rule being enforced is "bounded by *traffic* must be paged", not
#: "everything must be paged".
PAGED_ACCESSORS = [
    "list_calls",
    "list_customers",
    "list_leads",
    "list_promises",
    "list_payment_plans",
    "list_disputes",
    "list_callbacks",
    "list_kb_documents",
    "list_export_jobs",
    "list_coaching_actions",
    "list_calibration_sessions",
    "list_kb_faqs",
    "list_kb_snapshots",
    "list_prompt_versions",
    "list_bot_deployments",
]

#: Accessors deliberately left unpaged, each with a stated reason. Listing them
#: is the point: "we checked and it is bounded by configuration" is a different
#: statement from "we did not get to it", and only the first one survives a
#: reviewer asking why.
UNPAGED_BY_DESIGN = {
    "list_staff": "bounded by headcount",
    "list_teams": "bounded by org structure",
    "list_products": "bounded by product catalog",
    "list_canned_responses": "authored templates",
    "list_redaction_rules": "one row per PII type",
    "list_routing_rules": "authored rules",
    "list_persona_presets": "authored presets",
    "list_tts_voices": "configured voice shortlist",
    "list_tts_price_tiers": "pricing bands",
    "list_sandbox_scenarios": "authored scenarios",
}


#: Routes that must honour ``?limit=``. Bounding the accessor is only half the
#: job — ``/kb/faqs`` and ``/prompt-versions`` both had a bounded accessor and a
#: route that never passed the parameter through, so they still returned every
#: row. That is invisible to a unit test of the accessor, which is why this one
#: goes through the real app.
PAGED_ROUTES = [
    "/customers",
    "/calls",
    "/leads",
    "/promises",
    "/payment-plans",
    "/disputes",
    "/callbacks",
    "/kb/documents",
    "/kb/faqs",
    "/prompt-versions",
    "/bot-deployments",
    "/export-jobs",
    "/coaching-actions",
    "/calibration-sessions",
    # Missed by pass 1: these three had no limit/offset at all — accessor or
    # route — so they were not "bounded but unwired", they were unbounded. Found
    # while closing the cross-tenant leaks in the same queries.
    "/consent",
    "/document-requests",
    "/work-items",
    # P3. A hold queue grows with the book, so it is paged from the start
    # rather than after someone notices.
    "/treatment/holds",
    "/treatment/cases",
]


@pytest.fixture()
def paged_client(monkeypatch):
    from fastapi.testclient import TestClient

    import actor_context
    import main as app_main

    monkeypatch.setenv("API_KEY", "bounds-test-key")
    monkeypatch.delenv("API_KEY_MAP", raising=False)
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("ALLOW_ACTOR_HEADER", "true")
    actor_context.reload_api_key_map()
    return TestClient(app_main.app)


@pytest.mark.parametrize("path", PAGED_ROUTES)
def test_route_honours_limit_end_to_end(paged_client, path: str) -> None:
    headers = {"X-API-Key": "bounds-test-key", "X-Actor-User-Id": "priya-nair"}
    res = paged_client.get(f"{path}?limit=1", headers=headers)
    assert res.status_code == 200, f"{path} -> {res.status_code} {res.text[:200]}"
    body = res.json()
    assert isinstance(body, list), f"{path} did not return a list"
    assert len(body) <= 1, (
        f"{path} ignored ?limit=1 and returned {len(body)} rows — the accessor "
        "is probably bounded but the route does not pass the parameter through"
    )


def test_unpaged_accessors_are_still_small() -> None:
    """A table we called configuration-bounded must actually be small.

    This is the check that turns the justification above from an assertion into
    a measurement — if one of these ever starts growing with traffic, it fails
    here rather than in production.
    """
    for name in UNPAGED_BY_DESIGN:
        fn = getattr(db, name, None)
        if fn is None:
            continue
        assert len(fn()) <= db.MAX_LIST_LIMIT, (
            f"{name} is not paged because it was assumed "
            f"{UNPAGED_BY_DESIGN[name]}, but it now returns more than "
            f"{db.MAX_LIST_LIMIT} rows — it needs a page"
        )


@pytest.mark.parametrize("name", PAGED_ACCESSORS)
def test_traffic_growing_accessor_accepts_a_page(name: str) -> None:
    import inspect

    fn = getattr(db, name)
    params = inspect.signature(fn).parameters
    assert "limit" in params, f"{name} has no limit parameter"
    assert "offset" in params, f"{name} has no offset parameter"


@pytest.mark.parametrize("name", PAGED_ACCESSORS)
def test_traffic_growing_accessor_is_bounded_by_default(name: str) -> None:
    """Calling with no arguments must not attempt an unbounded read."""
    rows = getattr(db, name)()
    assert len(rows) <= db.MAX_LIST_LIMIT


@pytest.mark.parametrize("name", PAGED_ACCESSORS)
def test_traffic_growing_accessor_honours_limit(name: str) -> None:
    assert len(getattr(db, name)(limit=1)) <= 1


def test_kb_chunks_are_paged() -> None:
    """The largest response the API could produce: every chunk's full text."""
    import inspect

    params = inspect.signature(db.list_kb_chunks).parameters
    assert "limit" in params and "offset" in params
    docs = db.list_kb_documents(limit=1)
    if not docs:
        pytest.skip("no kb documents seeded")
    assert len(db.list_kb_chunks(docs[0]["id"], limit=1)) <= 1


def test_customer_detail_children_are_bounded(db_tx) -> None:
    """A five-year-old account must render recent notes, not every note ever."""
    rows = db.list_customers(limit=1)
    if not rows:
        pytest.skip("no customers seeded")
    cid = rows[0]["id"]
    for helper in (
        db._promise_contracts,
        db._dispute_contracts,
        db._document_contracts,
        db._note_contracts,
    ):
        assert len(helper(db_tx, cid)) <= db.DEFAULT_DETAIL_LIMIT, helper.__name__
