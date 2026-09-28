"""A captured yes/no compares as ``true``, and a corrupt graph survives a keystroke.

* **FLOW-5.** The extract tool declares ``type: boolean`` for a yes/no
  variable, so the model returns JSON ``true`` — and ``FlowVariables.set``
  stored ``str(value)``, which is ``"True"``. ``evaluate_clause`` compares text
  exactly, and the one system boolean the editor teaches against,
  ``identity_verified``, is deliberately lower-cased where it is set "so an
  authored ``equals true`` clause matches". So the editor taught authors to
  write ``true`` and an ``equals true`` edge on anything the flow itself
  captured could never fire. ``test_flow_graph_authoring.py`` pinned the broken
  spelling.

* **FLOW-4.** An unparseable ``prompt_versions.flow`` is served as ``{}`` plus
  ``flowUnreadable`` so the rest of the bot stays reachable. The response model
  materialises that ``{}`` into a populated empty sentinel, so the editor's
  "omit when null" protection did not apply and the first autosave triggered by
  *any* edit wrote the sentinel over the column. The red panel saying the graph
  is corrupt — and claiming "Nothing has been changed" — was replaced by "No
  authored flow" before the operator could act on it.
"""

from __future__ import annotations

import inspect
import json
import uuid

import pytest
from sqlalchemy import text

from tests.conftest import frontend_file

TENANT = "hdfc.retail"


# ---------------------------------------------------------------------------
# FLOW-5 — one spelling of a boolean
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# FLOW-4 — an unreadable graph is not overwritten by accident
# ---------------------------------------------------------------------------


SENTINEL = {"version": 1, "globalTools": [], "nodes": [], "edges": []}
CORRUPT = {"nodes": "not a list", "edges": 7}


def _draft(conn) -> str:
    """A draft carrying a graph the parser refuses."""
    vid = f"pv-unreadable-{uuid.uuid4().hex[:8]}"
    conn.execute(
        text(
            """
            INSERT INTO prompt_versions
              (id, tenant_id, bot_id, status, prompt, persona, voice, guardrails,
               tuning, flow, agent_card, label, summary, created_at, updated_at)
            VALUES
              (:id, :t, 'kaia-v2-4', 'draft', 'p', '{}'::jsonb, '{}'::jsonb, '{}'::jsonb,
               '{}'::jsonb, CAST(:flow AS jsonb), '{}'::jsonb, 'unreadable', '', now(), now())
            """
        ),
        {"id": vid, "t": TENANT, "flow": json.dumps(CORRUPT)},
    )
    return vid


def _stored(conn, vid: str):
    return conn.execute(
        text("SELECT flow FROM prompt_versions WHERE id = :id"), {"id": vid}
    ).scalar()


def test_the_editor_holds_an_unreadable_flow_at_null() -> None:
    """The other half, and the one that stops the request being sent at all."""

    route = frontend_file("src", "routes", "prompt-studio.lazy.tsx")
    body = route.read_text(encoding="utf-8")
    assert "setFlow(start.flowUnreadable ? null : (start.flow ?? null));" in body
    assert "setFlow(start.flow ?? null);" not in body
    # The panel promised a recovery it offered no button for.
    assert "Replace with the built-in script" in body
    assert "Nothing has been changed." not in body
