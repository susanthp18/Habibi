"""MCP connector registry + dispatch. Remote tools are prefixed ext.{slug}."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import text

import db
from agent_core.connectors import circuit
from agent_core.connectors.first_party import FIRST_PARTY_TOOLS, dispatch_first_party
from agent_core.connectors.strip import strip_result
from agent_core.platform_flags import mcp_client_enabled

logger = logging.getLogger(__name__)


def _https_ok(url: str | None) -> bool:
    if not url:
        return True
    parsed = urlparse(url)
    return parsed.scheme == "https" and bool(parsed.netloc)


def list_connectors() -> list[dict[str, Any]]:
    with db.engine.connect() as conn:
        rows = db._rows(
            conn.execute(
                text("SELECT * FROM mcp_connectors WHERE tenant_id = :t ORDER BY slug"),
                {"t": db._tenant()},
            )
        )
    return [_public(r) for r in rows]


def get_connector(connector_id: str) -> dict[str, Any] | None:
    with db.engine.connect() as conn:
        row = db._one(
            conn.execute(
                text("SELECT * FROM mcp_connectors WHERE (id = :id OR slug = :id) AND tenant_id = :t"),
                {"id": connector_id, "t": db._tenant()},
            )
        )
    return _public(row) if row else None


def _arr(value: Any) -> list[str]:
    if value is None:
        return []
    if hasattr(value, "tolist"):
        return list(value)
    if isinstance(value, list):
        return [str(v) for v in value]
    return []


def _public(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "slug": row["slug"],
        "displayName": row["display_name"],
        "kind": row["kind"],
        "url": row.get("url"),
        "authRef": row.get("auth_ref"),
        "allowPrefixes": _arr(row.get("allow_prefixes")),
        "dataClass": _arr(row.get("data_class")),
        "ttlMs": row.get("ttl_ms"),
        "timeoutMs": row.get("timeout_ms"),
        "allowedEnv": row.get("allowed_env"),
        "status": row["status"],
        "health": row["health"],
        "lastToolsListAt": str(row["last_tools_list_at"]) if row.get("last_tools_list_at") else None,
        "toolsCache": row.get("tools_cache") or [],
        "cimdIssuer": row.get("cimd_issuer"),
        "cimdClientId": row.get("cimd_client_id"),
        "circuitOpenedAt": str(row["circuit_opened_at"]) if row.get("circuit_opened_at") else None,
        "circuitFails": row.get("circuit_fails") or 0,
    }


def upsert_connector(payload: dict[str, Any]) -> dict[str, Any]:
    slug = str(payload.get("slug") or "").strip()
    if not slug:
        raise ValueError("connector_slug_required")
    url = str(payload.get("url") or "").strip() or None
    kind = str(payload.get("kind") or "remote_mcp")
    if kind == "remote_mcp" and not _https_ok(url):
        raise ValueError("connector_url_https_only")
    prefixes = payload.get("allowPrefixes") or payload.get("allow_prefixes") or [f"ext.{slug}."]
    data_class = payload.get("dataClass") or payload.get("data_class") or ["pii"]
    cid = str(payload.get("id") or f"conn-{slug}")
    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO mcp_connectors (
                  id, tenant_id, slug, display_name, kind, url, auth_ref, allow_prefixes,
                  data_class, ttl_ms, timeout_ms, allowed_env, status
                ) VALUES (
                  :id, :t, :slug, :name, :kind, :url, :auth, CAST(:pref AS text[]),
                  CAST(:dc AS text[]), :ttl, :timeout, :env, :status
                )
                ON CONFLICT (tenant_id, slug) DO UPDATE SET
                  display_name = EXCLUDED.display_name,
                  url = EXCLUDED.url,
                  auth_ref = EXCLUDED.auth_ref,
                  allow_prefixes = EXCLUDED.allow_prefixes,
                  data_class = EXCLUDED.data_class,
                  ttl_ms = EXCLUDED.ttl_ms,
                  timeout_ms = EXCLUDED.timeout_ms,
                  allowed_env = EXCLUDED.allowed_env,
                  status = EXCLUDED.status
                """
            ),
            {
                "id": cid,
                "t": db._tenant(),
                "slug": slug,
                "name": str(payload.get("displayName") or payload.get("display_name") or slug),
                "kind": kind,
                "url": url,
                "auth": payload.get("authRef") or payload.get("auth_ref"),
                "pref": "{" + ",".join(prefixes) + "}",
                "dc": "{" + ",".join(data_class) + "}",
                "ttl": int(payload.get("ttlMs") or payload.get("ttl_ms") or 30_000),
                "timeout": int(payload.get("timeoutMs") or payload.get("timeout_ms") or 2500),
                "env": str(payload.get("allowedEnv") or payload.get("allowed_env") or "sandbox"),
                "status": str(payload.get("status") or "draft"),
            },
        )
    row = get_connector(slug)
    assert row is not None
    return row


