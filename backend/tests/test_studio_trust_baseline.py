"""Agent Studio trust baseline — canary, shadow, handoff, skills, evals, chain."""

from __future__ import annotations

import json
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import text

import db
from agent_core import change_log
from agent_core.cards.compile import compile_card
from agent_core.cards.defaults import COLLECTIONS_BOT_ID, card_dump, card_for
from agent_core.canary import pick_deployment_id, record_experiment
from agent_core.guardrails import evaluate_guardrails
from agent_core.skills.defaults import FIRST_PARTY_SKILL_SLUGS
from agent_core.skills.intersect import effective_tools
from agent_core.skills.pack import pack_for_slug
from agent_core.skills.persist import packs_for_slugs, upsert_skill_from_pack
from agent_core.tools.catalog import CATALOG
from agent_core.tools.handoff_allowlist import handoff_allowlist
from voice.flow_export import built_in_collections_graph


CATALOG_NAMES = set(CATALOG.specs)


def _compile(**kwargs):
    return compile_card(
        bot_id=COLLECTIONS_BOT_ID,
        card_raw=card_dump(COLLECTIONS_BOT_ID),
        flow=built_in_collections_graph(),
        catalog_names=CATALOG_NAMES,
        known_bot_ids={COLLECTIONS_BOT_ID, "intake-v1", "insurance-v1", "supervisor-brief"},
        **kwargs,
    )


def test_missing_customer_id_follows_baseline(monkeypatch) -> None:
    monkeypatch.setattr(
        db,
        "get_active_deployment",
        lambda **_k: {"id": "DEP-ACTIVE"},
    )
    monkeypatch.setattr(
        "agent_core.canary.running_experiment",
        lambda *_a, **_k: {
            "canary_deployment_id": "DEP-CANARY",
            "baseline_deployment_id": "DEP-BASE",
            "traffic_pct": 40,
            "shadow": False,
        },
    )
    assert pick_deployment_id(COLLECTIONS_BOT_ID, customer_id=None) == "DEP-BASE"
    assert pick_deployment_id(COLLECTIONS_BOT_ID, customer_id="") == "DEP-BASE"


def _experiment(**over):
    base = {
        "id": "EXP-1",
        "canary_deployment_id": "DEP-CANARY",
        "baseline_deployment_id": "DEP-BASE",
        "traffic_pct": 100,
        "shadow": False,
    }
    return {**base, **over}


@pytest.mark.parametrize(
    "canary_status,expected",
    [
        ("active", "DEP-CANARY"),
        ("retired", "DEP-BASE"),
        ("rolled_back", "DEP-BASE"),
        (None, "DEP-BASE"),
    ],
)
def test_routing_refuses_a_canary_whose_deployment_is_not_live(
    monkeypatch, canary_status, expected
) -> None:
    """`rollback_bot_deployment` closes running experiments, but best-effort —
    the call sits in a `try/except` that only logs. If it ever fails, the
    experiment stays `running` and the split kept sending its share of traffic
    to the exact deployment an operator had just rolled back, while the screen
    said the rollback was done. The router now checks rather than trusting it.

    `None` is the LEFT JOIN finding no deployment row at all, which is a reason
    to follow the baseline, not to ignore.
    """
    monkeypatch.setattr(db, "get_active_deployment", lambda **_k: {"id": "DEP-ACTIVE"})
    monkeypatch.setattr(
        "agent_core.canary.running_experiment",
        lambda *_a, **_k: _experiment(canary_status=canary_status),
    )
    assert pick_deployment_id(COLLECTIONS_BOT_ID, customer_id="cust-1") == expected


def test_an_unchecked_status_does_not_reroute(monkeypatch) -> None:
    """A caller that supplied no `canary_status` never looked, which is not the
    same as looking and finding the deployment gone. Rerouting on a column that
    was never read would move live traffic on the strength of a missing key."""
    monkeypatch.setattr(db, "get_active_deployment", lambda **_k: {"id": "DEP-ACTIVE"})
    monkeypatch.setattr("agent_core.canary.running_experiment", lambda *_a, **_k: _experiment())
    assert pick_deployment_id(COLLECTIONS_BOT_ID, customer_id="cust-1") == "DEP-CANARY"


