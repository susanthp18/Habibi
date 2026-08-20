"""Tamper-evident change log for what an agent was configured to say.

Publishing a prompt version changes the words a regulated collections agent
speaks to every caller it answers. ``prompt_versions`` records the text and
``bot_deployments`` records the rollout, but neither answers the questions an
auditor actually asks months later:

* who pressed publish, and when;
* what changed between the version that was live and the one that replaced it;
* **what the compiler said at that moment** — gate outcomes were computed on
  every publish and then thrown away, so "was the signed-skills gate green when
  this shipped?" had no answer;
* whether the record itself has been altered since.

Design notes
------------
*Hashes, not copies.* A published ``prompt_versions`` row is immutable, so
duplicating the prompt here would only create a second thing to keep in sync.
Each component is stored as a SHA-256 digest, which is enough to prove which
text shipped and to spot a republish of identical content.

*Hash chain.* Every entry carries the previous entry's digest for the same
tenant, and its own digest covers that link. Editing or deleting a historical
row breaks every later link, and :func:`verify_chain` reports where. An audit
trail that can be silently rewritten is not evidence.

*Written inside the publish transaction.* The caller passes its connection, so
the record commits with the publish or not at all. A log that can be lost when
the process dies mid-publish would be worse than none, because it would look
complete.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Iterable, Mapping, Sequence

logger = logging.getLogger(__name__)

PUBLISH = "agent.publish"
ROLLBACK = "agent.rollback"
ARCHIVE = "agent.archive"

#: Components of a prompt version that are hashed and diffed independently.
COMPONENTS: tuple[str, ...] = (
    "prompt",
    "persona",
    "voice",
    "guardrails",
    "flow",
    "agent_card",
)

_ENTITY_TYPE = "bot"
_GENESIS = "0" * 64


def _canonical(value: Any) -> str:
    """Stable JSON for hashing — key order must not change a digest."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def component_hashes(row: Mapping[str, Any] | None) -> dict[str, str]:
    """One digest per component of a prompt version."""
    row = row or {}
    return {name: _digest(row.get(name)) for name in COMPONENTS}


def changed_components(
    before: Mapping[str, str] | None, after: Mapping[str, str]
) -> list[str]:
    """Component names whose digest moved. Everything is "changed" on a first
    publish, which is accurate — there was no live configuration before it."""
    if not before:
        return list(after)
    return sorted(name for name, digest in after.items() if before.get(name) != digest)


def gate_summary(report: Any) -> dict[str, str]:
    """``{"G0": "pass", "G9": "skipped", ...}`` from a CompileReport or its dump.

    Only gate and status: the full report is large and its detail strings are
    free text, while the status is the part a control test asserts on.
    """
    gates: Iterable[Any]
    if report is None:
        return {}
    if isinstance(report, Mapping):
        gates = report.get("gates") or []
    else:
        gates = getattr(report, "gates", []) or []
    out: dict[str, str] = {}
    for gate in gates:
        if isinstance(gate, Mapping):
            key, status = gate.get("gate"), gate.get("status")
        else:
            key, status = getattr(gate, "gate", None), getattr(gate, "status", None)
        if key:
            out[str(key)] = str(status or "unknown")
    return out


def _chain_head(conn: Any, tenant_id: str) -> tuple[str, int]:
    """Digest and sequence number of the newest entry, ordered by ``seq``.

    Not by ``created_at``: Postgres ``now()`` is transaction start time, so
    entries written in one transaction share a timestamp, and two publishes in
    the same second would tie in production. Order that a chain depends on
    cannot come from a clock.
    """
    from sqlalchemy import text as _text

    row = conn.execute(
        _text(
            """
            SELECT payload FROM audit_log
             WHERE tenant_id = :tenant AND entity_type = :entity
             ORDER BY COALESCE((payload->>'seq')::bigint, 0) DESC, id DESC
             LIMIT 1
            """
        ),
        {"tenant": tenant_id, "entity": _ENTITY_TYPE},
    ).scalar()
    if not row:
        return _GENESIS, 0
    payload = row if isinstance(row, dict) else json.loads(row)
    return str(payload.get("entryHash") or _GENESIS), int(payload.get("seq") or 0)


def _write(
    conn: Any,
    *,
    tenant_id: str,
    actor_user_id: str,
    action: str,
    bot_id: str,
    payload: dict[str, Any],
    entry_id: str,
) -> dict[str, Any]:
    from sqlalchemy import text as _text

    prev_hash, prev_seq = _chain_head(conn, tenant_id)
    body = {
        **payload,
        "action": action,
        "botId": bot_id,
        "seq": prev_seq + 1,
        "prevHash": prev_hash,
    }
    body["entryHash"] = _digest(body)

    conn.execute(
        _text(
            """
            INSERT INTO audit_log (id, tenant_id, actor_user_id, action,
                                   entity_type, entity_id, payload)
            VALUES (:id, :tenant, :actor, :action, :entity, :bot,
                    CAST(:payload AS jsonb))
            """
        ),
        {
            "id": entry_id,
            "tenant": tenant_id,
            "actor": actor_user_id,
            "action": action,
            "entity": _ENTITY_TYPE,
            "bot": bot_id,
            "payload": json.dumps(body),
        },
    )
    return body


