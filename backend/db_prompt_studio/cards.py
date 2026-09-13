"""Agent Studio cards: the list and detail views, entry bindings, archive/restore,
and the change log.

One module of the ``db_prompt_studio`` package (was one 3,400-line file).
Call sites stay ``db.*``; the package re-exports every name.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

from db_prompt_studio.common import (
    _db,
)
from db_prompt_studio.deployments import (
    get_active_deployment,
)
from db_prompt_studio.versions import (
    _map_prompt_version,
)
from agent_core.dicts import sub

logger = logging.getLogger(__name__)

def list_agent_studio_cards(*, include_archived: bool = False) -> list[dict[str, Any]]:
    """Fleet index: first-party mouths plus tenant clones. Not a fifth first-party.

    Reachability is stamped here rather than per card: it is a property of the
    whole handoff graph, and a single card cannot know whether anything routes
    to it.
    """
    _mod = _db()
    engine = _mod.engine
    _rows = _mod._rows
    _tenant = _mod._tenant
    _iso_ts = _mod._iso_ts
    from agent_core.cards.defaults import FIRST_PARTY_BOTS, card_dump
    from agent_core.cards.routing import entry_bindings_by_bot, reachability, resolve_entry

    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for bot_id, name, version in FIRST_PARTY_BOTS:
        out.append(_agent_studio_card_summary(bot_id, name, version, card_dump))
        seen.add(bot_id)
    where = "" if include_archived else " AND archived_at IS NULL"
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    f"""
                    SELECT id, name, version, archived_at FROM bots
                     WHERE tenant_id = :tenant{where}
                     ORDER BY name, id
                    """
                ),
                {"tenant": _tenant()},
            )
        )
    for r in rows:
        if r["id"] in seen:
            continue
        summary = _agent_studio_card_summary(
            r["id"], r["name"], r.get("version") or "1.0", card_dump
        )
        summary["archivedAt"] = _iso_ts(r.get("archived_at"))
        out.append(summary)
        seen.add(r["id"])

    # The channel default: the fleet index is asking which card is the root of
    # routing, not which number was dialled.
    entry = resolve_entry("voice")
    bound = entry_bindings_by_bot()
    # A retired card cannot carry traffic, so its handoffs are not a path: leaving
    # them in made a card look reachable through an agent that no longer answers.
    routes = reachability(
        [
            (c["botId"], c.get("publishedCard") or {})
            for c in out
            if not c.get("archivedAt")
        ],
        entry=entry,
        entries=bound,
        # A card holding its own active deployment is addressable by bot_id, so
        # it seeds the walk too. deploymentStatus is already computed per card.
        deployed=[c["botId"] for c in out if c.get("deploymentStatus") == "live"],
    )
    for card in out:
        card["entryBotId"] = entry
        card["entryBindings"] = bound.get(card["botId"], [])
        card["reachability"] = (
            "archived" if card.get("archivedAt") else routes.get(card["botId"], "unreachable")
        )
    return out

def _studio_card_versions(bot_id: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """(published, newest draft) for one bot, from one snapshot.

    Two separate calls let a concurrent publish land between them and produce a
    summary whose published id and card came from different rows.
    """
    _mod = _db()
    engine = _mod.engine
    _rows = _mod._rows
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT
                      p.id, p.label, p.summary, p.status, p.prompt,
                      p.persona, p.voice, p.guardrails, p.tuning, p.flow,
                      p.bot_id, p.agent_card, p.created_at,
                      COALESCE(u.name, 'Unknown') AS author_name
                    FROM prompt_versions p
                    LEFT JOIN users u ON u.id = p.author_user_id
                    WHERE p.bot_id = :bot_id AND p.status IN ('published', 'draft')
                    ORDER BY p.created_at DESC, p.id DESC
                    """
                ),
                {"bot_id": bot_id},
            )
        )
    pub = next((r for r in rows if r["status"] == "published"), None)
    draft = next((r for r in rows if r["status"] == "draft"), None)
    return (
        _map_prompt_version(pub) if pub else None,
        _map_prompt_version(draft) if draft else None,
    )

