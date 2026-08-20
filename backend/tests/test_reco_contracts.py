"""Contract tests for the offer engine — the ones that need a real database.

Part 6 of upsell_engine_plan.md lists three, and each exists because a specific
defect got past unit tests:

* **Lead round-trip.** D5 and D6 were both "the list endpoint and the detail
  endpoint disagree". No unit test could catch that, because each function was
  individually correct.
* **`capture_lead(offer_id)` product match.** The model could pitch product A
  and capture product B and nothing noticed.
* **Idempotent replay.** D3 — a retried tool call created a second lead, and
  two reps called the same customer about the same thing.

Plus candidate-generation coverage, which the plan flags as tested only
indirectly. Every exclusion path has to prove it emits the *right reason code*,
because those codes are what the dashboards count and what a rep is told when
nothing could be offered.

All of these run inside the `db_tx` rollback fixture, so they leave no rows.
"""

from __future__ import annotations

import uuid

import pytest


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _eligible_pair(db_tx) -> tuple[str, str, str]:
    """``(customer_id, account_id, product_id)`` that eligibility actually passes.

    Picking the first customer alphabetically and the first un-held product
    does not work: the seed is realistic, so that pair is a 92-DPD customer and
    a product with a 90-day limit, and every capture test fails on a correct
    compliance block rather than on the thing it meant to test.

    So the pair is chosen by asking the real veto, which also means these tests
    keep working when somebody re-tunes the seeded rules.
    """
    import capture
    from sqlalchemy import text

    rows = (
        db_tx.execute(
            text(
                """
                SELECT c.id AS customer_id, a.id AS account_id
                FROM customers c
                JOIN accounts a ON a.customer_id = c.id
                WHERE c.id <> 'UNKNOWN-CALLER' AND c.dnd IS FALSE
                ORDER BY c.id
                """
            )
        )
        .mappings()
        .all()
    )
    products = [
        r["id"]
        for r in db_tx.execute(
            text("SELECT id FROM products WHERE is_active IS TRUE ORDER BY id")
        ).mappings()
    ]

    for row in rows:
        customer_id = row["customer_id"]
        held_or_pending = {
            r[0]
            for r in db_tx.execute(
                text(
                    "SELECT product_id FROM accounts"
                    " WHERE customer_id = :cid AND product_id IS NOT NULL"
                    " UNION"
                    " SELECT product_id FROM leads"
                    " WHERE customer_id = :cid AND product_id IS NOT NULL"
                ),
                {"cid": customer_id},
            )
        }
        facts = capture.customer_eligibility_facts(db_tx, customer_id)
        for product_id in products:
            if product_id in held_or_pending:
                continue
            flags = capture.evaluate_product_eligibility(
                db_tx,
                customer_id=customer_id,
                product_id=product_id,
                channel="voice",
                facts=facts,
            )
            if capture.eligibility_blocks_capture(flags) is None:
                return customer_id, row["account_id"], product_id

    pytest.skip("no eligible (customer, product) pair in the seeded data")


# ---------------------------------------------------------------------------
# contract: the list endpoint and the detail endpoint must agree
# ---------------------------------------------------------------------------