def test_shadow_experiment_follows_baseline(monkeypatch) -> None:
    monkeypatch.setattr(db, "get_active_deployment", lambda **_k: {"id": "DEP-ACTIVE"})
    monkeypatch.setattr(
        "agent_core.canary.running_experiment",
        lambda *_a, **_k: {
            "canary_deployment_id": "DEP-CANARY",
            "baseline_deployment_id": "DEP-BASE",
            "traffic_pct": 40,
            "shadow": True,
        },
    )
    assert pick_deployment_id(COLLECTIONS_BOT_ID, customer_id="cust-1") == "DEP-BASE"


def test_record_experiment_refuses_shadow(db_tx) -> None:
    row = db_tx.execute(text("SELECT to_regclass('public.deployment_experiments') AS t")).mappings().first()
    if not row or not row["t"]:
        pytest.skip("deployment_experiments missing")
    result = record_experiment(
        db_tx,
        bot_id=COLLECTIONS_BOT_ID,
        canary_deployment_id="DEP-X",
        baseline_deployment_id="DEP-Y",
        traffic_pct=10,
        shadow=True,
        auto_rollback=["slo_miss"],
    )
    assert result is None
    n = db_tx.execute(
        text(
            """
            SELECT count(*) FROM deployment_experiments
             WHERE bot_id = :b AND shadow = true AND status = 'running'
            """
        ),
        {"b": COLLECTIONS_BOT_ID},
    ).scalar()
    assert int(n or 0) == 0


def test_g12_fails_closed_on_shadow() -> None:
    report = _compile(traffic_pct=100, shadow=True)
    g12 = next(g for g in report.gates if g.gate == "G12")
    assert g12.status == "fail"
    assert not report.ok


def test_g12_and_lint_skip_on_rollback() -> None:
    report = _compile(
        skip_eval_gates=True,
        shadow=True,
        prompt="threaten the borrower immediately",
        prompt_guardrails={"prohibited": ["threaten"]},
    )
    g12 = next(g for g in report.gates if g.gate == "G12")
    glint = next(g for g in report.gates if g.gate == "G-LINT")
    assert g12.status == "skipped"
    assert glint.status == "skipped"


def test_g_lint_blocks_error_severity_prompts() -> None:
    report = _compile(
        prompt="We will threaten legal action today.",
        prompt_guardrails={"prohibited": ["threaten"]},
    )
    glint = next(g for g in report.gates if g.gate == "G-LINT")
    assert glint.status == "fail"
    assert not report.ok


def test_handoff_allowlist_is_empty_never_none() -> None:
    assert handoff_allowlist(bot_id="no-such-bot") == set()
    assert handoff_allowlist(agent_card={"not": "a card"}, bot_id=None) == set()
    live = handoff_allowlist(agent_card=card_dump(COLLECTIONS_BOT_ID))
    assert isinstance(live, set)
    assert None not in live


def test_whatsapp_does_not_flag_missing_recording_disclosure() -> None:
    kwargs = dict(
        customer_text="hello",
        bot_text="Please pay your overdue EMI.",
        intent="payment_intent",
        guardrails={"alwaysDiscloseRecording": True},
        turn_index=1,
        elapsed_seconds=2.0,
        customer_bot_exchanges=1,
        recording_disclosed=False,
    )
    voice = evaluate_guardrails(channel="voice", **kwargs)
    text_ch = evaluate_guardrails(channel="whatsapp", **kwargs)
    assert "missing-recording-disclosure" in voice
    assert "missing-recording-disclosure" not in text_ch


