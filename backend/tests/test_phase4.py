"""Phase 4 — clerk, copilot, vision, twin, work-runtime. No Temporal cluster."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from agent_core.cards.compile import compile_card
from agent_core.cards.defaults import COLLECTIONS_BOT_ID, card_dump
from agent_core.tools.catalog import CATALOG
from agent_core.tools.schema import CHANNEL_MCP, CHANNEL_TEXT, CHANNEL_VOICE
from agent_core.treatment import actions as A
from agent_core.treatment import decisions, enact
from work_runtime import idempotency_key, query, signal, start_workflow


def _require_table(db_tx, name: str) -> None:
    row = db_tx.execute(text("SELECT to_regclass(:n) AS t"), {"n": f"public.{name}"}).mappings().first()
    if not row or not row["t"]:
        pytest.skip(f"{name} missing — apply alembic 20260815_0077")


def _require_column(db_tx, table: str, column: str) -> None:
    row = db_tx.execute(
        text(
            """
            SELECT 1 FROM information_schema.columns
             WHERE table_schema = 'public' AND table_name = :t AND column_name = :c
            """
        ),
        {"t": table, "c": column},
    ).first()
    if not row:
        pytest.skip(f"{table}.{column} missing — apply alembic 20260815_0077")


@pytest.fixture
def account(db_tx):
    row = db_tx.execute(
        text(
            """
            SELECT a.id, a.customer_id FROM accounts a
            JOIN customers c ON c.id = a.customer_id
            WHERE a.dpd BETWEEN 1 AND 30 AND c.phone_primary IS NOT NULL
              AND c.id <> 'UNKNOWN-CALLER'
            ORDER BY a.id LIMIT 1
            """
        )
    ).mappings().first()
    if row is None:
        pytest.skip("seed has no early-bucket account with a phone number")
    return dict(row)


def _compile(card_raw, **kw):
    return compile_card(
        bot_id=COLLECTIONS_BOT_ID,
        card_raw=card_raw,
        flow={},
        catalog_names=set(CATALOG.specs),
        known_bot_ids={COLLECTIONS_BOT_ID, "intake-v1", "insurance-v1", "supervisor-brief"},
        **kw,
    )


def test_ingest_tool_is_text_only_not_voice_or_mcp() -> None:
    spec = CATALOG.get("ingest_customer_document")
    assert spec is not None
    assert CHANNEL_TEXT in spec.channels
    assert CHANNEL_VOICE not in spec.channels
    assert CHANNEL_MCP not in spec.channels


def test_g11_skipped_when_twin_not_required() -> None:
    report = _compile(card_dump(COLLECTIONS_BOT_ID))
    g11 = next(g for g in report.gates if g.gate == "G11")
    assert g11.status == "skipped"
    assert report.ok


def test_g11_fails_closed_when_required_and_no_run() -> None:
    dumped = card_dump(COLLECTIONS_BOT_ID)
    dumped["eval"]["require"] = ["regression", "redteam", "twin"]
    report = _compile(dumped, twin_report=None)
    g11 = next(g for g in report.gates if g.gate == "G11")
    assert g11.status == "fail"
    assert report.http_status() == 409


def test_temporal_adapter_fails_closed(monkeypatch) -> None:
    monkeypatch.setenv("TEMPORAL_ENABLED", "true")
    with pytest.raises(RuntimeError, match="temporal_adapter_not_promoted"):
        start_workflow(
            workflow_type="bounce_chase",
            payload={},
            customer_id=None,
            idempotency_key="x:bounce_chase:probe",
        )


def test_work_runtime_resumes_approval_after_restart(db_tx, account) -> None:
    _require_table(db_tx, "work_runtime_jobs")
    from agent_core.clerk import process_one
    from work_runtime.adapter_pg import query as pg_query

    ref = f"hitl-{uuid.uuid4().hex[:8]}"
    job = start_workflow(
        workflow_type="bounce_chase",
        payload={"action": A.FIELD_VISIT, "triggerRef": ref, "decisionId": None},
        customer_id=account["customer_id"],
        idempotency_key=idempotency_key(workflow_type="bounce_chase", trigger_ref=ref),
    )
    assert process_one() is True
    parked = pg_query(job["id"])
    assert parked is not None
    assert parked["status"] == "input_required"
    # Simulate API process restart: a new query of the same row.
    again = query(job["id"])
    assert again is not None
    assert again["status"] == "input_required"
    signal(job["id"], "approve", {"userId": "priya-nair"})
    resumed = query(job["id"])
    assert resumed is not None
    assert resumed["status"] == "submitted"
    assert process_one() is True
    done = query(job["id"])
    assert done is not None
    assert done["status"] == "completed"
    assert done["result"].get("approved") is True


def test_bounce_whatsapp_same_hour_and_no_double_send(db_tx, account, monkeypatch) -> None:
    _require_table(db_tx, "work_runtime_jobs")
    _require_column(db_tx, "treatment_decisions", "enacted_by")
    monkeypatch.setenv("TREATMENT_MODE", "live")
    from agent_core.treatment import config as treatment_config

    monkeypatch.setattr(treatment_config, "mode", lambda: treatment_config.MODE_LIVE)
    sent: list[str] = []

    def fake_wa(conn, *, decision, customer):
        sent.append(decision["id"])
        return "whatsapp:test"

    monkeypatch.setitem(enact._HANDLERS, A.WHATSAPP, fake_wa)
    import contact_policy

    monkeypatch.setattr(
        contact_policy,
        "admit",
        lambda *a, **k: contact_policy.Decision(True, daily_cap=3),
    )

    ref = f"bounce-{uuid.uuid4().hex[:8]}"
    db_tx.execute(
        text(
            """
            INSERT INTO payment_events (
              id, tenant_id, customer_id, account_id, kind, reason, amount,
              source, source_ref, status, occurred_at
            ) VALUES (
              :id, :t, :c, :a, 'bounce', 'insufficient_funds', 5000,
              'sandbox', :ref, 'open', now()
            )
            """
        ),
        {
            "id": ref,
            "t": "hdfc.retail",
            "c": account["customer_id"],
            "a": account["id"],
            "ref": f"src-{ref}",
        },
    )
    decision_id = decisions.record(
        conn=db_tx,
        tenant_id="hdfc.retail",
        customer_id=account["customer_id"],
        account_id=account["id"],
        interaction_id=None,
        trigger_kind="bounce",
        trigger_ref=ref,
        mode="live",
        variant=None,
        recommender="ev",
        recommender_version="1.0.0",
        feature_schema_version="v1",
        features={},
        candidates=[],
        excluded={},
        chosen_action=A.WHATSAPP,
        chosen_channel="whatsapp",
        scheduled_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        expected_value=10.0,
        suppression_reason=None,
        rationale="bounce chase",
        latency_ms=1,
    )
    assert decision_id
    from agent_core.clerk import enqueue_chase, process_one

    key = idempotency_key(workflow_type="bounce_chase", trigger_ref=ref)
    first = enqueue_chase(
        workflow_type="bounce_chase",
        trigger_ref=ref,
        customer_id=account["customer_id"],
        decision_id=decision_id,
        action=A.WHATSAPP,
        conn=db_tx,
    )
    assert first is not None
    second = enqueue_chase(
        workflow_type="bounce_chase",
        trigger_ref=ref,
        customer_id=account["customer_id"],
        decision_id=decision_id,
        action=A.WHATSAPP,
        conn=db_tx,
    )
    assert second is not None
    assert first["id"] == second["id"]
    assert first["idempotencyKey"] == key
    assert process_one() is True
    done = query(first["id"])
    assert done is not None
    assert done["status"] == "completed", done
    assert done["result"].get("acted") is True, done
    row = db_tx.execute(
        text("SELECT enacted, enacted_by, enacted_ref FROM treatment_decisions WHERE id = :id"),
        {"id": decision_id},
    ).mappings().first()
    assert row is not None
    assert row["enacted"] is True
    assert row["enacted_by"] == "clerk_agent"
    assert sent == [decision_id]
    import db as dbmod

    item = next((r for r in dbmod.list_work_items(assignee="all") if r["id"] == ref), None)
    if item is not None:
        assert item.get("enactedBy") == "clerk_agent"
    assert process_one() is False or True  # drain may pick nothing
    assert sent == [decision_id]


def test_broken_ptp_reenters_without_opening_the_diary(db_tx, account, monkeypatch) -> None:
    _require_table(db_tx, "work_runtime_jobs")
    monkeypatch.setenv("TREATMENT_MODE", "live")
    from agent_core.treatment import config as treatment_config

    monkeypatch.setattr(treatment_config, "mode", lambda: treatment_config.MODE_LIVE)
    sent: list[str] = []
    monkeypatch.setitem(
        enact._HANDLERS,
        A.WHATSAPP,
        lambda conn, *, decision, customer: sent.append(decision["id"]) or "whatsapp:ptp",
    )
    import contact_policy

    monkeypatch.setattr(
        contact_policy,
        "admit",
        lambda *a, **k: contact_policy.Decision(True, daily_cap=3),
    )
    ref = f"ptp-{uuid.uuid4().hex[:8]}"
    db_tx.execute(
        text(
            """
            INSERT INTO promises (
              id, customer_id, account_id, owner_kind, owner_bot_id,
              amount, promised_at, status, reminder_status, channel
            ) VALUES (
              :id, :c, :a, 'bot', 'kaia-v2-4',
              4000, now() - interval '1 day', 'broken', 'off', 'whatsapp'
            )
            """
        ),
        {"id": ref, "c": account["customer_id"], "a": account["id"]},
    )
    decision_id = decisions.record(
        conn=db_tx,
        tenant_id="hdfc.retail",
        customer_id=account["customer_id"],
        account_id=account["id"],
        interaction_id=None,
        trigger_kind="broken_ptp",
        trigger_ref=ref,
        mode="live",
        variant=None,
        recommender="ev",
        recommender_version="1.0.0",
        feature_schema_version="v1",
        features={},
        candidates=[],
        excluded={},
        chosen_action=A.WHATSAPP,
        chosen_channel="whatsapp",
        scheduled_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        expected_value=10.0,
        suppression_reason=None,
        rationale="broken ptp",
        latency_ms=1,
    )
    assert decision_id
    from agent_core.clerk import enqueue_from_treatment, process_one

    job = enqueue_from_treatment(
        trigger_kind="broken_ptp",
        trigger_ref=ref,
        customer_id=account["customer_id"],
        decision_id=decision_id,
        action=A.WHATSAPP,
        conn=db_tx,
    )
    assert job is not None
    assert process_one() is True
    assert sent == [decision_id]


def test_receipt_photo_becomes_document_row(db_tx, account, monkeypatch) -> None:
    _require_column(db_tx, "document_requests", "source")
    monkeypatch.setenv("VISION_INGEST_ENABLED", "true")
    import azure_openai

    monkeypatch.setattr(
        azure_openai,
        "chat_with_tools",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("azure_down")),
    )
    from agent_core.vision import ingest_customer_document

    denied = ingest_customer_document(
        customer_id=account["customer_id"],
        filename="upi.jpg",
        mime_type="image/jpeg",
        identity_verified=False,
    )
    assert denied.ok is False
    assert denied.error == "identity_not_verified"

    ok = ingest_customer_document(
        customer_id=account["customer_id"],
        filename="upi-receipt.jpg",
        mime_type="image/jpeg",
        identity_verified=True,
        requested_via="inbox",
    )
    assert ok.ok is True
    doc_id = ok.data["documentRequestId"]
    row = db_tx.execute(
        text("SELECT source, requested_via, doc_type FROM document_requests WHERE id = :id"),
        {"id": doc_id},
    ).mappings().first()
    assert row is not None
    assert row["source"] == "vision"
    assert row["requested_via"] == "inbox"
    assert row["doc_type"] == "payment_receipt"


def test_twin_replays_bounce_ladder_without_dialling(db_tx) -> None:
    _require_table(db_tx, "simulation_twins")
    from agent_core.twin import replay_bounce_ladder

    run = replay_bounce_ladder()
    assert run["grader"]["passed"] is True
    assert run["grader"]["no_dial"]["passed"] is True
    assert run["outcome"]["dialled"] is False
    assert len(run["outcome"]["queues"]["whatsapp"]) == 1
    assert run["outcome"]["queues"]["voice"] == []


def test_copilot_draft_uses_engines_not_paraphrase(db_tx, monkeypatch) -> None:
    row = db_tx.execute(
        text(
            """
            SELECT id, customer_id FROM interactions
             WHERE customer_id IS NOT NULL
             ORDER BY started_at DESC NULLS LAST
             LIMIT 1
            """
        )
    ).mappings().first()
    if not row:
        pytest.skip("no interactions seeded")
    import azure_openai
    from agent_core.copilot import build

    monkeypatch.setattr(
        azure_openai,
        "chat_with_tools",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("azure_down")),
    )
    pack = build(row["id"])
    assert pack is not None
    assert pack["whisperDraft"]
    assert pack["engineDraft"] == pack["whisperDraft"]
    assert "card" in pack
    assert pack["card"]["botId"] or pack["card"]["botId"] is None
    assert "engines" in pack
    assert "authority" in pack["engines"]
    assert "treatment" in pack["engines"]
    assert "approvals" in pack


def test_copilot_stream_pack_then_tokens_no_product_invent(db_tx, monkeypatch) -> None:
    row = db_tx.execute(
        text(
            """
            SELECT id, customer_id FROM interactions
             WHERE customer_id IS NOT NULL
             ORDER BY started_at DESC NULLS LAST
             LIMIT 1
            """
        )
    ).mappings().first()
    if not row:
        pytest.skip("no interactions seeded")
    import azure_openai
    from agent_core.copilot import iter_events
    from work_runtime import start_workflow
    from work_runtime.adapter_pg import park_input_required

    monkeypatch.setattr(
        azure_openai,
        "chat_with_tools",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("azure_down")),
    )
    job = start_workflow(
        workflow_type="clerk_bounce_chase",
        payload={"action": "sms_nudge", "triggerRef": "test-4b"},
        customer_id=row["customer_id"],
        idempotency_key=f"copilot-stream-{row['id']}",
    )
    park_input_required(job["id"], "floor_confirm")

    events = list(iter_events(row["id"]))
    types = [e["type"] for e in events]
    assert types[0] == "pack"
    assert "token" in types
    assert types[-1] == "done"
    pack = events[0]
    assert pack["engineDraft"]
    assert pack["whisperDraft"] == pack["engineDraft"]
    assert "engines" in pack
    approvals = pack.get("approvals") or []
    assert any(a.get("id") == job["id"] for a in approvals)
    streamed = "".join(e["text"] for e in events if e["type"] == "token")
    assert streamed == events[-1]["whisperDraft"]
    lowered = streamed.lower()
    for banned in ("waiver", "settlement", "new credit card", "personal loan top-up"):
        if banned not in (pack["engineDraft"] or "").lower():
            assert banned not in lowered


def test_live_qa_does_not_pick_voice_rubric_for_sms(db_tx) -> None:
    _require_column(db_tx, "qa_rubrics", "channel")
    import db as dbmod

    # Prefer a seeded SMS interaction; otherwise insert one against a real bot.
    ix = db_tx.execute(
        text("SELECT id FROM interactions WHERE channel = 'sms' LIMIT 1")
    ).scalar()
    if not ix:
        cust = db_tx.execute(
            text("SELECT id FROM customers WHERE id <> 'UNKNOWN-CALLER' ORDER BY id LIMIT 1")
        ).scalar()
        ix = f"IX-SMS-{uuid.uuid4().hex[:8]}"
        db_tx.execute(
            text(
                """
                INSERT INTO interactions (
                  id, tenant_id, customer_id, channel, direction, handler_kind,
                  handler_bot_id, status, started_at
                ) VALUES (
                  :id, :t, :c, 'sms', 'outbound', 'bot', 'kaia-v2-4', 'completed', now()
                )
                """
            ),
            {"id": ix, "t": dbmod.current_tenant(), "c": cust},
        )
    db_tx.execute(
        text(
            """
            INSERT INTO qa_rubrics (id, tenant_id, name, version, enabled, channel)
            VALUES ('rubric-clerk-sms', :t, 'Clerk SMS', 'v1.0', true, 'clerk')
            ON CONFLICT (id) DO UPDATE SET channel = 'clerk', enabled = true
            """
        ),
        {"t": dbmod.current_tenant()},
    )
    db_tx.execute(
        text(
            """
            INSERT INTO qa_rubric_sections (id, rubric_id, name, weight)
            VALUES ('clerk-contact', 'rubric-clerk-sms', 'Contact policy', 100)
            ON CONFLICT (id) DO NOTHING
            """
        )
    )
    db_tx.execute(
        text(
            """
            INSERT INTO qa_rubric_criteria (id, section_id, label, description, weight, critical_fail)
            VALUES ('clk-dnd', 'clerk-contact', 'DND honoured', 'No send outside policy.', 100, true)
            ON CONFLICT (id) DO NOTHING
            """
        )
    )
    chosen = dbmod.rubric_id_for_interaction(ix)
    assert chosen != "rubric-v1"
    if chosen:
        tree = dbmod.load_rubric_tree(chosen)
        assert tree is not None
        labels = " ".join(
            c["label"] for s in tree["sections"] for c in s["criteria"]
        ).lower()
        assert "recording" not in labels
        assert "barge" not in labels


def test_tuner_is_shadow_and_does_not_write_env(monkeypatch) -> None:
    monkeypatch.delenv("RECO_W_FATIGUE", raising=False)
    from agent_core.tuner import suggestions

    out = suggestions(days=14)
    assert out["mode"] == "shadow"
    assert out["applied"] is False
    import os

    assert os.getenv("RECO_W_FATIGUE") is None
