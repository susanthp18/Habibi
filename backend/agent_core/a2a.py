"""A2A 1.0 — serve our Agent Card over mTLS. Never on the audio path.

Skills on the card are *our* skill names, not MCP tools. A bearer token without
a client certificate is not enough.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from typing import Any

from sqlalchemy import text

import db
from agent_core.platform_flags import a2a_enabled
from agent_core.skills.pack import pack_for_slug

logger = logging.getLogger(__name__)


def client_cert_dn(headers: dict[str, str]) -> str | None:
    verify = (
        headers.get("x-ssl-client-verify")
        or headers.get("ssl-client-verify")
        or ""
    ).strip().upper()
    if verify not in {"SUCCESS", "OK", "TRUE", "1", "YES"}:
        return None
    dn = (headers.get("x-ssl-client-dn") or headers.get("ssl-client-s-dn") or "").strip()
    return dn or None


def fingerprint_dn(dn: str) -> str:
    return hashlib.sha256(dn.encode("utf-8")).hexdigest()


def require_partner(headers: dict[str, str]) -> dict[str, Any]:
    if not a2a_enabled():
        raise PermissionError("a2a_disabled")
    auth = (headers.get("authorization") or "").strip()
    dn = client_cert_dn({k.lower(): v for k, v in headers.items()})
    if not dn:
        if auth.lower().startswith("bearer "):
            raise PermissionError("a2a_mtls_required")
        raise PermissionError("a2a_mtls_required")
    fp = fingerprint_dn(dn)
    try:
        with db.engine.connect() as conn:
            row = db._one(
                conn.execute(
                    text(
                        """
                        SELECT * FROM a2a_partners
                         WHERE status = 'active'
                           AND (cert_fingerprint = :fp OR cert_dn = :dn)
                         ORDER BY CASE WHEN tenant_id = :t THEN 0 ELSE 1 END
                         LIMIT 1
                        """
                    ),
                    {"t": db.current_tenant(), "fp": fp, "dn": dn},
                )
            )
    except Exception:
        raise PermissionError("a2a_partner_unknown") from None
    if not row:
        raise PermissionError("a2a_partner_unknown")
    return dict(row)


def agent_card_document(bot_id: str) -> dict[str, Any]:
    """A2A Agent Card. Skills = skill names + descriptions."""
    card_row = db.get_agent_studio_card(bot_id)
    if card_row is None:
        raise KeyError("agent_card_not_found")
    raw = card_row.get("agentCard") or {}
    ident = raw.get("identity") if isinstance(raw.get("identity"), dict) else {}
    skills_out: list[dict[str, Any]] = []
    for ref in raw.get("skills") or []:
        if not isinstance(ref, dict):
            continue
        slug = str(ref.get("skill_id") or "")
        if not slug:
            continue
        desc = slug
        try:
            pack = pack_for_slug(slug)
            desc = pack.description or slug
        except KeyError:
            pass
        skills_out.append({"id": slug, "name": slug, "description": desc})
    return {
        "name": ident.get("display_name") or card_row.get("name"),
        "description": ident.get("purpose") or card_row.get("purpose") or "",
        "url": "/a2a",
        "version": card_row.get("version") or "1.0",
        "protocolVersion": "0.2.2",
        "capabilities": {"streaming": False, "pushNotifications": False},
        "defaultInputModes": ["application/json"],
        "defaultOutputModes": ["application/json"],
        "skills": skills_out,
        "authentication": {"schemes": ["mutualTLS"]},
        "provider": {"organization": "BigBound AI"},
    }


def create_task(
    *,
    partner: dict[str, Any],
    skill_id: str,
    payload: dict[str, Any],
    bot_id: str,
    cert_dn: str | None,
) -> dict[str, Any]:
    allowed = list(partner.get("allowed_skills") or partner.get("allowedSkills") or [])
    if hasattr(allowed, "tolist"):
        allowed = list(allowed)
    if allowed and skill_id not in allowed:
        raise PermissionError("a2a_skill_not_allowed")
    tid = f"a2a-{uuid.uuid4().hex[:12]}"
    status = "input-required" if payload.get("inputRequired") else "submitted"
    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO a2a_tasks (
                  id, tenant_id, partner_id, bot_id, skill_id, status, input, cert_dn
                ) VALUES (
                  :id, :t, :p, :b, :s, :st, CAST(:inp AS jsonb), :dn
                )
                """
            ),
            {
                "id": tid,
                "t": db.current_tenant(),
                "p": partner["id"],
                "b": bot_id,
                "s": skill_id,
                "st": status,
                "inp": db._jsonb(payload),
                "dn": cert_dn,
            },
        )
    if status == "submitted":
        _enqueue_work(tid, partner["id"], skill_id, payload)
    return get_task(tid) or {"id": tid, "status": status}


def _enqueue_work(task_id: str, partner_id: str, skill_id: str, payload: dict[str, Any]) -> None:
    """Work runtime only — never voice."""
    try:
        from work_runtime import idempotency_key, start_workflow

        start_workflow(
            workflow_type="a2a_remote",
            payload={"taskId": task_id, "partnerId": partner_id, "skillId": skill_id, "input": payload},
            customer_id=payload.get("customerId"),
            idempotency_key=idempotency_key(workflow_type="a2a_remote", trigger_ref=task_id),
        )
    except Exception:
        logger.exception("a2a enqueue failed")


