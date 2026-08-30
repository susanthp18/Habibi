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


def _guard_outbound_url(url: str | None) -> str:
    """Resolve ``url`` and refuse anything that is not publicly routable.

    ``_https_ok`` reads the scheme and netloc and nothing else, so
    ``https://169.254.169.254/mcp`` — the cloud metadata endpoint — passed
    registration and we POSTed the connector's bearer token straight at it.
    This is the same check the webhook dispatcher makes, through the same two
    helpers, and for the same reason it makes it immediately before the connect
    rather than at registration: a name that resolved publicly when an operator
    approved the connector is free to answer with 10.0.0.5 by the time we dial
    it, which is the whole rebinding attack.

    Raises ``ValueError`` with a ``connector_url_*`` code so callers can tell a
    blocked target from a flaky one — the first must not trip the circuit.
    """
    import webhooks_dispatch

    target = str(url or "").strip()
    if not target:
        raise ValueError("connector_url_required")
    try:
        webhooks_dispatch.resolve_public_host(target)
    except ValueError as exc:
        reason = str(exc)
        if "private_forbidden" in reason:
            raise ValueError(
                f"connector_url_private_forbidden: {reason.split(': ', 1)[-1]}"
            ) from exc
        if "https_required" in reason:
            raise ValueError("connector_url_https_only") from exc
        raise ValueError(f"connector_url_unresolvable: {reason}") from exc
    return target


def _blocked_url_code(exc: BaseException) -> str | None:
    """The ``connector_url_*`` code behind ``exc``, or None if it is not one.

    Narrow on purpose: ``json.JSONDecodeError`` is a ``ValueError`` too, and a
    malformed remote response is a transport fault that *should* count against
    the circuit.
    """
    if not isinstance(exc, ValueError):
        return None
    code = str(exc).split(":", 1)[0].strip()
    return code if code.startswith("connector_url_") else None


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
    # The id carries the tenant because it is the PRIMARY KEY while the
    # uniqueness the registry actually wants is (tenant_id, slug). A bare
    # ``conn-{slug}`` default made the second tenant to register "paylink"
    # collide on the PK, which ``ON CONFLICT (tenant_id, slug)`` below cannot
    # absorb — the INSERT raised instead of upserting. Explicit ids from the
    # caller are left alone; only the default is scoped.
    cid = str(payload.get("id") or f"conn-{db._tenant()}-{slug}")
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
    # One registry read, two indexes. Calling list_connectors() twice put a
    # second `SELECT * FROM mcp_connectors` on the compile hot path for nothing.
    connectors = list_connectors()
    by_id = {c["id"]: c for c in connectors}
    by_slug = {c["slug"]: c for c in connectors}
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


def dispatch(
    name: str,
    *,
    customer_id: str,
    connector_id: str | None = None,
    args: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Call a bound connector tool.

    ``args`` is the caller's own argument object — the model's tool-call
    payload, in the ``bot_tools`` path. It was parsed and validated there and
    then thrown away, so a remote tool declaring anything beyond
    ``customer_id`` was invoked with that parameter missing every single time.
    First-party tools keep their fixed one-argument signature; only the remote
    JSON-RPC leg carries the extra keys.
    """
    if not mcp_client_enabled():
        return {"ok": False, "error": "mcp_client_disabled"}
    conn = None
    if connector_id:
        conn = get_connector(connector_id)
    if conn is None:
        slug = FIRST_PARTY_TOOLS.get(name) or (name.split(".")[1] if name.startswith("ext.") else "")
        conn = get_connector(slug) if slug else None
    if not conn or conn["status"] != "approved":
        return {"ok": False, "error": "connector_not_bound"}
    if not circuit.allow({"circuit_opened_at": conn.get("circuitOpenedAt")}):
        return {"ok": False, "error": "connector_circuit_open"}
    # First-party tools read the same CRM the bot already reads, but they read
    # it *as a connector* — so they answer to the same registry the remote ones
    # do. Gating them below the status and circuit checks rather than above is
    # the whole point: a first-party connector left in draft, or switched to
    # disabled after an incident, was still serving payment data to every
    # caller of dispatch().
    if name in FIRST_PARTY_TOOLS:
        return dispatch_first_party(name, customer_id)
    try:
        result = _call_remote(conn, name, customer_id, args=args)
    except Exception as exc:
        code = _blocked_url_code(exc)
        if code:
            # Not a transport fault: this connector is not flaky, its target is
            # not allowed. Counting it against the circuit would bury a
            # misconfigured (or repointed) URL behind a generic circuit-open for
            # whoever looks next.
            logger.error("connector call blocked · %s · %s", name, exc)
            return {"ok": False, "error": code}
        logger.exception("remote connector failed · %s", name)
        circuit.record_failure(conn["id"])
        return {"ok": False, "error": "connector_call_failed"}
    circuit.record_success(conn["id"])
    return strip_result(result)


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
        code = _blocked_url_code(exc)
        if code:
            logger.error("connector health probe blocked · %s · %s", conn["id"], exc)
            return {"ok": False, "error": code}
        circuit.record_failure(conn["id"])
        return {"ok": False, "error": type(exc).__name__}


def _auth_header(conn: dict[str, Any]) -> dict[str, str]:
    ref = conn.get("authRef")
    if not ref:
        return {}
    from agent_core.vault.persist import reveal

    secret = reveal(ref)
    return {"Authorization": f"Bearer {secret}"}


def _remote_arguments(customer_id: str, args: dict[str, Any] | None) -> dict[str, Any]:
    """``customer_id`` plus whatever the caller passed, caller's keys winning.

    ``customer_id`` is a default rather than an override so it is always on the
    wire — a remote tool that only knows about it keeps working unchanged — but
    the caller's object is layered on top, which is the whole point of
    forwarding it.
    """
    arguments: dict[str, Any] = {"customer_id": customer_id}
    if isinstance(args, dict):
        arguments.update(args)
    return arguments


def _call_remote(
    conn: dict[str, Any],
    name: str,
    customer_id: str,
    args: dict[str, Any] | None = None,
) -> dict[str, Any]:
    import httpx

    remote_name = name.split(".", 2)[-1] if name.startswith("ext.") else name
    timeout = max(0.2, (conn.get("timeoutMs") or 2500) / 1000)
    endpoint = _guard_outbound_url(conn.get("url")).rstrip("/") + "/mcp"
    resp = httpx.post(
        endpoint,
        headers={**_auth_header(conn), "Content-Type": "application/json"},
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": remote_name,
                "arguments": _remote_arguments(customer_id, args),
            },
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
    endpoint = _guard_outbound_url(conn.get("url")).rstrip("/") + "/mcp"
    resp = httpx.post(
        endpoint,
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