def _worst_eval_status(bot_id: str, get_latest_eval_report) -> str:
    red = (get_latest_eval_report(bot_id=bot_id, kind="redteam") or {}).get("status")
    reg = (get_latest_eval_report(bot_id=bot_id, kind="regression") or {}).get("status")
    statuses = [str(s) for s in (red, reg) if s]
    if any(s in {"fail", "error"} for s in statuses):
        return "fail"
    if any(s == "pass" for s in statuses):
        return "pass"
    return statuses[0] if statuses else "skipped"

def _agent_studio_card_summary(  # noqa: PLR0913 - one row of a wide summary
    bot_id: str,
    name: str,
    version: str,
    card_dump,
    *,
    versions: tuple[dict[str, Any] | None, dict[str, Any] | None] | None = None,
) -> dict[str, Any]:
    _mod = _db()
    get_latest_eval_report = _mod.get_latest_eval_report
    from agent_core.cards.defaults import FIRST_PARTY_BOT_IDS

    published, draft = versions if versions is not None else _studio_card_versions(bot_id)
    dep = get_active_deployment(bot_id=bot_id, environment="production")

    def _card_of(row: dict[str, Any] | None) -> dict[str, Any] | None:
        raw = (row or {}).get("agentCard")
        return raw if isinstance(raw, dict) and raw else None

    published_card = _card_of(published)
    # The editor PATCHes the draft, so the draft is what it must read back.
    # Returning the published card here is what made every Skills/Connectors
    # toggle snap back: the write landed on the draft, the refetch returned the
    # published row, and the UI reverted. It also left every cloned card — which
    # has a draft and no published row — showing an empty card.
    card = _card_of(draft) or published_card
    source = "draft" if _card_of(draft) else ("published" if published_card else "default")
    if card is None:
        try:
            card = card_dump(bot_id)
        except KeyError:
            # Not first-party and no version yet. An empty card is unauthorable,
            # which made a bot row with no prompt version a dead end in the
            # editor; a scaffold gives it something real to edit.
            from agent_core.cards.defaults import scaffold_card

            card = scaffold_card(bot_id, name)
            source = "scaffold"
    identity = sub(card, "identity")
    tools = sub(card, "tools")
    skill_rows = card.get("skills") if isinstance(card.get("skills"), list) else []
    if not skill_rows:
        try:
            from agent_core.skills.defaults import CARD_SKILLS

            skill_rows = [
                {"skill_id": slug, "version": "1", "pin": "exact"}
                for slug in CARD_SKILLS.get(bot_id, ())
            ]
            if skill_rows:
                card = {**card, "skills": skill_rows}
        except Exception:
            skill_rows = []
    if dep:
        status = "live"
    elif published:
        status = "published"
    elif draft:
        status = "draft"
    else:
        status = "empty"
    return {
        "botId": bot_id,
        "name": identity.get("display_name") or name,
        "version": version,
        "slug": identity.get("slug") or bot_id,
        "purpose": identity.get("purpose") or "",
        "channels": identity.get("channels") or [],
        "skills": [
            s.get("skill_id")
            for s in skill_rows
            if isinstance(s, dict) and s.get("skill_id")
        ],
        "toolCount": len(tools.get("include") or []),
        "evalStatus": _worst_eval_status(bot_id, get_latest_eval_report),
        # None, not 100: a card with no active deployment takes no traffic, and
        # claiming 100% made every unpublished clone look live on the fleet index.
        "trafficPct": (dep or {}).get("trafficPct") if dep else None,
        "deploymentStatus": status,
        "lastPublish": (dep or {}).get("publishedAt"),
        "promptVersionId": (published or {}).get("id"),
        "draftVersionId": (draft or {}).get("id"),
        "hasDraft": draft is not None,
        # What the editor edits vs what production is running — the Ship tab and
        # the fleet badge need to tell those apart.
        "cardSource": source,
        # Explicit rather than inferred: the fleet guessed first-party from
        # cardSource == "default", but a first-party card with a published row
        # reports "published", so its Archive button enabled and then 409'd.
        "isFirstParty": bot_id in FIRST_PARTY_BOT_IDS,
        # Always present: set here rather than only on the tenant branch of
        # list_agent_studio_cards, which left first-party rows without the key
        # while the single-card endpoint always had it.
        "archivedAt": None,
        "agentCard": card,
        # A first-party card with no published row runs its built-in card on
        # every call, so the fleet walk (reachability, G-F4) reads that; an
        # empty dict said "no handoffs" while the runtime enforced two.
        "publishedCard": published_card or (card if source == "default" else {}),
    }

