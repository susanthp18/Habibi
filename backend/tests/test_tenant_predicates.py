"""One tenant must not reach another tenant's row through a handler.

Every tenant predicate in this codebase is written by hand. ``rls.py`` exists to
move that last line of defence into Postgres -- it derives 221 policies from the
foreign-key graph, and CI proves enforcement against a scratch database
(``.github/workflows/backend-pytest.yml`` sets ``RLS_DATABASE_URL``). But RLS is
not switched on in any running deployment: the application connects as a
superuser with BYPASSRLS, so policies would be ignored even if installed.
Turning it on means provisioning a non-superuser role (``rls.provision_role``)
and repointing ``DATABASE_URL`` for api, voice and workers -- a deployment
decision, held separately from this file.

Until then the hand-written predicate is the only thing between two tenants, and
an audit found seven places it was missing. So these tests do not check that a
predicate is *present in the source*; they call the real handler as one tenant
against another tenant's row and assert that nothing happened. A grep for
``tenant_id`` passes on a predicate sitting in a comment. This does not.

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


# ---------------------------------------------------------------------------
# OUTBOUND-05 -- the Outbound tab's Start/Pause button
# ---------------------------------------------------------------------------


def _rival_campaign(conn, *, status: str = "paused") -> str:
    _other_tenant(conn)
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