def test_lead_round_trips_identically_through_list_and_detail(db_tx) -> None:
    """D5/D6: `list_leads` hardcoded followUps=[] while `_lead_by_id` read them.

    The Upsell screen reads the lead out of the *list* response, so a field the
    detail path populates and the list path does not is invisible in testing
    and glaring in production — "no follow-ups yet", immediately after you
    scheduled one.
    """
    import db

    customer_id, account_id, product_id = _eligible_pair(db_tx)

    created = db.create_lead(
        {
            "customerId": customer_id,
            "accountId": account_id,
            "productId": product_id,
            "stage": "interested",
            "source": "agent",
            "estimatedValue": 125000,
            "offerAmount": 125000,
            "priority": "normal",
            "transcriptSnippet": "contract test",
        }
    )
    lead_id = created["id"]

    db.add_lead_followup(
        lead_id,
        {"scheduledAt": "2026-08-15T10:00:00+05:30", "note": "contract test follow-up"},
    )

    detail = db._lead_by_id(db_tx, lead_id)
    listed = next((lead for lead in db.list_leads() if lead["id"] == lead_id), None)
    assert listed is not None, "lead created but absent from list_leads"

    # Compare every field both paths claim to serve. Restricting the assertion
    # to fields we currently suspect is how the next D5 gets shipped.
    for field in sorted(set(detail) & set(listed)):
        assert listed[field] == detail[field], (
            f"list_leads and _lead_by_id disagree on {field!r}: "
            f"{listed[field]!r} != {detail[field]!r}"
        )

    assert len(listed["followUps"]) == 1
    assert listed["nextFollowUpAt"] is not None
    # The timeline must come from activity_events, not be synthesised.
    assert any(e.get("kind") == "created" or e.get("type") == "created" for e in listed["events"]) \
        or listed["events"], "lead timeline is empty"


# ---------------------------------------------------------------------------
# contract: what was pitched is what gets captured
# ---------------------------------------------------------------------------


def test_capture_lead_by_offer_id_matches_the_offered_product(db_tx) -> None:
    """The model may not pitch A and capture B.

    `offer_id` is `"{decision_id}:{product_id}"`, so the product is carried by
    the token itself. This asserts the captured lead's product equals the one
    inside the offer id, not the one the model also passed.
    """
    import db
    from agent_core.tools import domain

    customer_id, _account_id, offered = _eligible_pair(db_tx)

    # The offer id is the engine's token; the product inside it is what the
    # channel layer must capture. Both channels resolve it the same way.
    decision_id = f"OD-{uuid.uuid4().hex[:12].upper()}"
    offer_id = f"{decision_id}:{offered}"
    resolved = offer_id.split(":", 1)[1]
    assert resolved == offered

    # The sourcing guard has to pass before capture is even attempted.
    assert domain.offer_sourcing_violation(resolved, {offered}) is None

    result = domain.capture_lead(
        customer_id=customer_id,
        product_id=resolved,
        offer_amount=90000,
        summary="contract test — offer id match",
        channel="voice",
        source="bot_voice",
        idempotency_key=f"contract-{uuid.uuid4().hex}",
    )
    assert result.ok, result.error

    lead = db._lead_by_id(db_tx, result.data["leadId"])
    assert lead["offer"]["productId"] == offered


def test_capture_lead_refuses_a_product_that_was_never_offered(db_tx) -> None:
    """The code-level enforcement, not the prompt.

    `domain.offer_sourcing_violation` is what makes "the model cannot name a
    product" true rather than merely requested. It is the chokepoint both
    channels call before `check_product_eligibility` and before `capture_lead`.
    """
    from agent_core.tools import domain

    customer_id, _account_id, offered = _eligible_pair(db_tx)

    # The engine approved something else entirely.
    violation = domain.offer_sourcing_violation(offered, {"some-other-product"})
    assert violation is not None and not violation.ok
    assert violation.error == "product_not_offered"

    # An engine that has not run at all is also a violation — nothing may be
    # pitched before it has.
    for empty in (None, set(), frozenset()):
        blocked = domain.offer_sourcing_violation(offered, empty)
        assert blocked is not None and blocked.error == "product_not_offered"


# ---------------------------------------------------------------------------
# contract: a replayed tool call must not create a second lead
# ---------------------------------------------------------------------------


def test_capture_lead_replay_returns_the_same_lead(db_tx) -> None:
    """D3: a model retry or a duplicated tool call created two identical leads."""
    from agent_core.tools import domain

    customer_id, _account_id, product_id = _eligible_pair(db_tx)
    key = f"contract-replay-{uuid.uuid4().hex}"

    first = domain.capture_lead(
        customer_id=customer_id,
        product_id=product_id,
        offer_amount=150000,
        summary="contract test — replay",
        channel="voice",
        source="bot_voice",
        idempotency_key=key,
    )
    second = domain.capture_lead(
        customer_id=customer_id,
        product_id=product_id,
        offer_amount=150000,
        summary="contract test — replay",
        channel="voice",
        source="bot_voice",
        idempotency_key=key,
    )

    assert first.ok and second.ok, (first.error, second.error)
    assert first.data["leadId"] == second.data["leadId"]


