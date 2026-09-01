"""Agent Studio → outbound runtime bindings.

Campaigns, treatment and the demo button used to ignore the card being
edited and dial ``DEFAULT_BOT_ID``. The inbound ANI lookup was computed and
then thrown away. These tests lock the joins that make the studio steer.
"""

from __future__ import annotations

import inspect
from pathlib import Path

from sqlalchemy import text

_BACKEND = Path(__file__).resolve().parents[1]
_HABIBI = _BACKEND.parent / "Habibi"


def test_resolve_outbound_bot_id_honours_explicit_and_decision() -> None:
    import mission

    assert mission.resolve_outbound_bot_id(explicit="card-from-studio") == "card-from-studio"
    assert (
        mission.resolve_outbound_bot_id(decision={"bot_id": "from-decision"}) == "from-decision"
    )


def test_resolve_outbound_bot_id_falls_back_to_default() -> None:
    import db
    import mission

    assert mission.resolve_outbound_bot_id() == db.DEFAULT_BOT_ID


def test_treatment_enact_resolves_the_bot(monkeypatch) -> None:
    import inspect

    from agent_core.treatment import enact

    src = inspect.getsource(enact._dial_bot)
    assert "resolve_outbound_bot_id" in src
    assert "DEFAULT_BOT_ID" not in src or "resolve_outbound_bot_id" in src


def test_demo_uses_resolved_bot() -> None:
    src = (_BACKEND / "main.py").read_text(encoding="utf-8")
    assert "def _demo_outbound_bot_id" in src
    assert "bot_id = _demo_outbound_bot_id()" in src
    assert "bot_id = str(db.DEFAULT_BOT_ID)" not in src


def test_campaign_create_persists_bot_id(db_tx) -> None:
    import campaigns
    import db as dbmod

    tenant = db_tx.execute(text("SELECT tenant_id FROM bots LIMIT 1")).scalar() or "hdfc.retail"
    bot = db_tx.execute(text("SELECT id FROM bots LIMIT 1")).scalar() or dbmod.DEFAULT_BOT_ID
    run = campaigns.create(
        db_tx,
        tenant_id=str(tenant),
        name="studio card run",
        objective="dpd_reminder",
        bot_id=str(bot),
    )
    stored = db_tx.execute(
        text("SELECT bot_id FROM campaign_runs WHERE id = :id"), {"id": run["id"]}
    ).scalar()
    assert stored == str(bot)


def test_campaign_start_refuses_when_outbound_switch_is_off() -> None:
    src = (_BACKEND / "main.py").read_text(encoding="utf-8")
    start = src.index("def set_campaign_status")
    chunk = src[start : start + 1800]
    assert "platform_switches.outbound_enabled" in chunk
    assert "outbound_disabled" in chunk


def test_inbound_ani_bind_uses_pstn_customer() -> None:
    from voice.persist import customer_id_for_bind

    assert (
        customer_id_for_bind(
            direction="inbound",
            pstn_customer={"customerId": "cust-susanth"},
        )
        == "cust-susanth"
    )
    assert (
        customer_id_for_bind(
            direction="outbound",
            twilio_params={"customer_id": "cust-dialled"},
        )
        == "cust-dialled"
    )
    assert customer_id_for_bind(direction="inbound") is None


def test_missions_prefer_the_draft_graph() -> None:
    src = (_BACKEND / "main.py").read_text(encoding="utf-8")
    start = src.index("def list_missions")
    chunk = src[start : start + 2500]
    assert "draftVersionId" in chunk
    assert "get_agent_studio_card" in chunk


def test_process_one_uses_the_run_bot_not_only_the_default() -> None:
    import campaigns

    src = inspect.getsource(campaigns.process_one)
    assert "run.get(\"bot_id\")" in src or "run.get('bot_id')" in src


