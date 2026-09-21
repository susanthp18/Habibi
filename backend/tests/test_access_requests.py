"""Access requests: Viewer asks, Admin grants a role."""

from __future__ import annotations

import uuid
from contextlib import contextmanager

import pytest
from sqlalchemy import text

import actor_context
import db_access_requests
import entra
from tests.entra_columns import ensure_entra_user_columns, ensure_relation

TID = "9f2e2b7d-6081-4b3a-b7f5-433b581f6a5f"


def _ensure_schema(conn) -> None:
    ensure_entra_user_columns(conn)
    ensure_relation(conn, "public.operator_access_requests")
    tenant = conn.execute(text("SELECT id FROM tenants ORDER BY created_at LIMIT 1")).scalar()
    if tenant:
        conn.execute(
            text(
                """
                INSERT INTO roles (id, tenant_id, name)
                SELECT 'role-viewer', :t, 'Viewer'
                WHERE NOT EXISTS (SELECT 1 FROM roles WHERE id = 'role-viewer')
                """
            ),
            {"t": tenant},
        )
        conn.execute(
            text(
                """
                INSERT INTO roles (id, tenant_id, name)
                SELECT 'role-agent', :t, 'Agent'
                WHERE NOT EXISTS (SELECT 1 FROM roles WHERE id = 'role-agent')
                """
            ),
            {"t": tenant},
        )


def _claims(*, oid: str, upn: str, name: str) -> dict:
    return {
        "oid": oid,
        "tid": TID,
        "preferred_username": upn,
        "name": name,
        "ver": "2.0",
        "scp": "access_as_user",
    }


@contextmanager
def _as(user_id: str):
    token = actor_context.set_actor_user_id(user_id)
    try:
        yield
    finally:
        actor_context.reset_actor_user_id(token)


@pytest.fixture
def access_ready(db_tx, monkeypatch: pytest.MonkeyPatch):
    _ensure_schema(db_tx)
    monkeypatch.setenv("ENTRA_BOOTSTRAP_ADMIN_UPNS", "susanth.p@bigtapp.ai")
    monkeypatch.delenv("SMTP_ENABLED", raising=False)
    monkeypatch.setattr("invite_mail.send_access_request_email", lambda **kwargs: None)
    return db_tx


def test_create_and_list(access_ready) -> None:
    viewer_id = entra.provision_user(
        _claims(oid=str(uuid.uuid4()), upn="alex@bigtapp.ai", name="Alex")
    )
    with _as(viewer_id):
        body = db_access_requests.create_access_request(
            "/billing", "Need spend figures for the weekly review.", "perm-billing-read"
        )
    req = body["request"]
    assert req["status"] == "pending"
    assert req["pagePath"] == "/billing"
    assert req["permission"] == "perm-billing-read"
    assert req["userId"] == viewer_id
    listed = db_access_requests.list_access_requests()["requests"]
    assert any(item["id"] == req["id"] for item in listed)


def test_duplicate_pending_is_refused(access_ready) -> None:
    viewer_id = entra.provision_user(
        _claims(oid=str(uuid.uuid4()), upn="alex@bigtapp.ai", name="Alex")
    )
    with _as(viewer_id):
        db_access_requests.create_access_request(
            "/billing", "Need spend figures for the weekly review."
        )
        with pytest.raises(ValueError, match="already_pending"):
            db_access_requests.create_access_request(
                "/billing", "Asking again for the same page access."
            )


def test_short_reason_is_refused(access_ready) -> None:
    viewer_id = entra.provision_user(
        _claims(oid=str(uuid.uuid4()), upn="alex@bigtapp.ai", name="Alex")
    )
    with _as(viewer_id):
        with pytest.raises(ValueError, match="invalid_reason"):
            db_access_requests.create_access_request("/billing", "need it")


def test_approve_unions_the_role(access_ready) -> None:
    viewer_id = entra.provision_user(
        _claims(oid=str(uuid.uuid4()), upn="alex@bigtapp.ai", name="Alex")
    )
    admin_id = entra.provision_user(
        _claims(oid=str(uuid.uuid4()), upn="susanth.p@bigtapp.ai", name="Susanth P")
    )
    with _as(viewer_id):
        req = db_access_requests.create_access_request(
            "/roles", "Need to see who is on the floor this week.", "perm-admin-write"
        )["request"]
    with _as(admin_id):
        approved = db_access_requests.approve_access_request(req["id"], "role-agent")["request"]
    assert approved["status"] == "approved"
    assert approved["grantedRoleName"] == "Agent"
    roles = {
        r[0]
        for r in access_ready.execute(
            text(
                "SELECT r.name FROM user_roles ur JOIN roles r ON r.id = ur.role_id "
                "WHERE ur.user_id = :id"
            ),
            {"id": viewer_id},
        )
    }
    assert roles == {"Agent"}


def test_approve_reactivates_inactive_operator(access_ready) -> None:
    import db_users

    viewer_id = entra.provision_user(
        _claims(oid=str(uuid.uuid4()), upn="alex@bigtapp.ai", name="Alex")
    )
    admin_id = entra.provision_user(
        _claims(oid=str(uuid.uuid4()), upn="susanth.p@bigtapp.ai", name="Susanth P")
    )
    with _as(viewer_id):
        req = db_access_requests.create_access_request(
            "/roles", "Need to see who is on the floor this week.", "perm-admin-write"
        )["request"]
    with _as(admin_id):
        db_users.patch_user_status(viewer_id, "inactive")
        approved = db_access_requests.approve_access_request(req["id"], "role-agent")["request"]
    assert approved["status"] == "approved"
    status = access_ready.execute(
        text("SELECT status FROM users WHERE id = :id"), {"id": viewer_id}
    ).scalar()
    assert status == "active"


def test_deny_leaves_roles_alone(access_ready) -> None:
    viewer_id = entra.provision_user(
        _claims(oid=str(uuid.uuid4()), upn="alex@bigtapp.ai", name="Alex")
    )
    admin_id = entra.provision_user(
        _claims(oid=str(uuid.uuid4()), upn="susanth.p@bigtapp.ai", name="Susanth P")
    )
    with _as(viewer_id):
        req = db_access_requests.create_access_request(
            "/integrations", "Need to check a connector for a demo."
        )["request"]
    with _as(admin_id):
        denied = db_access_requests.deny_access_request(req["id"])["request"]
    assert denied["status"] == "denied"
    with pytest.raises(ValueError, match="request_not_pending"):
        with _as(admin_id):
            db_access_requests.deny_access_request(req["id"])


def test_access_request_mail_body(monkeypatch: pytest.MonkeyPatch) -> None:
    import invite_mail

    monkeypatch.setenv("PUBLIC_BASE_URL", "https://beeonixpayint.bigtapp.net")
    monkeypatch.setenv("HABIBI_DEPLOYED", "1")
    monkeypatch.delenv("HABIBI_BASE", raising=False)
    subject, text, html = invite_mail.render_access_request(
        requester_name="Alex",
        requester_email="alex@bigtapp.ai",
        page_path="/billing",
        permission_label="View spend, invoices and budgets",
        reason="Need the weekly spend pack.",
    )
    assert "Alex" in subject
    assert "/billing" in text
    assert "Need the weekly spend pack." in text
    assert "https://beeonixpayint.bigtapp.net/app/settings" in text
    assert "Review in Settings" in html
    assert 'href="https://beeonixpayint.bigtapp.net/app/settings"' in html