def _handoff_edges() -> list[tuple[str, Any]]:
    """(bot_id, card) for every bot, from the draft when there is one.

    Only the handoff arrays matter here, but the card column is one read either
    way and parsing it in Python keeps the closure logic in one place.
    """
    _mod = _db()
    engine = _mod.engine
    _rows = _mod._rows
    _tenant = _mod._tenant
    _as_dict = _mod._as_dict
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT DISTINCT ON (p.bot_id) p.bot_id, p.agent_card
                      FROM prompt_versions p
                      JOIN bots b ON b.id = p.bot_id
                     WHERE p.status IN ('published', 'draft')
                       AND b.archived_at IS NULL
                       AND b.tenant_id = :tenant
                     ORDER BY p.bot_id, (p.status = 'published') DESC, p.created_at DESC
                    """
                ),
                {"tenant": _tenant()},
            )
        )
    return [(r["bot_id"], _as_dict(r.get("agent_card"))) for r in rows]

def _live_deployment_bot_ids() -> list[str]:
    """Cards carrying an active production deployment.

    These are addressable by bot_id whether or not anything hands off to them —
    agent_core/deployment.py resolves ``bot_id or DEFAULT_BOT_ID`` — so they
    seed the reachability walk alongside the configured entry card.
    """
    _mod = _db()
    engine = _mod.engine
    _rows = _mod._rows
    _tenant = _mod._tenant
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT DISTINCT d.bot_id
                      FROM bot_deployments d
                      JOIN bots b ON b.id = d.bot_id
                     WHERE d.status = 'active'
                       AND d.environment = 'production'
                       AND b.archived_at IS NULL
                       AND b.tenant_id = :tenant
                    """
                ),
                {"tenant": _tenant()},
            )
        )
    return [r["bot_id"] for r in rows]

def get_agent_studio_card(bot_id: str) -> dict[str, Any] | None:
    """One card by id — without building the whole fleet to throw it away."""
    _mod = _db()
    engine = _mod.engine
    _one = _mod._one
    _tenant = _mod._tenant
    _iso_ts = _mod._iso_ts
    from agent_core.cards.defaults import FIRST_PARTY_BOTS, card_dump
    from agent_core.cards.routing import entry_bindings_by_bot, reachability, resolve_entry

    bid = (bot_id or "").strip()
    if not bid:
        return None
    archived_at = None
    summary: dict[str, Any] | None = None
    for fp_id, name, version in FIRST_PARTY_BOTS:
        if fp_id == bid:
            summary = _agent_studio_card_summary(bid, name, version, card_dump)
            break
    if summary is None:
        with engine.connect() as conn:
            row = _one(
                conn.execute(
                    text(
                        """
                        SELECT id, name, version, archived_at FROM bots
                         WHERE id = :id AND tenant_id = :tenant
                        """
                    ),
                    {"id": bid, "tenant": _tenant()},
                )
            )
        if not row:
            return None
        archived_at = _iso_ts(row.get("archived_at"))
        summary = _agent_studio_card_summary(
            bid, row["name"], row.get("version") or "1.0", card_dump
        )
    summary["archivedAt"] = archived_at

    # The channel default: the fleet index is asking which card is the root of
    # routing, not which number was dialled.
    entry = resolve_entry("voice")
    bound = entry_bindings_by_bot()
    edges = {b: c for b, c in _handoff_edges()}
    edges[bid] = summary["agentCard"]  # unsaved-but-loaded card wins for this one
    summary["entryBotId"] = entry
    summary["entryBindings"] = bound.get(bid, [])
    summary["reachability"] = (
        "archived"
        if archived_at
        else reachability(
            list(edges.items()), entry=entry, entries=bound, deployed=_live_deployment_bot_ids()
        ).get(bid, "unreachable")
    )
    return summary