def record_publish(
    conn: Any,
    *,
    tenant_id: str,
    actor_user_id: str,
    entry_id: str,
    bot_id: str,
    version: Mapping[str, Any],
    previous_version: Mapping[str, Any] | None,
    deployment_id: str | None,
    traffic_pct: int,
    shadow: bool,
    auto_rollback: Sequence[str],
    report: Any,
) -> dict[str, Any]:
    """Append a publish entry. Call inside the publishing transaction."""
    after = component_hashes(version)
    before = component_hashes(previous_version) if previous_version else None
    payload = {
        "versionId": version.get("id"),
        "versionLabel": version.get("label"),
        "previousVersionId": (previous_version or {}).get("id"),
        "previousVersionLabel": (previous_version or {}).get("label"),
        "deploymentId": deployment_id,
        "summary": version.get("summary") or "",
        "rollout": {
            "trafficPct": int(traffic_pct),
            "shadow": bool(shadow),
            "autoRollback": list(auto_rollback or []),
        },
        "changed": changed_components(before, after),
        "hashes": after,
        "gates": gate_summary(report),
    }
    return _write(
        conn,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action=PUBLISH,
        bot_id=bot_id,
        payload=payload,
        entry_id=entry_id,
    )


def record_rollback(
    conn: Any,
    *,
    tenant_id: str,
    actor_user_id: str,
    entry_id: str,
    bot_id: str,
    to_deployment_id: str,
    from_deployment_id: str | None,
    version_id: str | None,
) -> dict[str, Any]:
    """Rollback changes what callers hear just as much as publish does."""
    payload = {
        "deploymentId": to_deployment_id,
        "replacedDeploymentId": from_deployment_id,
        "versionId": version_id,
    }
    return _write(
        conn,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action=ROLLBACK,
        bot_id=bot_id,
        payload=payload,
        entry_id=entry_id,
    )


def record_archive(
    conn: Any,
    *,
    tenant_id: str,
    actor_user_id: str,
    entry_id: str,
    bot_id: str,
    retired_deployment_id: str | None,
) -> dict[str, Any]:
    payload = {"retiredDeploymentId": retired_deployment_id}
    return _write(
        conn,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action=ARCHIVE,
        bot_id=bot_id,
        payload=payload,
        entry_id=entry_id,
    )


def read_entries(
    conn: Any, *, tenant_id: str, bot_id: str | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    from sqlalchemy import text as _text

    clauses = ["tenant_id = :tenant", "entity_type = :entity"]
    params: dict[str, Any] = {
        "tenant": tenant_id,
        "entity": _ENTITY_TYPE,
        "n": max(1, min(int(limit), 500)),
    }
    if bot_id:
        clauses.append("entity_id = :bot")
        params["bot"] = bot_id
    rows = conn.execute(
        _text(
            f"""
            SELECT id, actor_user_id, action, entity_id, payload, created_at
              FROM audit_log
             WHERE {" AND ".join(clauses)}
             ORDER BY COALESCE((payload->>'seq')::bigint, 0) DESC, id DESC
             LIMIT :n
            """
        ),
        params,
    ).mappings()
    out: list[dict[str, Any]] = []
    for row in rows:
        payload = row["payload"] if isinstance(row["payload"], dict) else json.loads(row["payload"])
        out.append(
            {
                "id": row["id"],
                "actorUserId": row["actor_user_id"],
                "action": row["action"],
                "botId": row["entity_id"],
                "at": str(row["created_at"]) if row["created_at"] else None,
                **{k: v for k, v in payload.items() if k not in {"action", "botId"}},
            }
        )
    return out


def verify_chain(conn: Any, *, tenant_id: str) -> dict[str, Any]:
    """Walk the chain oldest-first and report the first broken link.

    ``ok`` false means a historical entry was altered or removed after the fact.
    Scoped to the tenant because the chain is per tenant.
    """
    from sqlalchemy import text as _text

    rows = list(
        conn.execute(
            _text(
                """
                SELECT id, payload FROM audit_log
                 WHERE tenant_id = :tenant AND entity_type = :entity
                 ORDER BY COALESCE((payload->>'seq')::bigint, 0) ASC, id ASC
                """
            ),
            {"tenant": tenant_id, "entity": _ENTITY_TYPE},
        ).mappings()
    )
    expected_prev = _GENESIS
    for row in rows:
        payload = row["payload"] if isinstance(row["payload"], dict) else json.loads(row["payload"])
        stored = str(payload.get("entryHash") or "")
        body = {k: v for k, v in payload.items() if k != "entryHash"}
        if str(payload.get("prevHash") or "") != expected_prev:
            return {"ok": False, "checked": len(rows), "brokenAt": row["id"], "reason": "prev_hash_mismatch"}
        if _digest(body) != stored:
            return {"ok": False, "checked": len(rows), "brokenAt": row["id"], "reason": "entry_hash_mismatch"}
        expected_prev = stored
    return {"ok": True, "checked": len(rows), "brokenAt": None, "reason": None}
