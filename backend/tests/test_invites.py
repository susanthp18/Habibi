"""Operator invites: first-login role, refuse existing SSO users, mail body."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

import db_invites
import entra

TID = "9f2e2b7d-6081-4b3a-b7f5-433b581f6a5f"


def _ensure_schema(conn) -> None:
    conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS entra_oid UUID"))
    conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS entra_tid UUID"))
    conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS entra_upn TEXT"))
    conn.execute(
        text("ALTER TABLE users ADD COLUMN IF NOT EXISTS bootstrap_admin boolean NOT NULL DEFAULT false")
    )
    conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at timestamptz"))
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
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS operator_invites (
              id TEXT PRIMARY KEY,
              tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
              email TEXT NOT NULL,
              role_id TEXT NOT NULL REFERENCES roles(id),
              invited_by_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
              status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','accepted','revoked')),
              sent_at timestamptz NOT NULL DEFAULT now(),
              accepted_at timestamptz,
              last_error TEXT,
              created_at timestamptz NOT NULL DEFAULT now(),
              updated_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_operator_invites_pending_email
              ON operator_invites (tenant_id, lower(email))
              WHERE status = 'pending'
            """
        )
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
    with pytest.raises(ValueError, match="already_signed_in"):
        db_invites.create_invite("alex@bigtapp.ai", "role-agent")


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