def policy_engines() -> list[dict[str, Any]]:
    """The engines the mouth cannot unbind, and the mode each runs in now.

    Env-driven and legitimately `shadow` on a stack that is still earning
    trust -- which six card lozenges reading "required" could never say."""
    from agent_core.authority import config as authority
    from agent_core.cards.schema import POLICY_ENGINES
    from agent_core.live_qa import config as live_qa
    from agent_core.reco import config as reco
    from agent_core.treatment import config as treatment

    modes = {
        "reco": (reco.mode(), "RECO_MODE"),
        "treatment": (treatment.mode(), "TREATMENT_MODE"),
        "authority": (authority.mode(), "AUTHORITY_MODE"),
        "live_qa": (live_qa.mode(), "LIVE_QA_BARGE_MODE"),
    }
    out = []
    for key, label, tool in POLICY_ENGINES:
        mode, source = modes.get(key, ("always", None))
        out.append({"key": key, "label": label, "tool": tool, "mode": mode, "source": source})
    return out

def list_entry_bindings() -> list[dict[str, Any]]:
    from agent_core.cards.routing import list_entry_bindings as _list

    return _list()

def set_entry_binding(payload: dict[str, Any]) -> dict[str, Any]:
    """Author which card answers a channel (or a dialled number), on the record.

    The bot must hold an active production deployment: a binding to a card
    nothing can serve is a number that rings into silence."""
    from agent_core import change_log
    from agent_core.cards.routing import upsert_entry_binding

    _mod = _db()
    _tenant = _mod._tenant
    bot_id = str(payload.get("botId") or payload.get("bot_id") or "").strip()
    if bot_id not in _live_deployment_bot_ids():
        raise ValueError("entry_binding_target_not_live")
    with _mod.engine.begin() as conn:
        row = upsert_entry_binding(
            channel=str(payload.get("channel") or ""),
            address=payload.get("address"),
            bot_id=bot_id,
            note=str(payload.get("note") or ""),
            enabled=bool(payload.get("enabled", True)),
            conn=conn,
        )
        change_log.record_entry_binding(
            conn,
            tenant_id=_tenant(),
            actor_user_id=_mod._actor_user_id() or "system",
            entry_id=_mod._id("AUD"),
            bot_id=bot_id,
            binding=row,
        )
    return row

def remove_entry_binding(binding_id: str) -> dict[str, Any]:
    from agent_core import change_log
    from agent_core.cards.routing import delete_entry_binding

    _mod = _db()
    with _mod.engine.begin() as conn:
        row = delete_entry_binding(binding_id, conn=conn)
        if row is None:
            raise KeyError(f"entry_binding_not_found: {binding_id}")
        change_log.record_entry_binding(
            conn,
            tenant_id=_mod._tenant(),
            actor_user_id=_mod._actor_user_id() or "system",
            entry_id=_mod._id("AUD"),
            bot_id=str(row["bot_id"]),
            binding=row,
            removed=True,
        )
    return row

