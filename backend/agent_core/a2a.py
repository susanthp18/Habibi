"""A2A 1.0 — serve our Agent Card over mTLS. Never on the audio path.

Skills on the card are *our* skill names, not MCP tools. A bearer token without
a client certificate is not enough.
"""

from __future__ import annotations

import hashlib
import logging
import ssl
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


def fingerprint_certificate(pem: str) -> str:
    """SHA-256 of a syntactically valid certificate's DER bytes."""
    try:
        der = ssl.PEM_cert_to_DER_cert(pem)
    except ValueError as exc:
        raise ValueError("a2a_cert_pem_invalid") from exc
    return hashlib.sha256(der).hexdigest()


def client_cert_fingerprint(headers: dict[str, str]) -> str | None:
    """Fingerprint asserted by the trusted TLS terminator after verification."""
    lowered = {k.lower(): v for k, v in headers.items()}
    if client_cert_dn(lowered) is None:
        return None
    raw = (
        lowered.get("x-ssl-client-fingerprint")
        or lowered.get("ssl-client-fingerprint")
        or ""
    )
    normalized = raw.replace(":", "").strip().lower()
    if len(normalized) != 64 or any(c not in "0123456789abcdef" for c in normalized):
        return None
    return normalized


def _partners_have_bot_id(conn: Any) -> bool:
    row = conn.execute(
        text(
            """
            SELECT 1 FROM information_schema.columns
             WHERE table_schema = 'public'
               AND table_name = 'a2a_partners'
               AND column_name = 'bot_id'
            """
        )
    ).first()
    return bool(row)


def require_partner(headers: dict[str, str], *, bot_id: str | None = None) -> dict[str, Any]:
    if not a2a_enabled():
        raise PermissionError("a2a_disabled")
    auth = (headers.get("authorization") or "").strip()
    lowered = {k.lower(): v for k, v in headers.items()}
    dn = client_cert_dn(lowered)
    fp = client_cert_fingerprint(lowered)
    if not dn or not fp:
        if auth.lower().startswith("bearer "):
            raise PermissionError("a2a_mtls_required")
        raise PermissionError("a2a_mtls_required")
    try:
        with db.engine.connect() as conn:
            if not _partners_have_bot_id(conn):
                raise PermissionError("a2a_partner_scope_unavailable")
            row = db._one(
                conn.execute(
                    text(
                        """
                        SELECT * FROM a2a_partners
                         WHERE tenant_id = :t
                           AND status = 'active'
                           AND cert_fingerprint = :fp
                           AND bot_id = :bot
                         LIMIT 1
                        """
                    ),
                    {"t": db.current_tenant(), "fp": fp, "bot": bot_id},
                )
            )
    except PermissionError:
        raise
    except Exception:
        raise PermissionError("a2a_partner_unknown") from None
    if not row:
        raise PermissionError("a2a_partner_unknown")
    partner = dict(row)
    if partner.get("tenant_id") != db.current_tenant():
        raise PermissionError("a2a_partner_unknown")
    bound = str(partner.get("bot_id") or "").strip()
    if not bound:
        raise PermissionError("a2a_partner_unscoped")
    if not bot_id or bound != bot_id:
        raise PermissionError("a2a_bot_mismatch")
    return partner


def _published_card(bot_id: str) -> dict[str, Any]:
    """The live published mouth only. Drafts are not an A2A surface."""
    published = db.get_published_prompt_version(bot_id)
    if published is None:
        raise KeyError("agent_card_not_found")
    raw = published.get("agentCard") if isinstance(published.get("agentCard"), dict) else {}
    if not raw:
        raise KeyError("agent_card_not_found")
    return published


def exposed_skill_ids(raw: dict[str, Any]) -> list[str]:
    a2a = raw.get("a2a") if isinstance(raw.get("a2a"), dict) else {}
    declared = [str(s) for s in (a2a.get("skill_ids") or []) if s]
    attached = []
    for ref in raw.get("skills") or []:
        if not isinstance(ref, dict):
            continue
        slug = str(ref.get("skill_id") or "")
        if slug:
            attached.append(slug)
    if not declared:
        return []
    attached_set = set(attached)
    return [s for s in declared if s in attached_set]