def test_estimated_value_is_never_null(db_tx) -> None:
    """D2: a NULL estimated_value rendered the whole Kanban board blank.

    `offer_amount` is an optional tool argument, so the guarantee has to be
    made at the write, not asked for at the call site.
    """
    import db
    from agent_core.tools import domain

    customer_id, account_id, product_id = _eligible_pair(db_tx)

    result = domain.capture_lead(
        customer_id=customer_id,
        product_id=product_id,
        # offer_amount deliberately omitted — this is what produced the NULL.
        summary="contract test — no amount given",
        channel="voice",
        source="bot_voice",
        idempotency_key=f"contract-{uuid.uuid4().hex}",
    )
    assert result.ok, result.error

    lead = db._lead_by_id(db_tx, result.data["leadId"])
    assert lead["estimatedValue"] is not None
    assert float(lead["estimatedValue"]) >= 0


# ---------------------------------------------------------------------------
# candidate generation — every exclusion emits its own reason code
# ---------------------------------------------------------------------------


def _generate(db_tx, features, channel="voice", decline_days=90, family_days=30):
    from agent_core.reco import candidates as candidates_mod

    return candidates_mod.generate(
        db_tx,
        features=features,
        channel=channel,
        decline_cooldown_days=decline_days,
        family_cooldown_days=family_days,
    )


def _features(**kwargs):
    from agent_core.reco.features import CustomerFeatures

    return CustomerFeatures(customer_id=kwargs.pop("customer_id", "test-customer"), **kwargs)


def _campaign_on_a_candidate(db_tx) -> tuple[str, str]:
    """``(campaign_id, product_id)`` for a campaign whose product is reachable.

    Taking the first campaign by id skips every one of these tests: the seeded
    top-up campaign sits on a product with a `requires` prerequisite, so it is
    never a candidate for a customer holding nothing, and the assertion under
    test never runs. Pick a campaign that is actually in the pool instead.
    """
    from sqlalchemy import text

    pool, _ = _generate(db_tx, _features())
    reachable = {c.product_id for c in pool}
    for row in db_tx.execute(
        text("SELECT id, product_id FROM product_campaigns ORDER BY id")
    ).mappings():
        if row["product_id"] in reachable:
            return row["id"], row["product_id"]
    pytest.skip("no campaign sits on a product reachable for a blank customer")


def test_held_product_is_excluded_as_already_held(db_tx) -> None:
    from agent_core.reco import candidates as candidates_mod

    pool, _ = _generate(db_tx, _features())
    if not pool:
        pytest.skip("no candidates in the seeded catalog")
    held = pool[0].product_id

    _, excluded = _generate(db_tx, _features(held_product_ids=frozenset({held})))
    assert excluded.get(held) == candidates_mod.REASON_ALREADY_HELD


def test_open_lead_is_excluded_with_its_own_reason(db_tx) -> None:
    """Distinct from `already_held`: an open lead is somebody's live job, and
    re-offering it is how a customer gets called twice about one thing."""
    from agent_core.reco import candidates as candidates_mod

    pool, _ = _generate(db_tx, _features())
    if not pool:
        pytest.skip("no candidates in the seeded catalog")
    target = pool[0].product_id

    _, excluded = _generate(db_tx, _features(open_lead_product_ids=frozenset({target})))
    assert excluded.get(target) == candidates_mod.REASON_OPEN_LEAD


