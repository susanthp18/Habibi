"""Agent Studio → outbound runtime bindings.

Campaigns, treatment and the demo button used to ignore the card being
edited and dial ``DEFAULT_BOT_ID``. The inbound ANI lookup was computed and
then thrown away. These tests lock the joins that make the studio steer.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
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
    src = (_BACKEND / "routers" / "outbound.py").read_text(encoding="utf-8")
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
    src = (_BACKEND / "routers" / "outbound.py").read_text(encoding="utf-8")
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
    src = (_BACKEND / "routers" / "outbound.py").read_text(encoding="utf-8")
    start = src.index("def list_missions")
    chunk = src[start : start + 2500]
    assert "draftVersionId" in chunk
    assert "get_agent_studio_card" in chunk


IST = ZoneInfo("Asia/Kolkata")


class _Dialler:
    """Stands in for the carrier. ``process_one`` must never reach Twilio here."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, engine, attempt, *, to_phone, custom=None):
        self.calls.append({"attempt": attempt, "to": to_phone})
        return {"placed": True, "state": "dialing", "attemptId": attempt["id"]}


def _noon_today() -> datetime:
    d = datetime.now(IST).date()
    if d.isoweekday() == 7:
        d = d - timedelta(days=1)
    return datetime(d.year, d.month, d.day, 12, 0, tzinfo=IST)


def _pause_running_campaigns(conn) -> None:
    import campaigns

    rows = conn.execute(
        text("SELECT id, tenant_id FROM campaign_runs WHERE status = 'running'")
    )
    for run_id, tenant_id in rows:
        campaigns.set_status(conn, run_id, campaigns.STATUS_PAUSED, tenant_id=tenant_id)


def _a_campaign_borrower(conn) -> dict:
    row = conn.execute(
        text(
            """
            SELECT c.id, c.tenant_id
            FROM customers c JOIN accounts a ON a.customer_id = c.id
            WHERE c.id <> 'UNKNOWN-CALLER'
            ORDER BY c.id LIMIT 1
            """
        )
    ).mappings().first()
    if row is None:
        pytest.skip("no seeded customer with an account")
    conn.execute(
        text(
            """
            UPDATE customers
            SET phone_primary = '919000000001', timezone = 'Asia/Kolkata',
                dnd = false, preferred_window = NULL
            WHERE id = :id
            """
        ),
        {"id": row["id"]},
    )
    conn.execute(
        text(
            """
            UPDATE consent_records
            SET dnd_registry = false, allowed_days = NULL, allowed_hours = NULL
            WHERE customer_id = :id
            """
        ),
        {"id": row["id"]},
    )
    return dict(row)


def _opt_borrower_in(conn, customer_id: str) -> None:
    conn.execute(
        text(
            """
            INSERT INTO consent_records (id, customer_id)
            VALUES (:id, :cid)
            ON CONFLICT (customer_id) DO NOTHING
            """
        ),
        {"id": f"CR-{customer_id}", "cid": customer_id},
    )
    cr = conn.execute(
        text("SELECT id FROM consent_records WHERE customer_id = :id"),
        {"id": customer_id},
    ).mappings().first()
    assert cr
    for ch in ("voice", "whatsapp", "sms", "email"):
        conn.execute(
            text(
                """
                INSERT INTO channel_consents
                  (id, consent_id, channel, status, weekly_frequency_cap, used_this_week, captured_at)
                VALUES
                  (:id, :cr, :ch, 'opted_in', 99, 0, now())
                ON CONFLICT (consent_id, channel, purpose)
                DO UPDATE SET status = 'opted_in', weekly_frequency_cap = 99, captured_at = now()
                """
            ),
            {"id": f"{cr['id']}-{ch}", "cr": cr["id"], "ch": ch},
        )


def _running_campaign(conn, cust: dict, *, bot_id: str):
    import campaigns

    _pause_running_campaigns(conn)
    run = campaigns.create(
        conn,
        tenant_id=cust["tenant_id"],
        name="process_one composition",
        objective="dpd_reminder",
        bot_id=bot_id,
        window_start_hour=0,
        window_end_hour=24,
    )
    added = campaigns.add_targets(conn, run["id"], [cust["id"]], tenant_id=cust["tenant_id"])
    assert added == 1
    started = campaigns.set_status(
        conn, run["id"], campaigns.STATUS_RUNNING, tenant_id=cust["tenant_id"]
    )
    assert started is not None
    return started


def _admit_at_noon(monkeypatch: pytest.MonkeyPatch):
    import contact_policy

    real = contact_policy.admit
    noon = _noon_today()

    def _wrapped(conn, **kwargs):
        kwargs.setdefault("now", noon)
        return real(conn, **kwargs)

    monkeypatch.setattr(contact_policy, "admit", _wrapped)
    return real


def _record_gate(monkeypatch: pytest.MonkeyPatch, dialler: _Dialler) -> list[str]:
    import contact_policy
    import outbound

    steps: list[str] = []
    real_reserve = outbound.reserve
    real_admit = contact_policy.admit
    real_suppress = outbound.suppress

    def reserve(*args, **kwargs):
        steps.append("reserve")
        return real_reserve(*args, **kwargs)

    def admit(*args, **kwargs):
        steps.append("admit")
        return real_admit(*args, **kwargs)

    def suppress(*args, **kwargs):
        steps.append("suppress")
        return real_suppress(*args, **kwargs)

    def place(*args, **kwargs):
        steps.append("place")
        return dialler(*args, **kwargs)

    monkeypatch.setattr(outbound, "reserve", reserve)
    monkeypatch.setattr(contact_policy, "admit", admit)
    monkeypatch.setattr(outbound, "suppress", suppress)
    monkeypatch.setattr(outbound, "place", place)
    return steps


