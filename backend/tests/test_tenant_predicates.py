"""One tenant must not reach another tenant's row through a handler.

Every tenant predicate in this codebase is written by hand. ``rls.py`` exists to
move that last line of defence into Postgres -- it derives 221 policies from the
foreign-key graph, and CI proves enforcement against a scratch database
(``.github/workflows/backend-pytest.yml`` sets ``RLS_DATABASE_URL``). The
application login is ``NOBYPASSRLS`` (``collections_app``); owner/DDL is
``MIGRATION_DATABASE_URL`` only. Closer/QA/reaper keep per-tenant GUC /
``SET LOCAL``, not a god role.

Until then the hand-written predicate is the only thing between two tenants, and
an audit found seven places it was missing. So these tests do not check that a
predicate is *present in the source*; they call the real handler as one tenant
against another tenant's row and assert that nothing happened. A grep for
``tenant_id`` passes on a predicate sitting in a comment. This does not.

**2026-09-11: RLS is on.** The application connects as ``collections_app`` and
Postgres enforces the derived policies (migration 0126). That changes how the
rival's rows are *made*: a ``WITH CHECK`` policy refuses an INSERT for another
tenant, so every rival fixture writes under :func:`_acting_as` -- ``SET
LOCAL`` of the tenant GUC, the same thing the request layer does per call. The
assertions are unchanged, and now hold twice over: the ``WHERE`` and the
policy each refuse on their own. ``test_the_policy_holds_without_the_where``
is the proof that the second layer is real.

Each write case asserts two things, and the second is load-bearing: that the
call returned nothing, **and** that the victim's row is unchanged.
``upsert_partner`` is why -- its cross-tenant call used to succeed and return a
plausible object, so only re-reading the victim's row catches it.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import text

import db

OTHER = "rival.bank"

_PEM = "-----BEGIN CERTIFICATE-----\nMIIByjCCAXCgAwIBAgI=\n-----END CERTIFICATE-----"


def _other_tenant(conn) -> str:
    conn.execute(
        text("INSERT INTO tenants (id, name) VALUES (:t, 'Rival Bank')"),
        {"t": OTHER},
    )
    return OTHER


from tests.conftest import acting_as as _acting_as  # noqa: E402


# ---------------------------------------------------------------------------
# OUTBOUND-05 -- the Outbound tab's Start/Pause button
# ---------------------------------------------------------------------------


def _rival_campaign(conn, *, status: str = "paused") -> str:
    _other_tenant(conn)
    with _acting_as(conn, OTHER):
        conn.execute(
            text(
                """
                INSERT INTO campaign_runs (id, tenant_id, name, objective, status)
                VALUES ('run-rival', :t, 'Rival Chase', 'dpd_reminder', :s)
                """
            ),
            {"t": OTHER, "s": status},
        )
    return "run-rival"


def test_a_campaign_cannot_be_started_by_another_tenant(db_tx) -> None:
    import campaigns

    run_id = _rival_campaign(db_tx, status="paused")

    got = campaigns.set_status(
        db_tx, run_id, campaigns.STATUS_RUNNING, tenant_id=db.current_tenant()
    )

    assert got is None, "the update reported success against another tenant's run"
    with _acting_as(db_tx, OTHER):
        still = (
            db_tx.execute(
                text("SELECT status, started_at FROM campaign_runs WHERE id = :i"),
                {"i": run_id},
            )
            .mappings()
            .first()
        )
    assert still["status"] == "paused"
    assert still["started_at"] is None, "a cross-tenant start stamped started_at"


def test_a_campaign_cannot_be_cancelled_by_another_tenant(db_tx) -> None:
    """Cancel is the irreversible one -- it stamps finished_at."""
    import campaigns

    run_id = _rival_campaign(db_tx, status="running")

    got = campaigns.set_status(
        db_tx, run_id, campaigns.STATUS_CANCELLED, tenant_id=db.current_tenant()
    )

    assert got is None
    with _acting_as(db_tx, OTHER):
        still = (
            db_tx.execute(
                text("SELECT status, finished_at FROM campaign_runs WHERE id = :i"),
                {"i": run_id},
            )
            .mappings()
            .first()
        )
    assert still["status"] == "running"
    assert still["finished_at"] is None


def test_a_rivals_borrower_cannot_be_added_to_my_run(db_tx) -> None:
    """`add_targets` took a run id and a customer id and joined neither to
    the caller's tenant: one tenant's list upload could put another bank's
    borrower on its dialler."""
    import campaigns

    cid = _rival_customer(db_tx)
    run = campaigns.create(
        db_tx, tenant_id=db.current_tenant(), name="Mine", objective="dpd_reminder"
    )

    added = campaigns.add_targets(db_tx, run["id"], [cid], tenant_id=db.current_tenant())

    assert added == 0
    total = db_tx.execute(
        text("SELECT count(*) FROM campaign_targets WHERE run_id = :i"), {"i": run["id"]}
    ).scalar()
    assert total == 0


def test_a_rivals_run_cannot_be_given_targets(db_tx) -> None:
    import campaigns

    run_id = _rival_campaign(db_tx, status="draft")
    cid = db_tx.execute(
        text("SELECT id FROM customers WHERE tenant_id = :t LIMIT 1"), {"t": db.current_tenant()}
    ).scalar()

    with pytest.raises(KeyError):
        campaigns.add_targets(db_tx, run_id, [cid], tenant_id=db.current_tenant())


def test_a_campaign_the_tenant_owns_still_starts(db_tx) -> None:
    """The other half of the rule: the predicate must not break the normal path."""
    import campaigns

    db_tx.execute(
        text(
            """
            INSERT INTO campaign_runs (id, tenant_id, name, objective, status)
            VALUES ('run-mine', :t, 'My Chase', 'dpd_reminder', 'paused')
            """
        ),
        {"t": db.current_tenant()},
    )

    got = campaigns.set_status(
        db_tx, "run-mine", campaigns.STATUS_RUNNING, tenant_id=db.current_tenant()
    )

    assert got is not None
    assert got["status"] == campaigns.STATUS_RUNNING


# ---------------------------------------------------------------------------
# AUTHZ-5 -- an mTLS trust record
# ---------------------------------------------------------------------------


def _rival_partner(conn) -> str:
    _other_tenant(conn)
    with _acting_as(conn, OTHER):
        # The partner's bot must be the rival's too: `bots` is tenant-scoped
        # and the policy on a2a_partners is checked against the row's own
        # tenant, not its bot's, so a rival partner naming our bot is a row
        # the rival may write. It is what the finding described.
        conn.execute(
            text(
                """
                INSERT INTO a2a_partners
                  (id, tenant_id, name, card_url, cert_fingerprint, cert_dn,
                   allowed_skills, status, bot_id)
                VALUES
                  ('a2a-p-rival', :t, 'Rival Partner', 'https://rival.example/card',
                   'sha256:rival-fingerprint', 'CN=rival', CAST(:sk AS text[]),
                   'active', 'kaia-v2-4')
                """
            ),
            {"t": OTHER, "sk": ["read_only"]},
        )
    return "a2a-p-rival"


def test_a_partner_certificate_cannot_be_rewritten_by_another_tenant(db_tx) -> None:
    from agent_core import a2a

    pid = _rival_partner(db_tx)

    with pytest.raises(ValueError, match="another_tenant"):
        a2a.upsert_partner(
            {
                "id": pid,
                "name": "Impostor",
                "certPem": _PEM,
                "certDn": "CN=impostor",
                "botId": "kaia-v2-4",
                "allowedSkills": ["transfer_funds"],
            }
        )

    with _acting_as(db_tx, OTHER):
        row = (
            db_tx.execute(
                text(
                    "SELECT name, cert_dn, cert_fingerprint, allowed_skills "
                    "FROM a2a_partners WHERE id = :i"
                ),
                {"i": pid},
            )
            .mappings()
            .first()
        )
    assert row["name"] == "Rival Partner"
    assert row["cert_dn"] == "CN=rival"
    assert row["cert_fingerprint"] == "sha256:rival-fingerprint"
    assert list(row["allowed_skills"]) == ["read_only"]


def test_a_skill_name_with_a_comma_stays_one_allowed_skill(db_tx) -> None:
    """CONNECTORS-12's shape, landing in an allowlist.

    A Postgres array *literal* built as ``"{" + ",".join(names) + "}"`` splits a
    name carrying a comma into two elements. Bound as a list it does not.
    """
    from agent_core import a2a

    partner = a2a.upsert_partner(
        {
            "id": "a2a-p-comma",
            "name": "Mine",
            "certPem": _PEM,
            "certDn": "CN=mine",
            "botId": "kaia-v2-4",
            "allowedSkills": ["read_only,transfer_funds"],
        }
    )

    stored = db_tx.execute(
        text("SELECT allowed_skills FROM a2a_partners WHERE id = :i"),
        {"i": partner["id"]},
    ).scalar()
    assert list(stored) == ["read_only,transfer_funds"], (
        "a comma split one skill name into two allowlist entries"
    )


# ---------------------------------------------------------------------------
# EVALS-13 -- the report body, tenant_id included
# ---------------------------------------------------------------------------


def test_an_eval_report_is_not_readable_across_tenants(db_tx) -> None:
    from fastapi.testclient import TestClient

    import main

    _other_tenant(db_tx)
    with _acting_as(db_tx, OTHER):
        db_tx.execute(
            text(
                """
                INSERT INTO eval_suites (id, tenant_id, name, kind)
                VALUES ('suite-rival', :t, 'Rival Regression', 'regression')
                """
            ),
            {"t": OTHER},
        )
        db_tx.execute(
            text(
                """
                INSERT INTO eval_reports (id, tenant_id, suite_id, bot_id, status, summary)
                VALUES ('rep-rival', :t, 'suite-rival', 'kaia-v2-4', 'pass',
                        CAST(:s AS jsonb))
                """
            ),
            {"t": OTHER, "s": json.dumps({"passed": 9})},
        )

    with TestClient(main.app) as client:
        resp = client.get("/eval/reports/rep-rival")

    assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------------------
# AUTHZ-11 -- version-level writes
# ---------------------------------------------------------------------------


def _rival_draft(conn) -> str:
    _other_tenant(conn)
    with _acting_as(conn, OTHER):
        conn.execute(
            text(
                """
                INSERT INTO prompt_versions
                  (id, tenant_id, bot_id, label, status, prompt)
                VALUES ('pv-rival', :t, 'kaia-v2-4', 'Rival draft', 'draft', 'hello')
                """
            ),
            {"t": OTHER},
        )
    return "pv-rival"


def test_a_draft_cannot_be_patched_by_another_tenant(db_tx) -> None:
    import db_prompt_studio

    vid = _rival_draft(db_tx)

    with pytest.raises(KeyError):
        db_prompt_studio.patch_prompt_version(vid, {"prompt": "rewritten"})

    with _acting_as(db_tx, OTHER):
        assert (
            db_tx.execute(
                text("SELECT prompt FROM prompt_versions WHERE id = :i"), {"i": vid}
            ).scalar()
            == "hello"
        )


def test_a_draft_cannot_be_discarded_by_another_tenant(db_tx) -> None:
    import db_prompt_studio

    vid = _rival_draft(db_tx)

    with pytest.raises(KeyError):
        db_prompt_studio.discard_prompt_version(vid)

    with _acting_as(db_tx, OTHER):
        assert (
            db_tx.execute(
                text("SELECT status FROM prompt_versions WHERE id = :i"), {"i": vid}
            ).scalar()
            == "draft"
        )


# ---------------------------------------------------------------------------
# GRAPH-5 -- G5's allowlist of legal handoff targets
# ---------------------------------------------------------------------------


def test_a_handoff_to_another_tenants_bot_does_not_pass_g5(db_tx) -> None:
    """Through the gate, not through the helper.

    ``list_bot_ids`` read every row in ``bots``, so a card could name another
    tenant's bot as a handoff target and G5 -- the gate whose whole job is to
    refuse a target that does not exist -- reported it as a known bot. Asserting
    on ``list_bot_ids`` alone would pass even if the gate stopped consulting it,
    which is the mistake GUARDRAILS-1 was green on for months.
    """
    import db_prompt_studio

    _other_tenant(db_tx)
    with _acting_as(db_tx, OTHER):
        db_tx.execute(
            text(
                "INSERT INTO bots (id, tenant_id, name, version) "
                "VALUES ('rival-bot-1', :t, 'Rival Bot', 'v1')"
            ),
            {"t": OTHER},
        )

    assert "rival-bot-1" not in db.list_bot_ids()

    from agent_core.cards.defaults import COLLECTIONS_BOT_ID, card_dump

    card = card_dump(COLLECTIONS_BOT_ID)
    card["handoffs"] = [
        {"to_bot_id": "rival-bot-1", "when": "the caller mentions a rival"}
    ]

    report = db_prompt_studio.compile_agent_studio_card(
        COLLECTIONS_BOT_ID, card_raw=card
    )
    g5 = next(g for g in report["gates"] if g["gate"] == "G5")
    assert g5["status"] == "fail", g5


# ---------------------------------------------------------------------------
# The second half: the reads and writes the first sweep did not reach
# ---------------------------------------------------------------------------


def _rival_customer(conn) -> str:
    _other_tenant(conn)
    with _acting_as(conn, OTHER):
        conn.execute(
            text(
                """
                INSERT INTO customers (id, tenant_id, name, segment, risk, dnd)
                VALUES ('cust-rival-1', :t, 'Rival Borrower', 'retail', 'medium', false)
                """
            ),
            {"t": OTHER},
        )
    return "cust-rival-1"


def test_the_inbox_does_not_list_another_tenants_conversation(db_tx) -> None:
    """`conversations` carries no tenant column; the customer it belongs to
    does, and the Inbox list joined the customer and never asked."""
    import db_inbox

    cid = _rival_customer(db_tx)
    with _acting_as(db_tx, OTHER):
        db_tx.execute(
            text(
                "INSERT INTO bots (id, tenant_id, name, version) "
                "VALUES ('rival-bot-2', :t, 'Rival Bot', 'v1')"
            ),
            {"t": OTHER},
        )
        db_tx.execute(
            text(
                """
                INSERT INTO interactions
                  (id, tenant_id, customer_id, handler_kind, handler_bot_id, channel, status)
                VALUES ('int-rival-1', :t, :c, 'bot', 'rival-bot-2', 'whatsapp', 'active')
                """
            ),
            {"t": OTHER, "c": cid},
        )
        db_tx.execute(
            text(
                """
                INSERT INTO conversations (id, interaction_id, customer_id, status, channel)
                VALUES ('conv-rival-1', 'int-rival-1', :c, 'bot', 'whatsapp')
                """
            ),
            {"c": cid},
        )

    ids = {row["id"] for row in db_inbox.list_conversations()}
    assert "conv-rival-1" not in ids
    assert db_inbox.get_conversation("conv-rival-1") is None


def test_the_knowledge_base_does_not_answer_from_another_tenants_documents(db_tx) -> None:
    """The retrieval cache keyed on the tenant; the SQL under it did not."""
    _other_tenant(db_tx)
    with _acting_as(db_tx, OTHER):
        db_tx.execute(
            text(
                """
                INSERT INTO kb_documents (id, tenant_id, type, version, status, enabled, title, product_key)
                VALUES ('doc-rival-1', :t, 'policy', 'v1', 'indexed', true, 'Rival Policy', 'rival-product')
                """
            ),
            {"t": OTHER},
        )
        db_tx.execute(
            text(
                """
                INSERT INTO faq_pairs (id, linked_document_id, intent, question, answer, enabled)
                VALUES ('faq-rival-1', 'doc-rival-1', 'rival', 'What is the rival rate?', '99%', true)
                """
            )
        )
        # The trigger resolved the tenant from the linked document.
        assert (
            db_tx.execute(
                text("SELECT tenant_id FROM faq_pairs WHERE id = 'faq-rival-1'")
            ).scalar()
            == OTHER
        )

    import kb_retrieve

    # `catalog` is the corpus-shape read that walks kb_documents directly.
    keys = {row.get("product_key") for row in kb_retrieve.catalog()}
    assert "rival-product" not in keys


def test_a_ledger_entry_carries_its_tenant_by_default(db_tx) -> None:
    """Every writer inserts without a tenant today; the trigger supplies it, so
    the row is visible under a tenant predicate rather than to nobody."""
    row = db_tx.execute(
        text(
            """
            SELECT a.id AS account_id, c.tenant_id
            FROM accounts a JOIN customers c ON c.id = a.customer_id
            WHERE c.tenant_id = :t LIMIT 1
            """
        ),
        {"t": db.current_tenant()},
    ).mappings().first()
    assert row is not None
    db_tx.execute(
        text(
            """
            INSERT INTO ledger_entries (id, account_id, type, description, amount, posted_at)
            VALUES ('LED-tenant-probe', :a, 'fee', 'probe', 1, now())
            """
        ),
        {"a": row["account_id"]},
    )
    assert (
        db_tx.execute(
            text("SELECT tenant_id FROM ledger_entries WHERE id = 'LED-tenant-probe'")
        ).scalar()
        == row["tenant_id"]
    )


def test_billing_answers_for_the_callers_tenant_only(db_tx) -> None:
    from fastapi.testclient import TestClient

    import main

    _other_tenant(db_tx)
    with TestClient(main.app) as client:
        resp = client.get("/billing", params={"tenantId": OTHER})

    assert resp.status_code == 200, resp.text
    tenants = {t["id"] for t in resp.json().get("tenants") or []}
    assert OTHER not in tenants


def test_each_tenant_has_its_own_unknown_caller(db_tx) -> None:
    """One global sentinel meant a second tenant's unbound calls referenced the
    first tenant's customer row."""
    import db_core

    assert db_core.unknown_caller_id(db.current_tenant()) == "UNKNOWN-CALLER"
    assert db_core.unknown_caller_id(OTHER) == f"UNKNOWN-CALLER:{OTHER}"
    assert db_core.is_unknown_caller("UNKNOWN-CALLER")
    assert db_core.is_unknown_caller(f"UNKNOWN-CALLER:{OTHER}")
    assert not db_core.is_unknown_caller("UNKNOWN-CALLER-LIKE-NAME")
    assert not db_core.is_unknown_caller("cust-1")