def test_the_channel_actually_reaches_the_guardrail_from_the_turn_writer(db_tx) -> None:
    """The gate above was green while the live path was broken.

    `evaluate_and_flag_bot_turn` accepted `channel`, used it for `TurnFacts`,
    and did not forward it to `evaluate_guardrails` — so every WhatsApp turn
    defaulted to "voice" and wrote an `r-rec` RBI recording-disclosure
    violation for a disclosure `prompt.py` forbids the bot from saying on text.
    Testing the gate directly could never catch that; this goes through the
    caller. The flag writes below fail on a synthetic interaction id and are
    swallowed by the function's own handlers, which is why no fixture is needed.
    """
    from voice.persist import evaluate_and_flag_bot_turn

    kwargs = dict(
        interaction_id="INT-CHANNEL-WIRING-PROBE",
        customer_text="hello",
        bot_text="Please pay your overdue EMI.",
        intent="payment_intent",
        guardrails={"alwaysDiscloseRecording": True},
        turn_index=1,
        elapsed_seconds=2.0,
        customer_bot_exchanges=1,
        recording_disclosed=False,
        simulated=True,
    )

    assert "missing-recording-disclosure" in evaluate_and_flag_bot_turn(
        channel="voice", **kwargs
    )
    assert "missing-recording-disclosure" not in evaluate_and_flag_bot_turn(
        channel="whatsapp", **kwargs
    )


def test_frozen_connector_tools_do_not_rebind_live(db_tx) -> None:
    card = card_for(COLLECTIONS_BOT_ID)
    frozen = effective_tools(
        card, catalog_names=CATALOG_NAMES, frozen_connector_tools=["ext.frozen.tool"]
    )
    assert "ext.frozen.tool" in frozen
    closed = effective_tools(card, catalog_names=CATALOG_NAMES, frozen_connector_tools=[])
    assert "ext.frozen.tool" not in closed


def test_invalid_hmac_pack_is_dropped_not_fallen_back(db_tx) -> None:
    slug = "ptp-negotiate"
    row = db_tx.execute(
        text(
            """
            SELECT sv.id FROM skills s
              JOIN skill_versions sv ON sv.skill_id = s.id
             WHERE s.slug = :slug AND sv.status = 'signed'
             ORDER BY sv.created_at DESC LIMIT 1
            """
        ),
        {"slug": slug},
    ).mappings().first()
    if not row:
        pytest.skip("no signed ptp-negotiate version in this database")
    db_tx.execute(
        text("UPDATE skill_versions SET signature = :sig WHERE id = :id"),
        {"sig": "0" * 64, "id": row["id"]},
    )
    packs = packs_for_slugs([slug])
    assert slug not in {p.slug for p in packs}


def test_import_cannot_overwrite_a_first_party_slug(db_tx) -> None:
    pack = pack_for_slug("ptp-negotiate")
    pack.origin = "tenant"
    with pytest.raises(ValueError, match="skill_first_party"):
        upsert_skill_from_pack(pack, origin="tenant", signed=False)
    assert "ptp-negotiate" in FIRST_PARTY_SKILL_SLUGS


def test_eval_gate_requires_the_exact_draft(db_tx) -> None:
    suite = db_tx.execute(
        text("SELECT id FROM eval_suites WHERE kind = 'regression' LIMIT 1")
    ).mappings().first()
    if not suite:
        pytest.skip("no regression suite")
    pv = db.get_published_prompt_version(COLLECTIONS_BOT_ID)
    if pv is None:
        pytest.skip("no published collections prompt")
    other = f"pv-trust-{uuid.uuid4().hex[:8]}"
    db.save_eval_report(
        suite_id=suite["id"],
        bot_id=COLLECTIONS_BOT_ID,
        status="pass",
        summary={"failed": 0, "total": 1},
        prompt_version_id=None,
    )
    scoped = db.save_eval_report(
        suite_id=suite["id"],
        bot_id=COLLECTIONS_BOT_ID,
        status="fail",
        summary={"failed": 1, "total": 1},
        prompt_version_id=pv["id"],
    )
    latest_any = db.get_latest_eval_report(bot_id=COLLECTIONS_BOT_ID, kind="regression")
    latest_scoped = db.get_latest_eval_report(
        bot_id=COLLECTIONS_BOT_ID, kind="regression", prompt_version_id=pv["id"]
    )
    latest_other = db.get_latest_eval_report(
        bot_id=COLLECTIONS_BOT_ID, kind="regression", prompt_version_id=other
    )
    assert latest_scoped is not None
    assert latest_scoped["id"] == scoped["id"]
    assert latest_scoped["status"] == "fail"
    assert latest_other is None
    assert latest_any is not None


