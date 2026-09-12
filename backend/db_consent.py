"""Consent records and opt-outs (WP-036 peel).

Peeled from ``db.py``. Call sites stay ``db.*`` via a bottom-of-file
re-export. Reach the engine through :func:`_db`, never ``from db_core import
engine``: the ``db_tx`` fixture wraps ``db.engine``, and a name bound from
``db_core`` bypasses that proxy.
"""

from __future__ import annotations

import contact_window
from agent_core import clock
from datetime import datetime, timedelta, timezone
from sqlalchemy import text
from typing import Any
from agent_core.clock import utc_now


def _db():
    """The ``db`` module object, resolved at call time."""
    import db as d

    return d


_DAY_NAME_TO_NUM = {"sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6}

_DAY_NUM_TO_NAME = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]

_CONSENT_CHANNEL_ORDER = ("call", "whatsapp", "sms", "email")

_OPT_OUT_SOURCE_MAP = {
    "ivr": "IVR",
    "agent": "Agent",
    "agent-captured": "Agent",
    "web": "Web",
    "self-serve": "Web",
    "customer": "Web",
    "regulator": "Regulator",
    "bulk import": "Bulk Import",
    "bulk_import": "Bulk Import",
    "whatsapp reply": "WhatsApp Reply",
    "whatsapp_reply": "WhatsApp Reply",
    "onboarding": "Onboarding",
    "seed-default": "Onboarding",
    "seed": "Onboarding",
}

_CONSENT_ACTIVITY_KINDS = (
    "consent_updated",
    "consent_renewed",
    "opt_out",
    "dnd_updated",
)

def _consent_segment(raw: str | None) -> str:
    key = (raw or "retail").strip().lower()
    return {"retail": "Retail", "sme": "SME", "priority": "Priority"}.get(key, "Retail")

def _consent_source_screen(raw: str | None) -> str:
    if not raw:
        return "Onboarding"
    if raw in {"IVR", "Agent", "Web", "Regulator", "Bulk Import", "WhatsApp Reply", "Onboarding"}:
        return raw
    return _OPT_OUT_SOURCE_MAP.get(raw.strip().lower(), "Agent")

def _optout_source_screen(raw: str | None) -> str:
    mapped = _consent_source_screen(raw)
    return "Web" if mapped == "Onboarding" else mapped

def _consent_channel_db(channel: str) -> str:
    """Screen channel -> stored channel. The gate's normaliser is the owner of
    "call means voice"; `all` is the consent screen's own word."""
    import contact_policy

    return "all" if channel == "all" else contact_policy.normalize_channel(channel)

def _consent_channel_screen(channel: str) -> str | None:
    _mod = _db()
    _consent_channel = _mod._consent_channel
    if channel == "all":
        return "all"
    return _consent_channel(channel)

def _parse_allowed_days(raw: str | None) -> list[int]:
    """Consent days for the CRM's screens, substituting Mon-Fri when unrecorded.

    The parsing itself is :func:`contact_window.allowed_days` — the same one the
    contact Gate vetoes with. This module had its own copy that did not
    normalise the dash, so ``Mon–Sat`` came back as ``[1]``: the range branch
    missed, the token split matched the leading "mon", and a six-day consent was
    displayed and compared as Monday alone.

    The Mon-Fri substitution stays here rather than moving into the shared
    parser. "Blank consent days means Mon-Fri" is a product claim this screen
    makes, not a fact about the text, and the Gate deliberately makes the
    opposite one — absent days there mean no day restriction to apply. Both are
    defensible; neither should be hidden inside a parser where the other side
    cannot see it.
    """
    return contact_window.allowed_days(raw) or [1, 2, 3, 4, 5]

def _format_allowed_days(days: list[int]) -> str:
    unique = sorted({d for d in days if 0 <= d <= 6})
    if not unique:
        return "Mon-Fri"
    if unique == list(range(unique[0], unique[-1] + 1)):
        return f"{_DAY_NUM_TO_NAME[unique[0]]}-{_DAY_NUM_TO_NAME[unique[-1]]}"
    return ",".join(_DAY_NUM_TO_NAME[d] for d in unique)