def get_task(task_id: str) -> dict[str, Any] | None:
    with db.engine.connect() as conn:
        row = db._one(
            conn.execute(
                text("SELECT * FROM a2a_tasks WHERE id = :id AND tenant_id = :t"),
                {"id": task_id, "t": db.current_tenant()},
            )
        )
    return _map_task(row) if row else None


def list_tasks(*, limit: int = 50) -> list[dict[str, Any]]:
    with db.engine.connect() as conn:
        rows = db._rows(
            conn.execute(
                text(
                    """
                    SELECT * FROM a2a_tasks
                     WHERE tenant_id = :t
                     ORDER BY created_at DESC
                     LIMIT :n
                    """
                ),
                {"t": db.current_tenant(), "n": limit},
            )
        )
    return [_map_task(r) for r in rows]


def signal_task(task_id: str, name: str) -> dict[str, Any]:
    row = get_task(task_id)
    if row is None:
        raise KeyError("a2a_task_not_found")
    nxt = "submitted" if name == "approve" else "cancelled"
    with db.engine.begin() as conn:
        conn.execute(
            text("UPDATE a2a_tasks SET status = :s, updated_at = now() WHERE id = :id"),
            {"s": nxt, "id": task_id},
        )
    if nxt == "submitted":
        _enqueue_work(task_id, row.get("partnerId") or "", row.get("skillId") or "", row.get("input") or {})
    return get_task(task_id) or row


def list_partners() -> list[dict[str, Any]]:
    with db.engine.connect() as conn:
        rows = db._rows(
            conn.execute(
                text("SELECT * FROM a2a_partners WHERE tenant_id = :t ORDER BY name"),
                {"t": db.current_tenant()},
            )
        )
    return [_map_partner(r) for r in rows]


def upsert_partner(payload: dict[str, Any]) -> dict[str, Any]:
    pid = str(payload.get("id") or f"a2a-p-{uuid.uuid4().hex[:8]}")
    dn = str(payload.get("certDn") or payload.get("cert_dn") or "").strip()
    fp = str(payload.get("certFingerprint") or payload.get("cert_fingerprint") or "").strip()
    if not fp and dn:
        fp = fingerprint_dn(dn)
    if not fp:
        raise ValueError("a2a_cert_required")
    skills = payload.get("allowedSkills") or payload.get("allowed_skills") or []
    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO a2a_partners (
                  id, tenant_id, name, card_url, cert_fingerprint, cert_dn, allowed_skills, status
                ) VALUES (
                  :id, :t, :n, :url, :fp, :dn, CAST(:sk AS text[]), 'active'
                )
                ON CONFLICT (id) DO UPDATE SET
                  name = EXCLUDED.name,
                  card_url = EXCLUDED.card_url,
                  cert_fingerprint = EXCLUDED.cert_fingerprint,
                  cert_dn = EXCLUDED.cert_dn,
                  allowed_skills = EXCLUDED.allowed_skills,
                  status = EXCLUDED.status,
                  updated_at = now()
                """
            ),
            {
                "id": pid,
                "t": db.current_tenant(),
                "n": str(payload.get("name") or "Partner"),
                "url": str(payload.get("cardUrl") or payload.get("card_url") or ""),
                "fp": fp,
                "dn": dn or None,
                "sk": "{" + ",".join(str(s) for s in skills) + "}",
            },
        )
    partners = [p for p in list_partners() if p["id"] == pid]
    return partners[0]


def partner_has_cert(bot_id: str) -> bool:
    """G13: exposing A2A requires at least one partner cert on the tenant."""
    del bot_id
    if not a2a_enabled():
        return False
    with db.engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT 1 FROM a2a_partners
                 WHERE tenant_id = :t AND status = 'active'
                   AND cert_fingerprint IS NOT NULL AND cert_fingerprint <> ''
                 LIMIT 1
                """
            ),
            {"t": db.current_tenant()},
        ).first()
    return bool(row)


def _map_partner(row: dict[str, Any]) -> dict[str, Any]:
    skills = row.get("allowed_skills") or []
    if hasattr(skills, "tolist"):
        skills = list(skills)
    return {
        "id": row["id"],
        "name": row["name"],
        "cardUrl": row.get("card_url"),
        "certFingerprint": row.get("cert_fingerprint"),
        "certDn": row.get("cert_dn"),
        "allowedSkills": list(skills),
        "status": row.get("status"),
    }


def _map_task(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "partnerId": row.get("partner_id"),
        "botId": row.get("bot_id"),
        "skillId": row.get("skill_id"),
        "status": row.get("status"),
        "input": row.get("input") if isinstance(row.get("input"), dict) else {},
        "output": row.get("output") if isinstance(row.get("output"), dict) else {},
        "certDn": row.get("cert_dn"),
        "error": row.get("error"),
        "createdAt": str(row["created_at"]) if row.get("created_at") else None,
    }
