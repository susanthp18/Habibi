"""Clone a first-party card or skill into a tenant-authored row.

Marketplace import stays first-party-signed only. A clone is origin=tenant and
unsigned until a human signs (G9).
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import text

import db
from agent_core.cards.defaults import (
    COLLECTIONS_BOT_ID,
    INSURANCE_BOT_ID,
    SUPERVISOR_BOT_ID,
    card_dump,
)
from agent_core.cards.templates import template_card, templates

_GRAPHS = Path(__file__).resolve().parent / "graphs"
_GRAPH_BY_BOT = {
    COLLECTIONS_BOT_ID: "collections.json",
    INSURANCE_BOT_ID: "insurance.json",
    SUPERVISOR_BOT_ID: "supervisor.json",
}


def _slug(value: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", (value or "").strip().lower()).strip("-")
    return s or f"card-{uuid.uuid4().hex[:8]}"


def _disk_flow(bot_id: str) -> dict[str, Any]:
    """First-party conversation graph on disk. Empty when this mouth has none."""
    name = _GRAPH_BY_BOT.get(bot_id)
    if not name:
        return {}
    path = _GRAPHS / name
    if not path.is_file():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


def _source_mouth(source: str) -> dict[str, Any] | None:
    """Published version, else the newest version of any status."""
    published = db.get_published_prompt_version(source)
    if published:
        return published
    versions = db.list_prompt_versions(bot_id=source, limit=1)
    return versions[0] if versions else None


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

    mouth = _source_mouth(source)
    if template:
        card = template_card(template)
    elif mouth and isinstance(mouth.get("agentCard"), dict) and mouth["agentCard"]:
        card = dict(mouth["agentCard"])
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
    flow = (mouth or {}).get("flow") or _disk_flow(source) or {}
    prompt = (mouth or {}).get("prompt") or ""
    persona = (mouth or {}).get("persona") or db._DEFAULT_PERSONA
    voice = (mouth or {}).get("voice") or db._DEFAULT_VOICE
    guardrails = (mouth or {}).get("guardrails") or db._DEFAULT_GUARDRAILS
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
