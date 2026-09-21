"""Operator invites: first-login role, refuse existing SSO users, mail body."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

import db_invites
import entra
from tests.entra_columns import ensure_entra_user_columns, ensure_relation

TID = "9f2e2b7d-6081-4b3a-b7f5-433b581f6a5f"


def _ensure_schema(conn) -> None:
    ensure_entra_user_columns(conn)
    ensure_relation(conn, "public.operator_invites")
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


@pytest.fixture
def invites_ready(db_tx, monkeypatch: pytest.MonkeyPatch):
    _ensure_schema(db_tx)
    monkeypatch.setenv("ENTRA_BOOTSTRAP_ADMIN_UPNS", "susanth.p@bigtapp.ai")
    monkeypatch.delenv("SMTP_ENABLED", raising=False)
    monkeypatch.setattr("invite_mail.send_invite_email", lambda **kwargs: None)
    return db_tx


def test_invalid_email_is_refused(invites_ready) -> None:
    with pytest.raises(ValueError, match="invalid_email"):
        db_invites.create_invite("not-an-email", "role-viewer")
    with pytest.raises(ValueError, match="invalid_email"):
        db_invites.create_invite("someone@gmail.com", "role-viewer")


def test_create_invite_pending_without_smtp(invites_ready) -> None:
    body = db_invites.create_invite("alex@bigtapp.ai", "role-viewer")
    invite = body["invite"]
    assert invite["email"] == "alex@bigtapp.ai"
    assert invite["status"] == "pending"
    assert invite["roleName"] == "Viewer"
    listed = db_invites.list_invites()["invites"]
    assert any(i["id"] == invite["id"] for i in listed)


def test_invite_refused_when_already_signed_in(invites_ready) -> None:
    oid = str(uuid.uuid4())
    entra.provision_user(_claims(oid=oid, upn="alex@bigtapp.ai", name="Alex"))
    invites_ready.execute(
        text("INSERT INTO user_roles (user_id, role_id) VALUES (:id, 'role-viewer')"),
        {"id": oid},
    )
    with pytest.raises(ValueError, match="already_signed_in"):
        db_invites.create_invite("alex@bigtapp.ai", "role-agent")


def test_invite_uninvited_operator_grants_role_and_emails(invites_ready) -> None:
    oid = str(uuid.uuid4())
    entra.provision_user(_claims(oid=oid, upn="alex@bigtapp.ai", name="Alex"))
    body = db_invites.create_invite("alex@bigtapp.ai", "role-agent")
    assert body["invite"]["status"] == "accepted"
    roles = {
        r[0]
        for r in invites_ready.execute(
            text(
                "SELECT r.name FROM user_roles ur JOIN roles r ON r.id = ur.role_id "
                "WHERE ur.user_id = :id"
            ),
            {"id": oid},
        )
    }
    assert roles == {"Agent"}


def test_invite_inactive_operator_emails_and_restores(invites_ready) -> None:
    oid = str(uuid.uuid4())
    entra.provision_user(_claims(oid=oid, upn="alex@bigtapp.ai", name="Alex"))
    invites_ready.execute(
        text("INSERT INTO user_roles (user_id, role_id) VALUES (:id, 'role-viewer')"),
        {"id": oid},
    )
    invites_ready.execute(text("UPDATE users SET status = 'inactive' WHERE id = :id"), {"id": oid})
    body = db_invites.create_invite("alex@bigtapp.ai", "role-agent")
    assert body["invite"]["status"] == "accepted"
    assert body["invite"]["roleName"] == "Agent"
    status = invites_ready.execute(
        text("SELECT status FROM users WHERE id = :id"), {"id": oid}
    ).scalar()
    assert status == "active"
    roles = {
        r[0]
        for r in invites_ready.execute(
            text(
                "SELECT r.name FROM user_roles ur JOIN roles r ON r.id = ur.role_id "
                "WHERE ur.user_id = :id"
            ),
            {"id": oid},
        )
    }
    assert roles == {"Agent"}


def test_inactive_login_consumes_pending_invite(invites_ready, monkeypatch: pytest.MonkeyPatch) -> None:
    from db_core import _tenant

    monkeypatch.setenv("AUTHZ_ENFORCE", "1")
    oid = str(uuid.uuid4())
    entra.provision_user(_claims(oid=oid, upn="parked@bigtapp.ai", name="Parked"))
    invites_ready.execute(
        text("INSERT INTO user_roles (user_id, role_id) VALUES (:id, 'role-viewer')"),
        {"id": oid},
    )
    invites_ready.execute(text("UPDATE users SET status = 'inactive' WHERE id = :id"), {"id": oid})
    invite_id = f"INV-{uuid.uuid4().hex[:12]}"
    invites_ready.execute(
        text(
            """
            INSERT INTO operator_invites (
                id, tenant_id, email, role_id, status, sent_at
            ) VALUES (
                :id, :t, 'parked@bigtapp.ai', 'role-agent', 'pending', now()
            )
            """
        ),
        {"t": _tenant(), "id": invite_id},
    )
    import authz

    authz.invalidate_permission_cache(oid)
    entra.provision_user(_claims(oid=oid, upn="parked@bigtapp.ai", name="Parked"))
    status = invites_ready.execute(
        text("SELECT status FROM users WHERE id = :id"), {"id": oid}
    ).scalar()
    assert status == "active"
    roles = {
        r[0]
        for r in invites_ready.execute(
            text(
                "SELECT r.name FROM user_roles ur JOIN roles r ON r.id = ur.role_id "
                "WHERE ur.user_id = :id"
            ),
            {"id": oid},
        )
    }
    assert roles == {"Agent"}
    invite_status = invites_ready.execute(
        text("SELECT status FROM operator_invites WHERE id = :id"),
        {"id": invite_id},
    ).scalar()
    assert invite_status == "accepted"
    assert authz.ANALYTICS_READ in authz.actor_permissions(oid)


def test_first_login_consumes_invite_role(invites_ready) -> None:
    db_invites.create_invite("alex@bigtapp.ai", "role-agent")
    oid = str(uuid.uuid4())
    user_id = entra.provision_user(_claims(oid=oid, upn="alex@bigtapp.ai", name="Alex"))
    roles = {
        r[0]
        for r in invites_ready.execute(
            text(
                "SELECT r.name FROM user_roles ur JOIN roles r ON r.id = ur.role_id "
                "WHERE ur.user_id = :id"
            ),
            {"id": user_id},
        )
    }
    assert roles == {"Agent"}
    status = invites_ready.execute(
        text("SELECT status FROM operator_invites WHERE lower(email) = 'alex@bigtapp.ai'")
    ).scalar()
    assert status == "accepted"


def test_bootstrap_upn_wins_over_viewer_invite(
    invites_ready, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ENTRA_BOOTSTRAP_ADMIN_UPNS", "bootstrap-test@bigtapp.ai")
    db_invites.create_invite("bootstrap-test@bigtapp.ai", "role-viewer")
    oid = str(uuid.uuid4())
    user_id = entra.provision_user(
        _claims(oid=oid, upn="bootstrap-test@bigtapp.ai", name="Bootstrap Test")
    )
    roles = {
        r[0]
        for r in invites_ready.execute(
            text(
                "SELECT r.name FROM user_roles ur JOIN roles r ON r.id = ur.role_id "
                "WHERE ur.user_id = :id"
            ),
            {"id": user_id},
        )
    }
    assert "Admin" in roles
    status = invites_ready.execute(
        text("SELECT status FROM operator_invites WHERE lower(email) = 'bootstrap-test@bigtapp.ai'")
    ).scalar()
    assert status == "accepted"


def test_invite_mail_body_carries_brand(monkeypatch: pytest.MonkeyPatch) -> None:
    import invite_mail

    monkeypatch.setenv("PUBLIC_BASE_URL", "https://beeonixpayint.bigtapp.net")
    monkeypatch.setenv("HABIBI_DEPLOYED", "1")
    monkeypatch.delenv("HABIBI_BASE", raising=False)
    subject, text, html = invite_mail.render_invite(
        to_email="alex@bigtapp.ai", role_name="Viewer", inviter_name="Susanth P"
    )
    assert subject == "You're invited to PayInt"
    assert "Viewer" in text
    assert "https://beeonixpayint.bigtapp.net/app/login" in text
    assert "https://beeonixpayint.bigtapp.net/" in text
    assert "Product page" in html
    assert 'href="https://beeonixpayint.bigtapp.net/"' in html
    assert "PayInt" in html
    assert "Beeonix" in html
    assert "Open PayInt" in html
    assert "login-bee.jpg" in html
    assert "bigtapp.png" in html


def test_send_invite_email_uses_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    import smtplib

    import invite_mail

    sent: dict[str, object] = {}

    class FakeSmtp:
        def __init__(self, *args, **kwargs):
            sent["host"] = args[0] if args else kwargs.get("host")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def ehlo(self):
            return None

        def starttls(self, context=None):
            sent["tls"] = True

        def login(self, username, password):
            sent["user"] = username

        def sendmail(self, from_addr, to_addrs, msg):
            sent["from"] = from_addr
            sent["to"] = to_addrs
            sent["msg"] = msg

    monkeypatch.setenv("SMTP_ENABLED", "true")
    monkeypatch.setenv("SMTP_HOST", "smtp.office365.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USE_TLS", "true")
    monkeypatch.setenv("SMTP_USERNAME", "alerts@bigtapp.ai")
    monkeypatch.setenv("SMTP_PASSWORD", "unused")
    monkeypatch.setenv("SMTP_FROM_EMAIL", "alerts@bigtapp.ai")
    monkeypatch.setenv("SMTP_FROM_NAME", "PayInt")
    monkeypatch.setattr(smtplib, "SMTP", FakeSmtp)
    err = invite_mail.send_invite_email(
        to_email="alex@bigtapp.ai", role_name="Viewer", inviter_name="Susanth P"
    )
    assert err is None
    assert sent["to"] == ["alex@bigtapp.ai"]
    assert sent["user"] == "alerts@bigtapp.ai"
    assert "PayInt" in sent["msg"]