def test_a_machine_write_is_not_audited_as_a_person(db_tx, monkeypatch) -> None:
    import actor_context
    import db_core

    probe = "probe-" + OTHER
    db_core._activity(db_tx, "customer", probe, "probe", "as a person")
    human = db_tx.execute(
        text(
            "SELECT actor_kind, actor_user_id FROM activity_events "
            "WHERE entity_id = :e AND kind = 'probe' ORDER BY created_at DESC LIMIT 1"
        ),
        {"e": probe},
    ).mappings().first()
    assert human["actor_kind"] == "human"
    assert human["actor_user_id"]

    actor_context.bind_service_actor("bot", bot_id="kaia-v2-4")
    try:
        db_core._activity(db_tx, "customer", probe, "probe-bot", "as a machine")
    finally:
        actor_context._actor_kind_var.set(None)
        actor_context._actor_bot_var.set(None)
    machine = db_tx.execute(
        text(
            "SELECT actor_kind, actor_user_id, actor_bot_id FROM activity_events "
            "WHERE entity_id = :e AND kind = 'probe-bot' ORDER BY created_at DESC LIMIT 1"
        ),
        {"e": probe},
    ).mappings().first()
    assert machine["actor_kind"] == "bot"
    assert machine["actor_user_id"] is None
    assert machine["actor_bot_id"] == "kaia-v2-4"