def test_rollback_route_requires_agent_publish() -> None:
    import authz

    assert authz.ROUTE_PERMISSIONS[("POST", "/bot-deployments/{deployment_id}/rollback")] == authz.AGENT_PUBLISH
    assert (
        authz.ROUTE_PERMISSIONS[("POST", "/bot-deployments/experiments/{experiment_id}/rollback")]
        == authz.AGENT_PUBLISH
    )


def test_slo_signal_is_ttfb_not_call_duration() -> None:
    from agent_core import canary as canary_mod
    import inspect

    source = inspect.getsource(canary_mod._slo_miss)
    assert "llm_ttfb_ms" in source
    assert "duration_sec" not in source


def test_entry_hash_covers_actor_and_timestamp(cloned_bot: str) -> None:
    version_id = db.get_agent_studio_card(cloned_bot)["draftVersionId"]
    db.publish_prompt_version(version_id, "hash actors")
    with db.engine.connect() as conn:
        payload = conn.execute(
            text(
                """
                SELECT payload FROM audit_log
                 WHERE entity_id = :b AND action = 'agent.publish'
                 ORDER BY created_at DESC LIMIT 1
                """
            ),
            {"b": cloned_bot},
        ).scalar()
    payload = payload if isinstance(payload, dict) else json.loads(payload)
    body = {k: v for k, v in payload.items() if k != "entryHash"}
    assert body.get("actorUserId")
    assert body.get("at")
    assert change_log._digest(body) == payload["entryHash"]
    tampered = {**body, "actorUserId": "someone-else"}
    assert change_log._digest(tampered) != payload["entryHash"]