def agent_card_document(bot_id: str) -> dict[str, Any]:
    """A2A Agent Card for the *published* mouth. Honours ``a2a.expose`` / ``skill_ids``."""
    published = _published_card(bot_id)
    raw = published.get("agentCard") or {}
    a2a = raw.get("a2a") if isinstance(raw.get("a2a"), dict) else {}
    if not a2a.get("expose"):
        raise KeyError("a2a_not_exposed")
    ident = raw.get("identity") if isinstance(raw.get("identity"), dict) else {}
    skills_out: list[dict[str, Any]] = []
    for slug in exposed_skill_ids(raw):
        desc = slug
        try:
            pack = pack_for_slug(slug)
            desc = pack.description or slug
        except KeyError:
            pass
        skills_out.append({"id": slug, "name": slug, "description": desc})
    summary = None
    try:
        summary = db.get_agent_studio_card(bot_id)
    except Exception:
        summary = None
    return {
        "name": ident.get("display_name") or (summary or {}).get("name"),
        "description": ident.get("purpose") or (summary or {}).get("purpose") or "",
        "url": "/a2a",
        "version": (summary or {}).get("version") or published.get("id") or "1.0",
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
    bound = str(partner.get("bot_id") or partner.get("botId") or "").strip()
    if bound and bound != bot_id:
        raise PermissionError("a2a_bot_mismatch")
    published = _published_card(bot_id)
    raw = published.get("agentCard") or {}
    a2a = raw.get("a2a") if isinstance(raw.get("a2a"), dict) else {}
    if not a2a.get("expose"):
        raise PermissionError("a2a_not_exposed")
    card_skills = set(exposed_skill_ids(raw))
    if skill_id not in card_skills:
        raise PermissionError("a2a_skill_not_allowed")
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
    pem = str(payload.get("certPem") or payload.get("cert_pem") or "").strip()
    if "BEGIN CERTIFICATE" not in pem:
        raise ValueError("a2a_cert_pem_required")
    fp = fingerprint_certificate(pem)
    dn = str(payload.get("certDn") or payload.get("cert_dn") or "").strip()
    if not dn:
        raise ValueError("a2a_cert_dn_required")
    bot_id = str(payload.get("botId") or payload.get("bot_id") or "").strip()
    if not bot_id:
        raise ValueError("a2a_bot_required")
    skills = payload.get("allowedSkills") or payload.get("allowed_skills") or []
    with db.engine.begin() as conn:
        scoped = _partners_have_bot_id(conn)
        if not scoped:
            raise RuntimeError("a2a_partner_scope_unavailable")
        cols = (
            "id, tenant_id, name, card_url, cert_fingerprint, cert_dn, allowed_skills, status"
        )
        vals = ":id, :t, :n, :url, :fp, :dn, CAST(:sk AS text[]), 'active'"
        extra_update = ""
        params: dict[str, Any] = {
            "id": pid,
            "t": db.current_tenant(),
            "n": str(payload.get("name") or "Partner"),
            "url": str(payload.get("cardUrl") or payload.get("card_url") or ""),
            "fp": fp,
            "dn": dn,
            # Bound as a list, not "{" + ",".join(...) + "}". A skill name
            # containing a comma splits into two elements in the literal form,
            # so a caller could add entries to this allowlist that they never
            # named. `kb_ingest.py` already binds text[] this way.
            "sk": [str(s) for s in skills],
        }
        cols += ", bot_id"
        vals += ", :bot"
        extra_update = ", bot_id = EXCLUDED.bot_id"
        params["bot"] = bot_id
        row = conn.execute(
            text(
                f"""
                INSERT INTO a2a_partners ({cols})
                VALUES ({vals})
                ON CONFLICT (id) DO UPDATE SET
                  name = EXCLUDED.name,
                  card_url = EXCLUDED.card_url,
                  cert_fingerprint = EXCLUDED.cert_fingerprint,
                  cert_dn = EXCLUDED.cert_dn,
                  allowed_skills = EXCLUDED.allowed_skills,
                  status = EXCLUDED.status
                  {extra_update},
                  updated_at = now()
                WHERE a2a_partners.tenant_id = :t
                RETURNING id
                """
            ),
            params,
        ).first()
        if row is None:
            # The id exists and belongs to someone else. `tenant_id` is
            # deliberately absent from the SET list, so without this predicate
            # the row kept its owner while its certificate fingerprint, DN and
            # allowed skills were all replaced by this caller's -- a silent
            # cross-tenant rewrite of an mTLS trust record. The conflict target
            # stays `(id)` because that is the primary key; the guard is the
            # WHERE, which needs no new unique index to be correct.
            raise ValueError("a2a_partner_belongs_to_another_tenant")
    partners = [p for p in list_partners() if p["id"] == pid]
    return partners[0]


def partner_has_cert(bot_id: str) -> bool:
    """G13: exposing A2A requires a partner cert bound to this bot.

    Fail closed when the bot-scope column is missing (unmigrated) or when no
    active partner with a non-empty fingerprint is bound to ``bot_id``.
    """
    if not a2a_enabled():
        return False
    if not bot_id:
        return False
    with db.engine.connect() as conn:
        if not _partners_have_bot_id(conn):
            return False
        row = conn.execute(
            text(
                """
                SELECT 1 FROM a2a_partners
                 WHERE tenant_id = :t AND status = 'active'
                   AND bot_id = :b
                   AND cert_fingerprint IS NOT NULL AND cert_fingerprint <> ''
                   AND cert_dn IS NOT NULL AND cert_dn <> ''
                 LIMIT 1
                """
            ),
            {"t": db.current_tenant(), "b": bot_id},
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
        "botId": row.get("bot_id"),
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