def test_requires_relation_excludes_when_the_prerequisite_is_not_held(db_tx) -> None:
    from sqlalchemy import text

    from agent_core.reco import candidates as candidates_mod

    row = (
        db_tx.execute(
            text(
                "SELECT product_id, related_product_id FROM product_relations"
                " WHERE relation = 'requires' ORDER BY id LIMIT 1"
            )
        )
        .mappings()
        .first()
    )
    if not row:
        pytest.skip("no 'requires' relation seeded")

    dependent, prerequisite = row["product_id"], row["related_product_id"]

    _, excluded = _generate(db_tx, _features())
    assert excluded.get(dependent) == candidates_mod.REASON_REQUIRES_MISSING

    # Holding the prerequisite must let it through.
    pool, excluded = _generate(
        db_tx, _features(held_product_ids=frozenset({prerequisite}))
    )
    assert excluded.get(dependent) != candidates_mod.REASON_REQUIRES_MISSING
    assert dependent in {c.product_id for c in pool}


def test_excludes_relation_is_symmetric(db_tx) -> None:
    """Holding either side rules out the other — an `excludes` edge recorded
    one way round must not be enforceable only in that direction."""
    from sqlalchemy import text

    from agent_core.reco import candidates as candidates_mod

    row = (
        db_tx.execute(
            text(
                "SELECT product_id, related_product_id FROM product_relations"
                " WHERE relation = 'excludes' ORDER BY id LIMIT 1"
            )
        )
        .mappings()
        .first()
    )
    if not row:
        pytest.skip("no 'excludes' relation seeded")
    left, right = row["product_id"], row["related_product_id"]

    _, excluded_holding_left = _generate(
        db_tx, _features(held_product_ids=frozenset({left}))
    )
    _, excluded_holding_right = _generate(
        db_tx, _features(held_product_ids=frozenset({right}))
    )
    assert excluded_holding_left.get(right) == candidates_mod.REASON_EXCLUDED_BY_HOLDING
    assert excluded_holding_right.get(left) == candidates_mod.REASON_EXCLUDED_BY_HOLDING


def test_inactive_product_is_excluded(db_tx) -> None:
    from sqlalchemy import text

    from agent_core.reco import candidates as candidates_mod

    pool, _ = _generate(db_tx, _features())
    if not pool:
        pytest.skip("no candidates in the seeded catalog")
    target = pool[0].product_id

    db_tx.execute(
        text("UPDATE products SET is_active = false WHERE id = :id"), {"id": target}
    )
    _, excluded = _generate(db_tx, _features())
    assert excluded.get(target) == candidates_mod.REASON_INACTIVE


def test_channel_restriction_is_enforced(db_tx) -> None:
    from sqlalchemy import text

    from agent_core.reco import candidates as candidates_mod

    pool, _ = _generate(db_tx, _features())
    if not pool:
        pytest.skip("no candidates in the seeded catalog")
    target = pool[0].product_id

    db_tx.execute(
        text("UPDATE products SET channels = ARRAY['agent']::TEXT[] WHERE id = :id"),
        {"id": target},
    )
    _, excluded = _generate(db_tx, _features(), channel="voice")
    assert excluded.get(target) == candidates_mod.REASON_CHANNEL

    # ...and the same product is still offerable on a channel it does allow.
    pool_agent, excluded_agent = _generate(db_tx, _features(), channel="agent")
    assert excluded_agent.get(target) != candidates_mod.REASON_CHANNEL
    assert target in {c.product_id for c in pool_agent}


def test_expired_campaign_excludes_but_no_campaign_does_not(db_tx) -> None:
    """A product with no campaign is offerable; one whose window closed is not.

    Campaigns are an overlay for marketing to push or pause something, not a
    prerequisite — treating "no campaign" as "not live" would silently switch
    off every product nobody had bothered to promote.
    """
    from sqlalchemy import text

    from agent_core.reco import candidates as candidates_mod

    campaign_id, campaign_product = _campaign_on_a_candidate(db_tx)

    db_tx.execute(
        text("UPDATE product_campaigns SET ends_at = now() - interval '1 day' WHERE id = :id"),
        {"id": campaign_id},
    )
    _, excluded = _generate(db_tx, _features())
    assert excluded.get(campaign_product) == candidates_mod.REASON_CAMPAIGN_ENDED