def test_a2a_headers_are_only_believed_from_the_terminator(monkeypatch) -> None:
    from agent_core import a2a

    monkeypatch.setenv("A2A_ENABLED", "true")
    monkeypatch.delenv("A2A_TRUSTED_PROXY_CIDRS", raising=False)
    headers = {"x-ssl-client-verify": "SUCCESS", "x-ssl-client-dn": "CN=partner"}
    with pytest.raises(PermissionError, match="a2a_untrusted_peer"):
        a2a.require_partner(headers, bot_id="kaia-v2-4", client_host="203.0.113.9")

    monkeypatch.setenv("A2A_TRUSTED_PROXY_CIDRS", "10.0.0.0/8, 127.0.0.1/32")
    assert a2a.peer_is_trusted_terminator("10.1.2.3")
    assert a2a.peer_is_trusted_terminator("127.0.0.1")
    assert not a2a.peer_is_trusted_terminator("203.0.113.9")
    assert not a2a.peer_is_trusted_terminator(None)


def test_the_policy_holds_without_the_where(db_tx) -> None:
    """Row-level security is the second layer, and this is the proof it is real.

    A bare SELECT with no tenant predicate at all -- the shape every finding
    in this file started as -- returns none of the rival's rows, because the
    connection runs as ``collections_app`` and the policy on ``campaign_runs``
    compares each row against the tenant GUC. If the application were still
    the owner, or the policy were not enabled, this would count one.
    """
    run_id = _rival_campaign(db_tx, status="paused")

    seen = db_tx.execute(
        text("SELECT count(*) FROM campaign_runs WHERE id = :i"), {"i": run_id}
    ).scalar()
    assert seen == 0, "the policy did not hide the rival's row from a bare SELECT"

    with _acting_as(db_tx, OTHER):
        assert (
            db_tx.execute(
                text("SELECT count(*) FROM campaign_runs WHERE id = :i"), {"i": run_id}
            ).scalar()
            == 1
        )

    role = db_tx.execute(text("SELECT current_user")).scalar()
    assert role != "collections", "the tests are running as the owner, which bypasses every policy"


def test_an_ended_run_cannot_be_restarted(db_tx) -> None:
    """OUTBOUND-20: only the disabled button stopped a cancelled run from
    being resumed; the endpoint took it."""
    import campaigns

    run = campaigns.create(db_tx, tenant_id=db.current_tenant(), name="Done", objective="dpd_reminder")
    campaigns.set_status(db_tx, run["id"], campaigns.STATUS_RUNNING, tenant_id=db.current_tenant())
    campaigns.set_status(db_tx, run["id"], campaigns.STATUS_CANCELLED, tenant_id=db.current_tenant())
    with pytest.raises(ValueError, match="campaign_transition_refused"):
        campaigns.set_status(db_tx, run["id"], campaigns.STATUS_RUNNING, tenant_id=db.current_tenant())