def approve(connector_id: str) -> dict[str, Any]:
    row = get_connector(connector_id)
    if not row:
        raise KeyError("connector_not_found")
    if row["kind"] == "remote_mcp" and not _https_ok(row.get("url")):
        raise ValueError("connector_url_https_only")
    if not row.get("dataClass"):
        raise ValueError("connector_data_class_required")
    with db.engine.begin() as conn:
        conn.execute(
            text("UPDATE mcp_connectors SET status = 'approved' WHERE id = :id AND tenant_id = :t"),
            {"id": row["id"], "t": db._tenant()},
        )
    return get_connector(row["id"])  # type: ignore[return-value]


def bound_tool_names(card_connectors: list[dict[str, Any]]) -> list[str]:
    """Compile-time bind: only approved connectors, only allow_prefixes."""
    if not mcp_client_enabled():
        return []
    names: list[str] = []
    by_id = {c["id"]: c for c in list_connectors()}
    by_slug = {c["slug"]: c for c in list_connectors()}
    for ref in card_connectors:
        cid = str(ref.get("connector_id") or ref.get("connectorId") or "")
        conn = by_id.get(cid) or by_slug.get(cid)
        if not conn or conn["status"] != "approved":
            continue
        prefixes = ref.get("allow_prefixes") or ref.get("allowPrefixes") or conn["allowPrefixes"]
        if conn["kind"] == "first_party":
            for tool, slug in FIRST_PARTY_TOOLS.items():
                if slug == conn["slug"] and any(tool.startswith(p) for p in prefixes):
                    names.append(tool)
        else:
            for cached in conn.get("toolsCache") or []:
                raw = cached.get("name") if isinstance(cached, dict) else str(cached)
                prefixed = raw if str(raw).startswith("ext.") else f"ext.{conn['slug']}.{raw}"
                if any(prefixed.startswith(p) for p in prefixes):
                    names.append(prefixed)
    return names


def dispatch(name: str, *, customer_id: str, connector_id: str | None = None) -> dict[str, Any]:
    if not mcp_client_enabled():
        return {"ok": False, "error": "mcp_client_disabled"}
    if name in FIRST_PARTY_TOOLS:
        return dispatch_first_party(name, customer_id)
    conn = None
    if connector_id:
        conn = get_connector(connector_id)
    if conn is None:
        slug = name.split(".")[1] if name.startswith("ext.") else ""
        conn = get_connector(slug) if slug else None
    if not conn or conn["status"] != "approved":
        return {"ok": False, "error": "connector_not_bound"}
    if not circuit.allow({"circuit_opened_at": conn.get("circuitOpenedAt")}):
        return {"ok": False, "error": "connector_circuit_open"}
    try:
        result = _call_remote(conn, name, customer_id)
        circuit.record_success(conn["id"])
        return strip_result(result)
    except Exception:
        logger.exception("remote connector failed · %s", name)
        circuit.record_failure(conn["id"])
        return {"ok": False, "error": "connector_call_failed"}