def test_tail_deletion_is_visible_once_the_head_table_exists(cloned_bot: str) -> None:
    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS audit_chain_heads (
                  tenant_id TEXT PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
                  entry_hash TEXT NOT NULL,
                  seq BIGINT NOT NULL,
                  updated_at timestamptz NOT NULL DEFAULT now()
                )
                """
            )
        )
    version_id = db.get_agent_studio_card(cloned_bot)["draftVersionId"]
    db.publish_prompt_version(version_id, "v1")
    second = db.restore_prompt_version_as_draft(version_id)["id"]
    db.publish_prompt_version(second, "v2")

    with db.engine.connect() as conn:
        newest = conn.execute(
            text(
                """
                SELECT id FROM audit_log
                 WHERE entity_id = :b AND entity_type = 'bot'
                 ORDER BY COALESCE((payload->>'seq')::bigint, 0) DESC, id DESC
                 LIMIT 1
                """
            ),
            {"b": cloned_bot},
        ).scalar()
    with db.engine.begin() as conn:
        conn.execute(text("DELETE FROM audit_log WHERE id = :id"), {"id": newest})

    verdict = db.agent_change_log(cloned_bot)["chain"]
    assert verdict["ok"] is False
    assert verdict["reason"] == "tail_truncated"


def test_two_bots_can_append_concurrently_without_breaking_the_chain(db_real) -> None:
    tenant = db.current_tenant()
    actor = db._actor_user_id()
    bots = [f"chain-conc-{uuid.uuid4().hex[:8]}" for _ in range(2)]
    for bot_id in bots:
        db_real.track("audit_log", entity_id=bot_id)

    errors: list[BaseException] = []

    def _write(bot_id: str) -> None:
        try:
            with db.engine.begin() as conn:
                change_log.record_archive(
                    conn,
                    tenant_id=tenant,
                    actor_user_id=actor,
                    entry_id=db._id("AUD"),
                    bot_id=bot_id,
                    retired_deployment_id=None,
                )
        except BaseException as exc:  # noqa: BLE001 — surface into the parent
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(_write, bots))
    assert not errors, errors

    with db.engine.connect() as conn:
        verdict = change_log.verify_chain(conn, tenant_id=tenant)
        rows = list(
            conn.execute(
                text(
                    """
                    SELECT payload->>'seq' AS seq FROM audit_log
                     WHERE tenant_id = :t AND entity_type = 'bot'
                       AND entity_id IN (:b0, :b1)
                    """
                ),
                {"t": tenant, "b0": bots[0], "b1": bots[1]},
            )
        )
    assert verdict["ok"] is True, verdict
    seqs = [int(r[0]) for r in rows]
    assert len(seqs) == 2
    assert seqs[0] != seqs[1]


def test_experiment_rollback_writes_an_actor_bearing_entry(db_tx) -> None:
    from agent_core.canary import rollback_experiment

    row = db_tx.execute(text("SELECT to_regclass('public.deployment_experiments') AS t")).mappings().first()
    if not row or not row["t"]:
        pytest.skip("deployment_experiments missing")
    published = db.get_published_prompt_version(COLLECTIONS_BOT_ID)
    if published is None:
        pytest.skip("no published collections prompt")
    canary_id = f"DEP-CANARY-{uuid.uuid4().hex[:8]}"
    baseline_id = f"DEP-BASE-{uuid.uuid4().hex[:8]}"
    db_tx.execute(
        text(
            """
            UPDATE bot_deployments
               SET status = 'retired', updated_at = now()
             WHERE bot_id = :b AND environment = 'production' AND status = 'active'
            """
        ),
        {"b": COLLECTIONS_BOT_ID},
    )
    for dep_id, status, pct in ((baseline_id, "retired", 100), (canary_id, "active", 10)):
        db_tx.execute(
            text(
                """
                INSERT INTO bot_deployments (
                  id, bot_id, prompt_version_id, tts_voice_id, environment, status,
                  traffic_pct, shadow, published_at, created_at, updated_at
                ) VALUES (
                  :id, :b, :pv, 'en-IN-NeerjaNeural', 'production', :st, :pct,
                  false, now(), now(), now()
                )
                """
            ),
            {
                "id": dep_id,
                "b": COLLECTIONS_BOT_ID,
                "pv": published["id"],
                "st": status,
                "pct": pct,
            },
        )
    recorded = record_experiment(
        db_tx,
        bot_id=COLLECTIONS_BOT_ID,
        canary_deployment_id=canary_id,
        baseline_deployment_id=baseline_id,
        traffic_pct=10,
        shadow=False,
        auto_rollback=["slo_miss"],
    )
    assert recorded is not None
    rollback_experiment(recorded["id"], reason="slo_miss")
    entry = db_tx.execute(
        text(
            """
            SELECT actor_user_id, payload FROM audit_log
             WHERE action = 'agent.experiment_rollback'
               AND entity_id = :b
             ORDER BY created_at DESC LIMIT 1
            """
        ),
        {"b": COLLECTIONS_BOT_ID},
    ).mappings().first()
    assert entry is not None
    assert entry["actor_user_id"]
    payload = entry["payload"] if isinstance(entry["payload"], dict) else json.loads(entry["payload"])
    assert payload.get("actorUserId")
    assert payload.get("experimentId") == recorded["id"]


def test_publish_refuses_an_archived_card(cloned_bot: str) -> None:
    version_id = db.get_agent_studio_card(cloned_bot)["draftVersionId"]
    db.archive_agent_studio_card(cloned_bot)
    with pytest.raises(ValueError, match="bot_archived"):
        db.publish_prompt_version(version_id, "archived must not ship")


@pytest.fixture
def cloned_bot(db_tx):
    from agent_core.cards.clone import clone_card

    from tests.test_agent_change_log import _reset_chain_head

    _reset_chain_head()
    row = clone_card(template_id="hardship", name=f"CL {uuid.uuid4().hex[:6]}")
    bot_id = row["botId"]
    yield bot_id
    _reset_chain_head()
    with db.engine.begin() as conn:
        conn.execute(text("DELETE FROM audit_log WHERE entity_id = :b"), {"b": bot_id})
        conn.execute(text("DELETE FROM bot_deployments WHERE bot_id = :b"), {"b": bot_id})
        conn.execute(text("DELETE FROM prompt_versions WHERE bot_id = :b"), {"b": bot_id})
        conn.execute(text("DELETE FROM bots WHERE id = :b"), {"b": bot_id})