def archive_agent_studio_card(bot_id: str) -> dict[str, Any]:
    """Retire a tenant card. Never deletes — the row is referenced by audit.

    ``bots.id`` is a foreign key on interactions, eval_reports, activity_events
    and a2a_tasks. A DELETE would cascade the deployments and NULL the audit
    trail of every call the agent ever handled, so retirement is a timestamp.

    Refused when the card is first-party (re-seeded on boot) or when it is the
    runtime entry point — inbound traffic would resolve to a retired bot.

    A live production deployment is retired here rather than refused. It used to
    be a third guard, which made the whole feature unreachable: publish always
    leaves an active deployment and rollback only swaps which one is active, so
    no card that had ever shipped could be retired. Taking no traffic *is* what
    archiving means, so retiring the deployment is the operation, not a side
    effect. Restore does not redeploy — publish again to bring the card back.
    """
    _mod = _db()
    engine = _mod.engine
    _one = _mod._one
    _tenant = _mod._tenant
    _id = _mod._id
    _actor_user_id = _mod._actor_user_id
    from agent_core.cards.defaults import FIRST_PARTY_BOT_IDS
    from agent_core.cards.routing import is_entry_card

    bid = (bot_id or "").strip()
    if not bid:
        raise ValueError("bot_id_required")
    if bid in FIRST_PARTY_BOT_IDS:
        raise ValueError("first_party_card_not_archivable")
    if is_entry_card(bid):
        raise ValueError("entry_card_not_archivable")
    with engine.begin() as conn:
        updated = conn.execute(
            text(
                """
                UPDATE bots SET archived_at = now(), updated_at = now()
                 WHERE id = :id AND tenant_id = :t AND archived_at IS NULL
                """
            ),
            {"id": bid, "t": _tenant()},
        ).rowcount
        if updated:
            retired = _one(
                conn.execute(
                    text(
                        """
                        SELECT id FROM bot_deployments
                         WHERE bot_id = :id AND environment = 'production'
                           AND status = 'active'
                         LIMIT 1
                        """
                    ),
                    {"id": bid},
                )
            )
            conn.execute(
                text(
                    """
                    UPDATE bot_deployments
                       SET status = 'retired', updated_at = now()
                     WHERE bot_id = :id AND environment = 'production'
                       AND status = 'active'
                    """
                ),
                {"id": bid},
            )
            from agent_core import change_log

            change_log.record_archive(
                conn,
                tenant_id=_tenant(),
                actor_user_id=_actor_user_id() or "system",
                entry_id=_id("AUD"),
                bot_id=bid,
                retired_deployment_id=(retired or {}).get("id"),
            )
    if not updated:
        raise KeyError(f"agent_card_not_found_or_archived:{bid}")
    return {"ok": True, "botId": bid, "archived": True}

def restore_agent_studio_card(bot_id: str) -> dict[str, Any]:
    """Undo an archive. The card returns exactly as it was left.

    Recorded in the change log for the same reason the archive is: an agent
    reappearing on the roster is a configuration change, and a chain that logs
    only the retirement reads as though the card is still retired.
    """
    _mod = _db()
    engine = _mod.engine
    _one = _mod._one
    _tenant = _mod._tenant
    _id = _mod._id
    _actor_user_id = _mod._actor_user_id
    bid = (bot_id or "").strip()
    if not bid:
        raise ValueError("bot_id_required")
    with engine.begin() as conn:
        # Read before the UPDATE nulls it — the archived window is the fact the
        # entry exists to carry, and afterwards it is gone.
        archived_at = _one(
            conn.execute(
                text(
                    """
                    SELECT archived_at FROM bots
                     WHERE id = :id AND tenant_id = :t AND archived_at IS NOT NULL
                    """
                ),
                {"id": bid, "t": _tenant()},
            )
        )
        updated = conn.execute(
            text(
                """
                UPDATE bots SET archived_at = NULL, updated_at = now()
                 WHERE id = :id AND tenant_id = :t AND archived_at IS NOT NULL
                """
            ),
            {"id": bid, "t": _tenant()},
        ).rowcount
        if updated:
            from agent_core import change_log

            change_log.record_restore(
                conn,
                tenant_id=_tenant(),
                actor_user_id=_actor_user_id() or "system",
                entry_id=_id("AUD"),
                bot_id=bid,
                archived_at=(archived_at or {}).get("archived_at"),
            )
    if not updated:
        raise KeyError(f"archived_card_not_found:{bid}")
    return {"ok": True, "botId": bid, "archived": False}

def agent_change_log(bot_id: str | None = None, *, limit: int = 50) -> dict[str, Any]:
    """Publish / rollback / archive history, plus the chain-integrity verdict.

    ``chain`` is reported alongside the entries rather than on a separate call:
    a change log whose integrity you have to remember to check separately is one
    nobody checks.
    """
    _mod = _db()
    engine = _mod.engine
    _tenant = _mod._tenant
    from agent_core import change_log

    with engine.connect() as conn:
        return {
            "entries": change_log.read_entries(
                conn, tenant_id=_tenant(), bot_id=bot_id, limit=limit
            ),
            "total": change_log.count_entries(conn, tenant_id=_tenant(), bot_id=bot_id),
            "chain": change_log.verify_chain(conn, tenant_id=_tenant()),
        }