def health_test(connector_id: str) -> dict[str, Any]:
    conn = get_connector(connector_id)
    if not conn:
        raise KeyError("connector_not_found")
    if conn["kind"] == "first_party":
        tool = next(t for t, slug in FIRST_PARTY_TOOLS.items() if slug == conn["slug"])
        # One read. No customer: structural ok.
        circuit.record_success(conn["id"])
        return {"ok": True, "tool": tool, "kind": "first_party"}
    # Remote: tools/list
    try:
        listed = _remote_tools_list(conn)
        with db.engine.begin() as dbc:
            dbc.execute(
                text(
                    """
                    UPDATE mcp_connectors
                       SET tools_cache = CAST(:cache AS jsonb), last_tools_list_at = now(), health = 'healthy'
                     WHERE id = :id
                    """
                ),
                {"cache": db._jsonb(listed), "id": conn["id"]},
            )
        circuit.record_success(conn["id"])
        return {"ok": True, "tools": len(listed)}
    except Exception as exc:
        circuit.record_failure(conn["id"])
        return {"ok": False, "error": type(exc).__name__}


def _auth_header(conn: dict[str, Any]) -> dict[str, str]:
    ref = conn.get("authRef")
    if not ref:
        return {}
    from agent_core.vault.persist import reveal

    secret = reveal(ref)
    return {"Authorization": f"Bearer {secret}"}


def _call_remote(conn: dict[str, Any], name: str, customer_id: str) -> dict[str, Any]:
    import httpx

    remote_name = name.split(".", 2)[-1] if name.startswith("ext.") else name
    timeout = max(0.2, (conn.get("timeoutMs") or 2500) / 1000)
    resp = httpx.post(
        str(conn["url"]).rstrip("/") + "/mcp",
        headers={**_auth_header(conn), "Content-Type": "application/json"},
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": remote_name, "arguments": {"customer_id": customer_id}},
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("error"):
        raise RuntimeError(payload["error"].get("message") or "remote_error")
    result = payload.get("result") or {}
    content = result.get("content") or []
    if content and isinstance(content[0], dict) and content[0].get("text"):
        try:
            return json.loads(content[0]["text"])
        except json.JSONDecodeError:
            return {"ok": True, "status": content[0]["text"][:80]}
    return result if isinstance(result, dict) else {"ok": True}


def _remote_tools_list(conn: dict[str, Any]) -> list[dict[str, Any]]:
    import httpx

    timeout = max(0.2, (conn.get("timeoutMs") or 2500) / 1000)
    resp = httpx.post(
        str(conn["url"]).rstrip("/") + "/mcp",
        headers={**_auth_header(conn), "Content-Type": "application/json"},
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        timeout=timeout,
    )
    resp.raise_for_status()
    tools = (resp.json().get("result") or {}).get("tools") or []
    return [{"name": t.get("name")} for t in tools if isinstance(t, dict)]


def seed_first_party() -> None:
    for slug, title, prefixes, data_class in (
        ("paylink", "Pay-link status", ["ext.paylink."], ["money", "pii"]),
        ("lms", "LMS balance", ["ext.lms."], ["money", "pii"]),
    ):
        upsert_connector(
            {
                "id": f"conn-{slug}",
                "slug": slug,
                "displayName": title,
                "kind": "first_party",
                "allowPrefixes": prefixes,
                "dataClass": data_class,
                "status": "approved",
                "allowedEnv": "both",
            }
        )


def cimd_connect(connector_id: str, issuer: str) -> dict[str, Any]:
    """CIMD: record a bank IdP issuer. No DCR. Client secret stays in vault."""
    parsed = urlparse(issuer)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("cimd_issuer_https_only")
    row = get_connector(connector_id)
    if not row:
        raise KeyError("connector_not_found")
    client_id = f"cimd-{uuid.uuid4().hex[:10]}"
    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE mcp_connectors
                   SET cimd_issuer = :iss, cimd_client_id = :cid
                 WHERE id = :id AND tenant_id = :t
                """
            ),
            {"iss": issuer.rstrip("/"), "cid": client_id, "id": row["id"], "t": db._tenant()},
        )
    return {"ok": True, "clientId": client_id, "issuer": issuer.rstrip("/")}
