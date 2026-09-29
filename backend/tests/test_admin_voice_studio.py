"""Settings, Roles & access and Billing, wired to Voice Studio.

One promise per test:

* the master switch stops calls Voice Studio starts itself, and an attempt id
  is only a pass when it names a real attempt PayInt reserved for that number;
* a studio attempt records its provider, so the after-call hook can find it;
* an engine API key works only while its owner is active and still holds the
  permission for what the key is doing;
* the Roles screen's Voice Studio actions are the gateway's own rules;
* a test call speaks as the chosen Voice Studio agent, through the gate;
* metering a run twice meters it once, and spend that arrives later is added;
* a budget rule fires once a month and can pause outbound;
* a cost statement is the metered usage, rebuilt while it is a draft.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text

import authz
import platform_switches
import voice_studio


@pytest.fixture
def switch_on(monkeypatch):
    monkeypatch.setattr(platform_switches, "outbound_enabled", lambda **_kw: True)


@pytest.fixture
def customer(db_tx):
    row = db_tx.execute(text(
        "SELECT id, phone_primary FROM customers WHERE phone_primary IS NOT NULL "
        "AND length(regexp_replace(phone_primary, '\\D', '', 'g')) >= 10 ORDER BY id LIMIT 1"
    )).mappings().first()
    if row is None:
        pytest.skip("seed has no customer with a phone number")
    return dict(row)


# --- the engine's own dials -------------------------------------------------


def test_the_master_switch_stops_calls_the_engine_starts(monkeypatch) -> None:
    monkeypatch.setattr(platform_switches, "outbound_enabled", lambda **_kw: False)
    got = voice_studio.admit_engine_call({"to_number": "+919999900000", "workflow_run_id": 1})
    assert got == {"admitted": False, "reason": "outbound_disabled"}


def test_an_invented_attempt_id_is_not_a_pass(db_tx, switch_on) -> None:
    got = voice_studio.admit_engine_call({"to_number": "+910000000001", "attempt_id": "ATT-made-up",
                                          "workflow_run_id": 1})
    assert got["admitted"] is False and got["reason"] == "unknown_number"


def test_a_reserved_attempt_for_that_number_is_a_pass(db_tx, switch_on, customer) -> None:
    import outbound

    attempt = outbound.reserve(db_tx, customer_id=customer["id"], to_phone=customer["phone_primary"],
                               objective="dpd_reminder")
    ok = voice_studio.admit_engine_call({"to_number": customer["phone_primary"], "attempt_id": attempt["id"],
                                         "workflow_run_id": 7})
    assert ok == {"admitted": True, "reason": "payint_dialler"}
    # The same attempt id cannot carry a call to someone else.
    other = voice_studio.admit_engine_call({"to_number": "+910000000002", "attempt_id": attempt["id"],
                                            "workflow_run_id": 8})
    assert other["admitted"] is False


def test_a_studio_dial_records_its_provider(monkeypatch, switch_on) -> None:
    import voice_studio_routing

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"workflow_run_id": 321}

    sent = {}
    monkeypatch.setenv("VOICE_STUDIO_API_KEY", "k")
    monkeypatch.setattr(voice_studio_routing, "outbound_trigger_path", lambda wid: f"trigger-{wid}")
    monkeypatch.setattr(voice_studio.httpx, "post", lambda url, json, headers, timeout: sent.update(url=url, body=json) or _Resp())
    got = voice_studio.originate(to="+919999900000", custom={"agent_id": "42", "objective": "dpd_reminder"})
    assert got == {"callSid": "321", "status": "initiated", "provider": voice_studio.PROVIDER}
    assert sent["url"].endswith("/public/agent/trigger-42")
    assert sent["body"]["initial_context"]["agent_id"] == 42


# --- engine API keys ---------------------------------------------------------


def _user(db_tx, *, status: str) -> str:
    import db

    uid = f"u-{uuid.uuid4().hex[:8]}"
    db_tx.execute(text(
        "INSERT INTO users (id, tenant_id, name, status) VALUES (:id, :t, 'Key owner', :s)"
    ), {"id": uid, "t": db.current_tenant(), "s": status})
    authz.invalidate_permission_cache(uid)
    return uid


def test_a_key_stops_working_when_its_owner_is_deactivated(db_tx, monkeypatch) -> None:
    import db
    from routers.voice_studio_hooks import key_use_allowed

    uid = _user(db_tx, status="inactive")
    monkeypatch.setattr(authz, "has_permission", lambda *_a, **_k: True)
    got = key_use_allowed({"user_id": uid, "tenant_id": db.current_tenant(), "method": "POST",
                           "path": "/api/v1/public/agent/abc"})
    assert got == {"allowed": False, "reason": "owner_inactive"}


def test_a_key_needs_the_permission_for_what_it_does(db_tx, monkeypatch) -> None:
    import db
    from routers.voice_studio_hooks import key_use_allowed

    uid = _user(db_tx, status="active")
    held = {authz.BOT_READ}
    monkeypatch.setattr(authz, "has_permission", lambda _u, p: p in held)
    body = {"user_id": uid, "tenant_id": db.current_tenant(), "method": "POST", "path": "/api/v1/public/agent/x"}
    assert key_use_allowed(body)["allowed"] is False  # placing a call needs voice.operate
    held.add(authz.VOICE_OPERATE)
    assert key_use_allowed(body) == {"allowed": True}
    other_tenant = {**body, "tenant_id": "someone-else"}
    assert key_use_allowed(other_tenant)["allowed"] is False
    assert key_use_allowed({**body, "user_id": voice_studio.SYSTEM_ACTOR}) == {"allowed": True}


# --- roles -------------------------------------------------------------------


def test_the_roles_screen_lists_the_gateways_own_rules() -> None:
    from routers import agentstudio_gateway as gw

    actions = gw.studio_actions()
    for _methods, _pattern, perms, label in gw.PERMISSION_RULES:
        for perm in perms if label else ():
            assert label in actions[perm]
    assert gw.required_permissions("PUT", "/tools/abc") == (authz.AGENT_EDIT,)
    assert gw.required_permissions("POST", "/workflow/3/embed-token") == (authz.AGENT_PUBLISH,)
    assert gw.required_permissions("POST", "/campaign/3/start") == (authz.COLLECTIONS_WRITE,)
    assert gw.required_permissions("GET", "/campaign/3/report") == (authz.PII_RAW_READ,)
    assert gw.required_permissions("GET", "/organizations/usage/runs/report") == (authz.PII_RAW_READ,)
    assert gw.required_permissions("PATCH", "/campaign/3") == (authz.COLLECTIONS_WRITE,)
    assert gw.required_permissions("GET", "/telephony/ws/4/1/9") == ()
    assert authz.TOOL_APPROVE in gw.required_permissions("GET", "/tools/abc/revisions")
    assert gw.required_permissions("GET", "/organizations/usage/runs") == (authz.ANALYTICS_READ,)


def test_designing_and_releasing_take_two_people() -> None:
    designer = authz.ROLE_DEFAULTS["voice_designer"]
    approver = authz.ROLE_DEFAULTS["release_approver"]
    assert authz.AGENT_EDIT in designer and authz.AGENT_PUBLISH not in designer
    assert authz.AGENT_PUBLISH in approver and authz.TOOL_APPROVE in approver
    assert authz.AGENT_EDIT not in approver


# --- the test call -------------------------------------------------------------


def test_a_test_call_speaks_as_the_chosen_agent(db_tx, monkeypatch, switch_on, customer) -> None:
    import db
    import outbound
    import voice_studio_testcall as testcall

    number_id = f"TN-{uuid.uuid4().hex[:8]}"
    db_tx.execute(text("INSERT INTO test_numbers (id, tenant_id, e164) VALUES (:id, :t, :n)"),
                  {"id": number_id, "t": db.current_tenant(), "n": outbound.to_e164(customer["phone_primary"])})
    monkeypatch.setattr(testcall, "waivers", lambda: frozenset(
        {"cooling_off", "daily_cap", "weekly_cap", "outside_calling_hours", "outside_allowed_window"}))
    placed = {}

    def fake_place(engine, attempt, *, to_phone, custom):
        placed.update(attempt=attempt, custom=custom)
        return {"placed": True, "attemptId": attempt["id"], "callSid": "99"}

    monkeypatch.setattr(outbound, "place", fake_place)
    try:
        got = testcall.place(42, number_id, "dpd_reminder", "tester")
    except PermissionError as refused:
        pytest.skip(f"the seed customer is not contactable: {refused}")
    assert got["runId"] == "99" and got["customerId"] == customer["id"]
    assert placed["custom"]["agent_id"] == "42"
    bot = db_tx.execute(text("SELECT bot_id FROM call_attempts WHERE id = :a"), {"a": placed["attempt"]["id"]}).scalar()
    assert bot == voice_studio.bot_id_for(42)


# --- metering ----------------------------------------------------------------


def test_metering_a_run_twice_meters_it_once_and_adds_what_came_later(db_tx) -> None:
    import usage_meter

    usage_meter.sync_price_book(db_tx)  # the carrier-minutes service row
    run_id = f"t{uuid.uuid4().hex[:8]}"
    run = {"id": run_id, "usage_info": {
        "llm": {"OpenAILLMService|||gpt-4.1-mini": {"prompt_tokens": 1000, "completion_tokens": 200,
                                                     "total_tokens": 1200}},
        "tts": {"AzureTTSService|||en-IN-NeerjaNeural": 500},
        "call_duration_seconds": 120,
    }}
    voice_studio.meter_run(None, run)
    voice_studio.meter_run(None, run)

    def totals():
        usage_meter.flush()
        return {r[0]: (float(r[1]), float(r[2] or 0)) for r in db_tx.execute(text(
            "SELECT service_id, sum(units), sum((meta->>'promptTokens')::numeric) FROM usage_events "
            "WHERE source_ref = :r GROUP BY 1"), {"r": f"voice-studio-run:{run_id}"})}

    first = totals()
    assert first["llm_chat"] == (1.2, 1000.0)
    assert first["tts_az"][0] == 0.5
    assert abs(first["stt_az"][0] - 2.0) < 1e-6 and abs(first["tel_min"][0] - 2.0) < 1e-6
    # The QA node's tokens are merged into the run after it was filed.
    run["usage_info"]["llm"]["OpenAILLMService|||gpt-4.1-mini"] = {
        "prompt_tokens": 1500, "completion_tokens": 300, "total_tokens": 1800}
    voice_studio.meter_run(None, run)
    assert totals()["llm_chat"] == (1.8, 1500.0)


def test_a_model_with_its_own_price_is_priced_by_it(monkeypatch) -> None:
    import usage_meter

    monkeypatch.setenv("LLM_PRICE_BOOK_JSON", '{"big": {"in": 10, "out": 20, "cached": 1}}')
    monkeypatch.setenv("USD_INR_FX", "100")
    # 1M in of which 0.5M cached, 1M out: 0.5*10 + 0.5*1 + 20 = 25.5 USD.
    cost = usage_meter.chat_cost_inr(prompt_tokens=1_000_000, completion_tokens=1_000_000,
                                     model="big", cached_tokens=500_000)
    assert cost == Decimal("2550")
    assert usage_meter.model_prices("unknown")[3] is False


# --- budgets and statements ----------------------------------------------------


def _spend(db_tx, tenant: str, day: date, cost: str) -> None:
    db_tx.execute(text(
        "INSERT INTO billing_usage_daily (id, service_id, tenant_id, environment, usage_date, units, cost_inr) "
        "VALUES (:id, 'llm_chat', :t, 'production', :d, 1, :c)"
    ), {"id": f"bud-{uuid.uuid4().hex[:10]}", "t": tenant, "d": day, "c": Decimal(cost)})


def test_a_budget_rule_fires_once_a_month_and_can_pause_outbound(db_tx, monkeypatch) -> None:
    import billing_jobs
    import db

    tenant = db.current_tenant()
    month = "2031-05"
    budget = f"budget-test-{uuid.uuid4().hex[:6]}"
    db_tx.execute(text("INSERT INTO budgets (id, tenant_id, environment, month, amount_inr) "
                       "VALUES (:id, :t, 'production', '2031-04', 1000)"), {"id": budget, "t": tenant})
    db_tx.execute(text("INSERT INTO budget_rules (id, budget_id, threshold_pct, action_channel, action, channels) "
                       "VALUES (:id, :b, 80, 'in-app', 'Pause outbound', '[\"in-app\"]')"),
                  {"id": f"r-{uuid.uuid4().hex[:6]}", "b": budget})
    billing_jobs.ensure_month_budgets(db_tx, tenant, month)
    carried = db_tx.execute(text("SELECT amount_inr FROM budgets WHERE tenant_id = :t AND month = :m "
                                 "AND environment = 'production'"), {"t": tenant, "m": month}).scalar()
    assert carried == Decimal("1000.00")
    _spend(db_tx, tenant, date(2031, 5, 3), "850")
    fired = billing_jobs.evaluate(db_tx, tenant, date(2031, 5, 4))
    assert len(fired) == 1 and fired[0]["action"] == billing_jobs.PAUSE_OUTBOUND
    assert billing_jobs.evaluate(db_tx, tenant, date(2031, 5, 5)) == []  # once a month

    flipped = []
    monkeypatch.setattr(platform_switches, "flip", lambda key, enabled, note=None: flipped.append((key, enabled)))
    billing_jobs._act(fired[0])
    assert flipped == [(platform_switches.OUTBOUND_ENABLED, False)]


def test_a_statement_is_the_metered_usage_rebuilt_while_a_draft(db_tx) -> None:
    import billing_jobs
    import db

    tenant = db.current_tenant()
    _spend(db_tx, tenant, date(2031, 6, 2), "10.25")
    _spend(db_tx, tenant, date(2031, 6, 9), "4.75")
    inv = billing_jobs.build_statement(db_tx, tenant, "2031-06", "production")
    total = db_tx.execute(text("SELECT total_inr FROM invoices WHERE id = :id"), {"id": inv}).scalar()
    assert total == Decimal("15.00")
    _spend(db_tx, tenant, date(2031, 6, 20), "5")
    assert billing_jobs.build_statement(db_tx, tenant, "2031-06", "production") == inv
    assert db_tx.execute(text("SELECT total_inr FROM invoices WHERE id = :id"), {"id": inv}).scalar() == Decimal("20.00")
    db_tx.execute(text("UPDATE invoices SET status = 'pending' WHERE id = :id"), {"id": inv})
    _spend(db_tx, tenant, date(2031, 6, 21), "5")
    assert billing_jobs.build_statement(db_tx, tenant, "2031-06", "production") is None  # issued: frozen
