"""The living offer policy — one snapshot every screen reads."""

from __future__ import annotations

from sqlalchemy import text


def test_snapshot_open_lead_is_the_job(db_tx) -> None:
    """An open lead outranks a missing decision — the rep already has work."""
    import db
    from agent_core.reco import policy

    row = (
        db_tx.execute(
            text(
                "SELECT customer_id FROM leads"
                " WHERE stage = ANY(:stages) AND product_id IS NOT NULL"
                " LIMIT 1"
            ),
            {"stages": list(db.OPEN_LEAD_STAGES)},
        )
        .mappings()
        .first()
    )
    assert row is not None
    snap = policy.snapshot(
        db_tx, customer_id=row["customer_id"], tenant_id=db.current_tenant()
    )
    assert snap["status"] == "open_lead"
    assert snap["leadId"]
    assert snap["productId"]


def test_snapshot_suppressed_when_no_open_lead(db_tx) -> None:
    import db
    from agent_core.reco import policy

    row = (
        db_tx.execute(
            text(
                """
                SELECT c.id
                FROM customers c
                WHERE c.dnd IS FALSE
                  AND NOT EXISTS (
                    SELECT 1 FROM leads l
                    WHERE l.customer_id = c.id AND l.stage = ANY(:stages)
                  )
                ORDER BY c.id
                LIMIT 1
                """
            ),
            {"stages": list(db.OPEN_LEAD_STAGES)},
        )
        .mappings()
        .first()
    )
    assert row is not None
    cid = row["id"]
    db_tx.execute(
        text(
            """
            INSERT INTO offer_decisions (
              id, tenant_id, customer_id, channel, mode,
              recommender, recommender_version, feature_schema_version,
              features, candidates, excluded, suppression_reason, presented
            ) VALUES (
              :id, :tenant, :cid, 'voice', 'live',
              'rule', '1.0.0', 'v1',
              '{}'::jsonb, '[]'::jsonb, '{}'::jsonb, 'hardship_stated', false
            )
            """
        ),
        {"id": "OD-TESTPOLICY01", "tenant": db.current_tenant(), "cid": cid},
    )
    snap = policy.snapshot(db_tx, customer_id=cid, tenant_id=db.current_tenant())
    assert snap["status"] == "suppressed"
    assert snap["suppressionReason"] == "hardship_stated"
    assert "Hardship" in (snap["suppressionLabel"] or "")


def test_insights_include_offer_nba_for_open_lead(db_tx) -> None:
    import db
    from customer_insights import derive_insights
    from agent_core.reco import policy

    row = (
        db_tx.execute(
            text(
                "SELECT customer_id FROM leads"
                " WHERE stage = ANY(:stages) AND product_id IS NOT NULL"
                " LIMIT 1"
            ),
            {"stages": list(db.OPEN_LEAD_STAGES)},
        )
        .mappings()
        .first()
    )
    customer = db.get_customer(row["customer_id"])
    assert customer is not None
    snap = policy.snapshot(
        db_tx, customer_id=row["customer_id"], tenant_id=db.current_tenant()
    )
    insights = derive_insights(customer, offer_policy=snap)
    assert insights["offerPolicy"]["status"] == "open_lead"
    offer_items = [i for i in insights["nba"] if i.get("action") == "offer"]
    assert offer_items
    assert offer_items[0]["leadId"] == snap["leadId"]