def test_process_one_uses_the_run_bot_not_only_the_default(
    db_tx, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The studio card on the run is the agent that dials, not ``DEFAULT_BOT_ID``.

    This used to be an ``inspect.getsource`` substring. A logic inversion that
    kept the same token still passed; executing the dialer does not.
    """
    import campaigns
    import db as dbmod

    monkeypatch.setattr(campaigns, "enabled", lambda: True)
    monkeypatch.setenv("CONTACT_DAILY_CAP", "99")
    monkeypatch.setenv("CONTACT_WEEKLY_CAP", "99")
    monkeypatch.setenv("CONTACT_COOLING_OFF_MINUTES", "0")
    monkeypatch.setattr(dbmod, "DEFAULT_BOT_ID", "NOT-THE-STUDIO-BOT")
    _admit_at_noon(monkeypatch)

    cust = _a_campaign_borrower(db_tx)
    _opt_borrower_in(db_tx, cust["id"])
    bot = db_tx.execute(text("SELECT id FROM bots LIMIT 1")).scalar()
    if not bot:
        pytest.skip("no bot seeded")
    run = _running_campaign(db_tx, cust, bot_id=str(bot))

    dialler = _Dialler()
    steps = _record_gate(monkeypatch, dialler)

    assert campaigns.process_one(dbmod.engine) is True
    assert steps == ["reserve", "admit", "place"]
    assert len(dialler.calls) == 1
    stored = db_tx.execute(
        text("SELECT bot_id FROM call_attempts WHERE campaign_run_id = :run"),
        {"run": run["id"]},
    ).scalar()
    assert stored == str(bot)


def test_process_one_suppresses_an_opted_out_borrower_instead_of_dialling(
    db_tx, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``reserve → admit → suppress``, and ``place`` is not reached.

    The composition the piece-wise suites never executed. An opt-out written
    by ``db.opt_out`` has to be the reason — not a hand-built SQL row.
    """
    import campaigns
    import contact_policy
    import db as dbmod

    monkeypatch.setattr(campaigns, "enabled", lambda: True)
    monkeypatch.setenv("CONTACT_COOLING_OFF_MINUTES", "0")

    cust = _a_campaign_borrower(db_tx)
    _opt_borrower_in(db_tx, cust["id"])
    dbmod.opt_out(cust["id"], {"channel": "call", "source": "Agent"})
    bot = db_tx.execute(text("SELECT id FROM bots LIMIT 1")).scalar() or dbmod.DEFAULT_BOT_ID
    run = _running_campaign(db_tx, cust, bot_id=str(bot))

    dialler = _Dialler()
    steps = _record_gate(monkeypatch, dialler)

    assert campaigns.process_one(dbmod.engine) is True
    assert steps == ["reserve", "admit", "suppress"]
    assert dialler.calls == []

    attempt = db_tx.execute(
        text(
            """
            SELECT state, suppressed_reason FROM call_attempts
            WHERE campaign_run_id = :run
            """
        ),
        {"run": run["id"]},
    ).mappings().first()
    assert attempt is not None
    assert attempt["state"] == "suppressed"
    assert attempt["suppressed_reason"] == contact_policy.REASON_OPTED_OUT

    target = db_tx.execute(
        text("SELECT state, note FROM campaign_targets WHERE run_id = :run"),
        {"run": run["id"]},
    ).mappings().first()
    assert target is not None
    assert target["state"] == "skipped"
    assert target["note"] == contact_policy.REASON_OPTED_OUT


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


def _voice_bot_src() -> str:
    """run_bot and the three modules it was split into, as one text."""
    return "\n".join(
        (_BACKEND / "voice" / name).read_text(encoding="utf-8")
        for name in ("bot.py", "bot_flow.py", "bot_pipeline.py", "bot_handlers.py")
    )


def test_bot_traces_the_hops_the_demo_log_was_missing() -> None:
    src = _voice_bot_src()
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
    assert "prewarm_shared_client(force=True)" not in src
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
    bot = _voice_bot_src()
    # The conversation is data now (voice/flows.py was materialised and deleted).
    flows = (_BACKEND / "agent_core" / "cards" / "graphs" / "collections.json").read_text(encoding="utf-8")

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
    # The mission briefing is a developer block, not a string spliced into the
    # system prefix; the prefix is per deployment, not per borrower.
    assert 'session.extra["mission_briefing"]' in bot
    assert "outbound collections voice agent" not in bot
    assert "garbled STT fragments" in bot
    assert "on_user_turn_stopped_rearm_idle" in bot
    assert "Never open with a tool acknowledgement" in flows
    assert "search_knowledge_base" in flows


def test_frontend_create_campaign_sends_bot_id() -> None:

    from tests.conftest import frontend_file

    tab = frontend_file("src", "components", "prompt-studio", "OutboundTab.tsx")
    text = tab.read_text(encoding="utf-8")
    assert "botId" in text
    assert "flow={flow}" in text or "flow }" in text or "flow," in text
    assert "agentCard: card, flow" in text