def _parse_allowed_hours(raw: str | None) -> tuple[int, int]:
    """The gate's reading of a window, defaults included: a row with no window
    on file is shown the bounds the gate enforces (09:00-20:00), not a
    10:00-19:00 this screen used to invent."""
    return contact_window.window_hours(raw)

def _format_allowed_hours(start_hour: int, end_hour: int) -> str:
    return f"{int(start_hour):02d}:00-{int(end_hour):02d}:00 IST"

def _optout_actor_label(actor_kind: str | None, user_name: str | None) -> str:
    if user_name:
        return user_name
    kind = (actor_kind or "").lower()
    if kind == "customer":
        return "Customer"
    if kind == "system":
        return "System"
    if kind == "regulator":
        return "Regulator"
    if kind == "bot":
        return "Bot"
    return "System"

def _consent_channels_grouped(conn: Any, consent_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    _mod = _db()
    _rows = _mod._rows
    if not consent_ids:
        return {}
    rows = _rows(
        conn.execute(
            text(
                """
                SELECT consent_id, channel, status, source, captured_at,
                       weekly_frequency_cap, used_this_week, created_at
                FROM channel_consents
                WHERE consent_id = ANY(:ids)
                ORDER BY channel
                """
            ),
            {"ids": consent_ids},
        )
    )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        mapped = _consent_channel_screen(r["channel"])
        if mapped is None or mapped == "all":
            continue
        grouped.setdefault(r["consent_id"], []).append(
            {
                "channel": mapped,
                "status": r["status"] if r["status"] in {"opted_in", "opted_out", "dnd", "expired"} else "opted_out",
                "capturedAt": r["captured_at"] or r["created_at"],
                "source": _consent_source_screen(r["source"]),
                "frequencyCapPerWeek": int(r["weekly_frequency_cap"] or 3),
                "usedThisWeek": int(r["used_this_week"] or 0),
            }
        )
    return grouped

def _consent_optouts_grouped(conn: Any, consent_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    _mod = _db()
    _rows = _mod._rows
    if not consent_ids:
        return {}
    rows = _rows(
        conn.execute(
            text(
                """
                SELECT o.id, o.consent_id, o.channel, o.source, o.actor_kind, o.note,
                       o.occurred_at, u.name AS actor_name
                FROM optout_events o
                LEFT JOIN users u ON u.id = o.actor_user_id
                WHERE o.consent_id = ANY(:ids)
                ORDER BY o.occurred_at
                """
            ),
            {"ids": consent_ids},
        )
    )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        mapped = _consent_channel_screen(r["channel"])
        if mapped is None:
            continue
        grouped.setdefault(r["consent_id"], []).append(
            {
                "id": r["id"],
                "at": r["occurred_at"],
                "channel": mapped,
                "source": _optout_source_screen(r["source"]),
                "actor": _optout_actor_label(r["actor_kind"], r["actor_name"]),
                "note": r["note"] or "",
            }
        )
    return grouped

def _consent_audit_grouped(conn: Any, customer_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    _mod = _db()
    _rows = _mod._rows
    if not customer_ids:
        return {}
    rows = _rows(
        conn.execute(
            text(
                """
                SELECT ae.id, ae.entity_id, ae.at, ae.label, u.name AS actor
                FROM activity_events ae
                LEFT JOIN users u ON u.id = ae.actor_user_id
                WHERE ae.entity_type = 'customer'
                  AND ae.entity_id = ANY(:ids)
                  AND ae.kind = ANY(:kinds)
                ORDER BY ae.at
                """
            ),
            {"ids": customer_ids, "kinds": list(_CONSENT_ACTIVITY_KINDS)},
        )
    )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        grouped.setdefault(r["entity_id"], []).append(
            {
                "id": r["id"],
                "at": r["at"],
                "actor": r["actor"] or "System",
                "action": r["label"],
            }
        )
    return grouped

def _ensure_channels_complete(channels: list[dict[str, Any]], fallback_at: str) -> list[dict[str, Any]]:
    by_channel = {c["channel"]: c for c in channels}
    complete: list[dict[str, Any]] = []
    for ch in _CONSENT_CHANNEL_ORDER:
        if ch in by_channel:
            complete.append(by_channel[ch])
        else:
            # No consent row means no consent. Synthesising "opted_in" made the
            # Consent screen assert a permission nobody captured — the one
            # place in the product where the answer must never be inferred.
            complete.append(
                {
                    "channel": ch,
                    "status": "opted_out",
                    "capturedAt": fallback_at,
                    # Stays "Onboarding" — the screen's `source` is a closed
                    # union (ChannelConsent in consent-seed.ts) and the status
                    # is what carries the correction.
                    "source": "Onboarding",
                    "frequencyCapPerWeek": 3,
                    "usedThisWeek": 0,
                }
            )
    return complete

_SCREEN_CHANNELS = ("call", "whatsapp", "sms", "email")


def _contactable_refusal(rec: dict[str, Any], channel: str, now: datetime) -> str | None:
    """Why this channel cannot be used right now, from the row itself; None when it can.

    A reading of the consent row, not the contact Gate: the Gate also knows
    holds, cooling-off and coalescing, and answers per customer through
    ``get_contact_policy``. This is what the Consent screen's pill and stats
    summarise across the whole list without a Gate evaluation per row. It used
    to live in the browser, where "now" was the operator's clock, not the
    borrower's.
    """
    expires = rec["consentExpiresAt"]
    try:
        expires_at = datetime.fromisoformat(str(expires).replace("Z", "+00:00"))
    except ValueError:
        expires_at = None
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at is not None and expires_at < now:
        return "Consent window expired — renew before contacting."
    if rec["onDndRegistry"] and channel == "call":
        return "Customer is on national DND registry (calls only)."
    cc = next((c for c in rec["channels"] if c["channel"] == channel), None)
    if cc is None:
        return "Channel not configured."
    if cc["status"] == "dnd":
        return f"{channel} marked DND."
    if cc["status"] == "opted_out":
        return f"Customer opted out of {channel}."
    if cc["status"] == "expired":
        return f"{channel} consent expired."
    if cc["usedThisWeek"] >= cc["frequencyCapPerWeek"]:
        return f"Weekly cap reached ({cc['usedThisWeek']}/{cc['frequencyCapPerWeek']})."
    window = rec["allowedWindow"]
    local = now.astimezone(clock.zone(rec["timezone"]))
    day = (local.weekday() + 1) % 7  # Sunday = 0, as the screen and contact_window count
    if day not in window["days"] or not (window["startHour"] <= local.hour < window["endHour"]):
        return f"Outside allowed hours ({window['startHour']}:00–{window['endHour']}:00)."
    return None


def contactable_summary(rec: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    """green / amber / red across the four screen channels, with the refusals."""
    at = now or utc_now()
    refusals = [(c, _contactable_refusal(rec, c, at)) for c in _SCREEN_CHANNELS]
    reasons = [f"{c}: {why}" for c, why in refusals if why]
    if not reasons:
        return {"status": "green", "reasons": ["All channels available."]}
    if len(reasons) == len(_SCREEN_CHANNELS):
        return {"status": "red", "reasons": reasons}
    return {"status": "amber", "reasons": reasons}


def list_consent(*, limit: int | None = None, offset: int | None = None) -> list[dict[str, Any]]:
    """Consent & Communication Preferences feed (richer than Customer 360 consent)."""
    _mod = _db()
    _rows = _mod._rows
    _sql = _mod._sql
    _tenant = _mod._tenant
    _vis_params = _mod._vis_params
    clamp_list_limit = _mod.clamp_list_limit
    clamp_offset = _mod.clamp_offset
    engine = _mod.engine
    logger = _mod.logger
    page, skip = clamp_list_limit(limit), clamp_offset(offset)
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                _sql(
                    """
                    SELECT cr.id, cr.customer_id, cr.dnd_registry, cr.expires_at,
                           cr.allowed_days, cr.allowed_hours, cr.created_at,
                           c.name AS customer_name, c.phone_primary, c.email,
                           c.timezone, c.segment, c.preferred_window, c.dnd AS customer_dnd,
                           a.id AS account_id
                    FROM consent_records cr
                    JOIN customers c ON c.id = cr.customer_id
                     AND c.tenant_id = :tenant_id
                     /*VISIBILITY*/
                    LEFT JOIN LATERAL (
                      SELECT *
                      FROM accounts a
                      WHERE a.customer_id = c.id
                      ORDER BY
                        CASE WHEN a.id LIKE 'AC-%' THEN 0 ELSE 1 END,
                        a.created_at,
                        a.id
                      LIMIT 1
                    ) a ON true
                    ORDER BY c.name
                    LIMIT :limit OFFSET :offset
                    """
                ),
                {"limit": page, "offset": skip, "tenant_id": _tenant(), **_vis_params()},
            )
        )
        consent_ids = [r["id"] for r in rows]
        customer_ids = [r["customer_id"] for r in rows]
        channels = _consent_channels_grouped(conn, consent_ids)
        optouts = _consent_optouts_grouped(conn, consent_ids)
        audits = _consent_audit_grouped(conn, customer_ids)
        usage: dict[str, dict[str, Any]] = {}
        try:
            import contact_policy

            usage = contact_policy.ledger_usage(conn, customer_ids)
        except Exception:
            logger.exception("contact_policy ledger_usage failed")
        result: list[dict[str, Any]] = []
        for r in rows:
            created = r["created_at"]
            hours_raw = r["allowed_hours"] or r["preferred_window"]
            start_h, end_h = _parse_allowed_hours(hours_raw)
            expires = r["expires_at"]
            if not expires:
                try:
                    base = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
                except ValueError:
                    base = utc_now()
                expires = (base + timedelta(days=365)).isoformat()
            audit = audits.get(r["customer_id"]) or [
                {
                    "id": f"A-{r['id']}",
                    "at": created,
                    "actor": "Onboarding",
                    "action": "Consent captured",
                }
            ]
            stats = usage.get(r["customer_id"]) or {}
            by_ch = stats.get("byChannel") or {}
            complete = _ensure_channels_complete(channels.get(r["id"]) or [], created)
            for item in complete:
                db_ch = "voice" if item["channel"] == "call" else item["channel"]
                if db_ch in by_ch:
                    item["usedThisWeek"] = by_ch[db_ch]
            screen = {
                    "id": r["id"],
                    "customerId": r["customer_id"],
                    "customerName": r["customer_name"],
                    "accountId": r["account_id"] or "",
                    "phone": r["phone_primary"] or "",
                    "email": r["email"] or "",
                    "timezone": r["timezone"] or clock.DEFAULT_TIMEZONE,
                    "segment": _consent_segment(r["segment"]),
                    "channels": complete,
                    "allowedWindow": {
                        "days": _parse_allowed_days(r["allowed_days"]),
                        "startHour": start_h,
                        "endHour": end_h,
                    },
                    "consentExpiresAt": expires,
                    "onDndRegistry": bool(r["dnd_registry"] or r["customer_dnd"]),
                    "optOutLog": optouts.get(r["id"]) or [],
                    "audit": audit,
                    "outreachToday": int(stats.get("outreachToday") or 0),
                    "dailyCap": int(stats.get("dailyCap") or 3),
                    "lastDecisionReason": stats.get("lastDecisionReason"),
                }
            screen["contactable"] = contactable_summary(screen)
            result.append(screen)
        return result

def get_contact_policy(customer_id: str, channel: str = "whatsapp", purpose: str = "outreach") -> dict[str, Any]:
    """Dry-run of the contact gate for Inbox / Floor / Consent pills."""
    _mod = _db()
    _one = _mod._one
    _tenant = _mod._tenant
    engine = _mod.engine
    import contact_policy

    with engine.connect() as conn:
        if _one(conn.execute(text("SELECT 1 FROM customers WHERE id = :id AND tenant_id = :tid"), {"id": customer_id, "tid": _tenant()})) is None:
            raise KeyError("customer_not_found")
        decision = contact_policy.evaluate(
            conn,
            customer_id=customer_id,
            channel=channel,
            purpose=purpose,
        )
    payload = decision.as_dict()
    payload["channel"] = contact_policy.normalize_channel(channel)
    payload["purpose"] = purpose if purpose in contact_policy.PURPOSES else "outreach"
    return payload

def _ensure_consent_record(conn: Any, customer_id: str) -> str:
    """The consent row a channel or window write hangs off.

    A borrower with no row gets one with **no window**. This used to insert
    ``Mon-Fri`` / ``10:00-19:00 IST`` -- a consent the borrower never gave,
    written by the first operator to toggle a channel, indistinguishable
    afterwards from a recorded preference. Nothing on file is a fact the
    readers already handle: ``contact_window.window_hours(None)`` is the
    platform default and ``contact_policy`` bounds it by statute.
    """
    _mod = _db()
    _one = _mod._one
    consent_id = f"consent-{customer_id}"
    existing = _one(
        conn.execute(text("SELECT id FROM consent_records WHERE customer_id = :id"), {"id": customer_id})
    )
    if existing:
        return existing["id"]
    conn.execute(
        text(
            """
            INSERT INTO consent_records (id, customer_id, dnd_registry, allowed_days, allowed_hours)
            VALUES (:id, :customer_id, false, NULL, NULL)
            """
        ),
        {"id": consent_id, "customer_id": customer_id},
    )
    return consent_id

def _channel_status_from_patch(item: dict[str, Any]) -> str:
    status = item.get("status")
    if status in {"opted_in", "opted_out", "dnd", "expired"}:
        return status
    if "optedIn" in item:
        return "opted_in" if item.get("optedIn") else "opted_out"
    raise ValueError("channel status or optedIn is required")

def _incoming_window_days(aw: dict[str, Any]) -> list[int] | None:
    if "days" not in aw:
        return None
    try:
        return sorted(int(d) for d in (aw.get("days") or []))
    except (TypeError, ValueError):
        return None

def _incoming_window_hours(aw: dict[str, Any]) -> tuple[int, int] | None:
    """GET always sends both hours. Missing hours are not filled with 10–19."""
    start = aw.get("startHour")
    end = aw.get("endHour")
    if start is None or end is None:
        return None
    try:
        return (int(start), int(end))
    except (TypeError, ValueError):
        return None

def _window_days_echo_stored(incoming_days: list[int], allowed_days: str | None) -> bool:
    """True when ``incoming_days`` is the GET serializer's view of ``allowed_days``.

    Writing that view reformats the text: an en-dash ``Mon–Sat`` becomes
    ``Mon-Mon``. The parser that produces that artefact is WP-030; this only
    refuses to persist it. Decided per field so an hours edit cannot rewrite days.
    """
    return incoming_days == sorted(_parse_allowed_days(allowed_days))

def _window_hours_echo_stored(incoming_hours: tuple[int, int], hours_raw: str | None) -> bool:
    """True when ``incoming_hours`` is the GET serializer's view of the stored hours.

    Writing that view turns a NULL window into ``10:00-19:00 IST`` and drops
    minutes from a stored ``08:30-17:45 IST``. The parser is WP-030.
    """
    return incoming_hours == _parse_allowed_hours(hours_raw)

def patch_consent(customer_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Payload arrives with exclude_unset: a present key is an intentional write.

    ``allowedWindow`` is the exception: the consent screen used to echo the GET
    serializer on every save, so a present key may be a round-trip of the stored
    text rather than an operator edit. Each field whose parsed value matches the
    stored string is left byte-identical; only a real edit is written.
    """
    _mod = _db()
    _activity = _mod._activity
    _actor_user_id = _mod._actor_user_id
    _assert_tenant_owns_customer = _mod._assert_tenant_owns_customer
    _ensure_customer = _mod._ensure_customer
    _one = _mod._one
    current_tenant = _mod.current_tenant
    engine = _mod.engine
    get_customer = _mod.get_customer
    with engine.begin() as conn:
        _assert_tenant_owns_customer(conn, customer_id)
        _ensure_customer(conn, customer_id)
        consent_id = _ensure_consent_record(conn, customer_id)

        dnd_val = None
        if "dnd" in payload:
            dnd_val = payload["dnd"]
        elif "onDndRegistry" in payload:
            dnd_val = payload["onDndRegistry"]
        if dnd_val is not None:
            conn.execute(
                text("UPDATE customers SET dnd = :dnd WHERE id = :id"),
                {"dnd": bool(dnd_val), "id": customer_id},
            )
            conn.execute(
                text("UPDATE consent_records SET dnd_registry = :dnd WHERE id = :id"),
                {"dnd": bool(dnd_val), "id": consent_id},
            )

        if "consentExpiresAt" in payload and payload["consentExpiresAt"] is not None:
            conn.execute(
                text("UPDATE consent_records SET expires_at = :expires_at WHERE id = :id"),
                {"expires_at": payload["consentExpiresAt"], "id": consent_id},
            )

        if "allowedWindow" in payload and payload["allowedWindow"] is not None:
            aw = payload["allowedWindow"]
            if not isinstance(aw, dict):
                aw = aw.model_dump() if hasattr(aw, "model_dump") else dict(aw)
            stored = _one(
                conn.execute(
                    text(
                        """
                        SELECT cr.allowed_days, cr.allowed_hours, c.preferred_window
                        FROM consent_records cr
                        JOIN customers c ON c.id = cr.customer_id
                        WHERE cr.id = :id
                        """
                    ),
                    {"id": consent_id},
                )
            )
            days_raw = stored["allowed_days"] if stored else None
            # GET uses allowed_hours, then preferred_window. Match that view so
            # a round-trip of either column is recognised as an echo.
            hours_raw = (stored["allowed_hours"] or stored["preferred_window"]) if stored else None
            incoming_days = _incoming_window_days(aw)
            incoming_hours = _incoming_window_hours(aw)
            # Preserve each stored string when its parsed value round-trips
            # unchanged. A whole-window skip still rewrote days on an hours
            # edit (Mon–Sat → Mon-Mon) and hours on a days edit.
            if incoming_days is not None and not _window_days_echo_stored(
                incoming_days, days_raw
            ):
                conn.execute(
                    text("UPDATE consent_records SET allowed_days = :days WHERE id = :id"),
                    {"days": _format_allowed_days(incoming_days), "id": consent_id},
                )
            if incoming_hours is not None and not _window_hours_echo_stored(
                incoming_hours, hours_raw
            ):
                hours_str = _format_allowed_hours(*incoming_hours)
                conn.execute(
                    text("UPDATE consent_records SET allowed_hours = :hours WHERE id = :id"),
                    {"hours": hours_str, "id": consent_id},
                )
                conn.execute(
                    text("UPDATE customers SET preferred_window = :hours WHERE id = :id"),
                    {"hours": hours_str, "id": customer_id},
                )

        for item in payload.get("channels") or []:
            if not isinstance(item, dict):
                item = item.model_dump() if hasattr(item, "model_dump") else dict(item)
            channel_value = _consent_channel_db(item["channel"])
            status = _channel_status_from_patch(item)
            source = item.get("source") or "Agent"
            cap = item.get("frequencyCapPerWeek")
            # Servicing unless the screen says otherwise. This is the only way a
            # promotional consent can be captured, and it has to exist: a gate
            # nobody can satisfy is not a compliance control, it is an outage
            # with a paragraph number attached.
            purpose = str(item.get("purpose") or "servicing").strip().lower()
            if purpose not in ("servicing", "promotional"):
                purpose = "servicing"
            params: dict[str, Any] = {
                "id": f"{consent_id}-{channel_value}-{purpose}",
                "consent_id": consent_id,
                "channel": channel_value,
                "purpose": purpose,
                "status": status,
                "source": source,
                "cap": cap,
            }
            conn.execute(
                text(
                    """
                    INSERT INTO channel_consents
                      (id, consent_id, channel, purpose, status, source,
                       weekly_frequency_cap, used_this_week, captured_at)
                    VALUES
                      (:id, :consent_id, :channel, :purpose, :status, :source,
                       COALESCE(:cap, 3), 0, now())
                    ON CONFLICT (consent_id, channel, purpose)
                    DO UPDATE SET
                      status = EXCLUDED.status,
                      source = EXCLUDED.source,
                      weekly_frequency_cap = COALESCE(:cap, channel_consents.weekly_frequency_cap),
                      captured_at = now()
                    """
                ),
                params,
            )

        note = (payload.get("note") or "").strip()
        if "consentExpiresAt" in payload and payload.get("consentExpiresAt"):
            kind, label = "consent_renewed", note or "Consent renewed for 12 months."
        elif dnd_val is not None and not payload.get("channels") and "allowedWindow" not in payload:
            kind = "dnd_updated"
            label = note or ("Added to DND registry (calls blocked)." if dnd_val else "Removed from DND registry.")
        else:
            kind, label = "consent_updated", note or "Consent preferences updated."
        _activity(conn, "customer", customer_id, kind, label, note or None, customer_id)
        # On the consent chain: what was written, hashed, so a later edit of
        # the row is visible against the last authorised one.
        from agent_core import change_log

        change_log.record_consent_change(
            conn,
            tenant_id=current_tenant(),
            actor_user_id=_actor_user_id(),
            customer_id=customer_id,
            change={"kind": kind, "fields": {k: v for k, v in payload.items() if k != "note"}},
        )

    customer = get_customer(customer_id)
    if customer is None:
        raise KeyError("customer_not_found")
    return customer

def opt_out(customer_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    _mod = _db()
    _activity = _mod._activity
    _actor_user_id = _mod._actor_user_id
    _ensure_customer = _mod._ensure_customer
    _id = _mod._id
    current_tenant = _mod.current_tenant
    engine = _mod.engine
    get_customer = _mod.get_customer
    channel_raw = payload["channel"]
    affected = list(_CONSENT_CHANNEL_ORDER) if channel_raw == "all" else [channel_raw]
    source = payload.get("source") or "Agent"
    note = (payload.get("note") or "").strip() or None
    with engine.begin() as conn:
        _ensure_customer(conn, customer_id)
        consent_id = _ensure_consent_record(conn, customer_id)
        for ch in affected:
            channel_value = _consent_channel_db(ch)
            # An opt-out closes **both** purposes, and closes the promotional
            # one even where no promotional consent was ever captured.
            #
            # Somebody who says "stop contacting me" has not opted out of
            # servicing while leaving marketing open, and reading it that way
            # would be the most self-serving construction available. The
            # promotional row is inserted rather than merely updated so that a
            # later promotional capture has an explicit opt-out to overwrite,
            # deliberately, rather than an absence to fill in.
            for consent_purpose in ("servicing", "promotional"):
                conn.execute(
                    text(
                        """
                        INSERT INTO channel_consents
                          (id, consent_id, channel, purpose, status, source, captured_at)
                        VALUES
                          (:id, :consent_id, :channel, :purpose, 'opted_out', :source, now())
                        ON CONFLICT (consent_id, channel, purpose)
                        DO UPDATE SET status = 'opted_out', source = EXCLUDED.source,
                                      captured_at = EXCLUDED.captured_at
                        """
                    ),
                    {
                        "id": f"{consent_id}-{channel_value}-{consent_purpose}",
                        "consent_id": consent_id,
                        "channel": channel_value,
                        "purpose": consent_purpose,
                        "source": source,
                    },
                )
        # Screen shape stores one opt-out event (channel may be "all").
        event_channel = "all" if channel_raw == "all" else _consent_channel_db(channel_raw)
        conn.execute(
            text(
                """
                INSERT INTO optout_events
                  (id, consent_id, channel, source, actor_kind, actor_user_id, note)
                VALUES
                  (:id, :consent_id, :channel, :source, 'human', :actor_user_id, :note)
                """
            ),
            {
                "id": _id("OPTOUT"),
                "consent_id": consent_id,
                "channel": event_channel,
                "source": source,
                "actor_user_id": _actor_user_id(),
                "note": note,
            },
        )
        label = f"Opt-out captured via {source} ({channel_raw})."
        _activity(conn, "customer", customer_id, "opt_out", label, note, customer_id)
        from agent_core import change_log

        change_log.record_consent_change(
            conn,
            tenant_id=current_tenant(),
            actor_user_id=_actor_user_id(),
            customer_id=customer_id,
            change={"kind": "opt_out", "channel": channel_raw, "source": source},
        )
    customer = get_customer(customer_id)
    if customer is None:
        raise KeyError("customer_not_found")
    return customer

