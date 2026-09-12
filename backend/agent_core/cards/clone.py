"""Clone a first-party card or skill into a tenant-authored row.

Marketplace import stays first-party-signed only. A clone is origin=tenant and
unsigned until a human signs (G9).
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy import text

import db
from agent_core.cards.defaults import card_dump
from agent_core.cards.templates import template_card, templates


def _slug(value: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", (value or "").strip().lower()).strip("-")
    return s or f"card-{uuid.uuid4().hex[:8]}"


def clone_card(
    *,
    template_id: str | None = None,
    source_bot_id: str | None = None,
    name: str | None = None,
) -> dict[str, Any]:
    """Insert a new bots row + draft prompt version. Does not publish."""
    source = (source_bot_id or "").strip()
    template = (template_id or "").strip().lower()
    if template and template not in {t["id"] for t in templates()}:
        raise ValueError("unknown_clone_template")
    if not source:
        source = next((t["sourceBotId"] for t in templates() if t["id"] == template), "") or ""
    if not source:
        raise ValueError("clone_source_required")

    published = db.get_published_prompt_version(source)
    if template:
        card = template_card(template)
    elif published and isinstance(published.get("agentCard"), dict) and published["agentCard"]:
        card = dict(published["agentCard"])
    else:
        try:
            card = card_dump(source)
        except KeyError:
            card = {}
    display = (name or "").strip() or str((card.get("identity") or {}).get("display_name") or "Cloned agent")
    bot_id = f"{_slug(display)}-{uuid.uuid4().hex[:6]}"
    ident = dict(card.get("identity") or {})
    ident["bot_id"] = bot_id
    ident["display_name"] = display
    ident["slug"] = ident.get("slug") or _slug(display)
    card["identity"] = ident

    tenant = db.current_tenant()
    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO bots (id, tenant_id, name, version)
                VALUES (:id, :t, :n, '1.0')
                """
            ),
            {"id": bot_id, "t": tenant, "n": display},
        )
    flow = (published or {}).get("flow") or {}
    prompt = (published or {}).get("prompt") or ""
    persona = (published or {}).get("persona") or db._DEFAULT_PERSONA
    voice = (published or {}).get("voice") or db._DEFAULT_VOICE
    guardrails = (published or {}).get("guardrails") or db._DEFAULT_GUARDRAILS
    db.create_prompt_version(
        {
            "botId": bot_id,
            "label": f"{display} v1",
            "prompt": prompt,
            "persona": persona,
            "voice": voice,
            "guardrails": guardrails,
            "flow": flow,
            "agentCard": card,
            "summary": f"Cloned from {source}",
        }
    )
    row = db.get_agent_studio_card(bot_id)
    if row is None:
        raise RuntimeError("clone_card_missing")
    return row