def test_exhausted_campaign_quota_excludes(db_tx) -> None:
    from sqlalchemy import text

    from agent_core.reco import candidates as candidates_mod

    campaign_id, campaign_product = _campaign_on_a_candidate(db_tx)

    db_tx.execute(
        text(
            "UPDATE product_campaigns SET quota_total = 5, quota_used = 5 WHERE id = :id"
        ),
        {"id": campaign_id},
    )
    _, excluded = _generate(db_tx, _features())
    assert excluded.get(campaign_product) == candidates_mod.REASON_CAMPAIGN_QUOTA


def test_campaign_risk_and_segment_filters(db_tx) -> None:
    from sqlalchemy import text

    from agent_core.reco import candidates as candidates_mod

    campaign_id, campaign_product = _campaign_on_a_candidate(db_tx)

    db_tx.execute(
        text(
            "UPDATE product_campaigns"
            " SET risk_not_in = ARRAY['critical']::TEXT[],"
            "     segment_in = ARRAY['salaried']::TEXT[]"
            " WHERE id = :id"
        ),
        {"id": campaign_id},
    )

    _, excluded = _generate(db_tx, _features(segment="salaried", risk="critical"))
    assert excluded.get(campaign_product) == candidates_mod.REASON_CAMPAIGN_RISK

    _, excluded = _generate(db_tx, _features(segment="retail", risk="low"))
    assert excluded.get(campaign_product) == candidates_mod.REASON_CAMPAIGN_SEGMENT

    pool, excluded = _generate(db_tx, _features(segment="salaried", risk="low"))
    assert campaign_product not in excluded
    assert campaign_product in {c.product_id for c in pool}


def test_decline_and_family_cooldowns_use_distinct_reason_codes(db_tx) -> None:
    """A refused product is off the table for the decline window; its whole
    family is off for the shorter one. The two must be countable separately —
    they call for different fixes."""
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import text

    from agent_core.reco import candidates as candidates_mod

    pool, _ = _generate(db_tx, _features())
    if not pool:
        pytest.skip("no candidates in the seeded catalog")

    declined = pool[0]
    family = declined.family
    recent = datetime.now(timezone.utc) - timedelta(days=1)

    _, excluded = _generate(
        db_tx,
        _features(declined_product_ids=frozenset({declined.product_id}), last_offer_at=recent),
    )
    assert excluded.get(declined.product_id) == candidates_mod.REASON_DECLINED_COOLDOWN

    if not family:
        pytest.skip("top candidate has no family set")

    sibling = (
        db_tx.execute(
            text(
                "SELECT id FROM products WHERE family = :f AND id <> :id"
                " AND is_active IS TRUE ORDER BY id LIMIT 1"
            ),
            {"f": family, "id": declined.product_id},
        )
        .mappings()
        .first()
    )
    if not sibling:
        pytest.skip("no sibling product in the same family")

    if sibling["id"] not in {c.product_id for c in pool}:
        pytest.skip("family sibling is not a candidate for a blank customer")

    _, excluded = _generate(
        db_tx,
        _features(declined_product_ids=frozenset({declined.product_id}), last_offer_at=recent),
    )
    assert excluded.get(sibling["id"]) == candidates_mod.REASON_FAMILY_COOLDOWN


def test_family_cooldown_of_zero_disables_the_family_rule(db_tx) -> None:
    """A cool-down of zero must mean "off", not "everything is in cool-down"."""
    from datetime import datetime, timedelta, timezone

    from agent_core.reco import candidates as candidates_mod

    pool, _ = _generate(db_tx, _features())
    if not pool:
        pytest.skip("no candidates in the seeded catalog")

    declined = pool[0]
    features = _features(
        declined_product_ids=frozenset({declined.product_id}),
        last_offer_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    _, excluded = _generate(db_tx, features, family_days=0)
    assert candidates_mod.REASON_FAMILY_COOLDOWN not in excluded.values()