def test_call_trace_joins_session_attempt_and_demo() -> None:
    from types import SimpleNamespace

    from voice.call_trace import session_fields

    session = SimpleNamespace(
        session_id="VS-4D8667B522",
        interaction_id="CL-392294B1EC",
        extra={
            "attempt_id": "CA-CAD227E47BED",
            "call_sid": "CAb9789064812789e710767257241c4484",
            "objective": "dpd_reminder",
            "twilio_params": {"demo": "1"},
        },
    )
    fields = session_fields(session)
    assert fields["session"] == "VS-4D8667B522"
    assert fields["attempt"] == "CA-CAD227E47BED"
    assert fields["sid"].startswith("CA")
    assert fields["interaction"] == "CL-392294B1EC"
    assert fields["objective"] == "dpd_reminder"
    assert fields["demo"] == 1


def test_call_trace_preview_strips_digit_runs() -> None:
    from voice.call_trace import preview

    assert preview("Yeah, last four is 2324.") == "Yeah, last four is ***."
    assert preview("") is None
    long = "A" * 100
    assert preview(long, limit=20).endswith("…")
    assert len(preview(long, limit=20)) == 20


def test_bot_traces_the_hops_the_demo_log_was_missing() -> None:
    src = (_BACKEND / "voice" / "bot.py").read_text(encoding="utf-8")
    assert "first.speech" in src
    assert "first.tts" in src
    assert "deadair.nudge" in src
    assert "call.ended" in src
    assert "loop.trip" in src
    assert "setup.amd" in src
    sink = (_BACKEND / "voice" / "crm_sink.py").read_text(encoding="utf-8")
    assert '"user.turn"' in sink
    assert '"bot.tts"' in sink
    assert '"critique"' in sink
    tools = (_BACKEND / "voice" / "tools.py").read_text(encoding="utf-8")
    assert '"tool.called"' in tools
    assert '"tool.result"' in tools
    assert '"flow.node"' in tools
    assert "_LOOP_LLM_BUDGET" in src
    assert "prewarm_llm_connection(force=True)" not in src
    assert "customer_id_for_bind" in src


def test_first_names_match_accepts_outbound_variants() -> None:
    from voice.names import first_names_match

    assert first_names_match("Yeah, Sushant here.", "Susanth")
    assert first_names_match("Susanth", "Sushant Kumar")
    assert not first_names_match("yes speaking", "Susanth")
    assert not first_names_match("Priya", "Susanth")


def test_demo_call_product_fixes_are_wired() -> None:
    """Source locks so the next demo cannot silently lose the VS-2E3096 fixes."""
    tools = (_BACKEND / "voice" / "tools.py").read_text(encoding="utf-8")
    kb = (_BACKEND / "agent_core" / "tools" / "kb.py").read_text(encoding="utf-8")
    natural = (_BACKEND / "voice" / "natural.py").read_text(encoding="utf-8")
    bot = (_BACKEND / "voice" / "bot.py").read_text(encoding="utf-8")
    flows = (_BACKEND / "voice" / "flows.py").read_text(encoding="utf-8")

    # The VS-2E3096 invariant: an empty retrieve is never reported as
    # confident, which is how a travel-insurance question got a fabricated
    # follow-up instead of a refusal. Was two statements guarding a numeric
    # gate; the gate is gone (measured at AUC 0.548 — a coin flip) and
    # emptiness is now the whole rule, so it reads as one expression.
    # Behaviour is covered directly by
    # test_kb_plan.py::test_empty_results_are_never_confident.
    assert "confident = bool(results)" in kb
    assert "query_looks_product(query)" in tools
    assert 'session.extra["upsell_blocked"] = reason' in tools
    assert 'blocked = session.extra.get("upsell_blocked")' in tools
    assert 'session.extra.pop("upsell_blocked", None)' in tools
    assert "first_names_match" in tools
    assert "AFTER the caller has spoken" in natural
    assert "first words of the call" in natural
    assert "outbound collections voice agent" in bot
    assert "garbled STT fragments" in bot
    assert "on_user_turn_stopped_rearm_idle" in bot
    assert "Never open with a tool acknowledgement" in flows
    assert "search_knowledge_base" in flows


def test_frontend_create_campaign_sends_bot_id() -> None:
    from pathlib import Path

    tab = _HABIBI / "src" / "components" / "prompt-studio" / "OutboundTab.tsx"
    text = tab.read_text(encoding="utf-8")
    assert "botId" in text
    assert "flow={flow}" in text or "flow }" in text or "flow," in text
    assert "agentCard: card, flow" in text
