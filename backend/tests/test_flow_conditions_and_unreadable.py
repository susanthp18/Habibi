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

import db_prompt_studio as studio
import flow_graph as fg
from flow_vars import FlowVariables, evaluate_clause
from tests.conftest import frontend_file

TENANT = "hdfc.retail"


def _expr(variable: str, operator: str, value):
    return fg.FlowExpressionClause(variable=variable, operator=operator, value=value)


# ---------------------------------------------------------------------------
# FLOW-5 — one spelling of a boolean
# ---------------------------------------------------------------------------


def test_a_captured_boolean_is_stored_the_way_the_editor_teaches() -> None:
    variables = FlowVariables()
    variables.update({"wants_plan": True, "has_paid": False})
    assert variables.get("wants_plan") == "true"
    assert variables.get("has_paid") == "false"


def test_an_equals_true_clause_now_fires_on_a_captured_boolean() -> None:
    """The finding, as the author would hit it: a yes/no variable, an
    ``equals true`` edge, and an edge that never fired."""
    variables = FlowVariables({"wants_plan": True})
    assert evaluate_clause(_expr("wants_plan", "equals", "true"), variables)
    assert not evaluate_clause(_expr("wants_plan", "equals", "false"), variables)


def test_it_matches_the_system_boolean_it_was_out_of_step_with() -> None:
    captured = FlowVariables({"verified_by_flow": True})
    system = FlowVariables(context=lambda: {"identity_verified": "true"})
    clause = _expr("x", "equals", "true")
    assert evaluate_clause(_expr("verified_by_flow", "equals", "true"), captured)
    assert evaluate_clause(_expr("identity_verified", "equals", "true"), system)
    assert clause.value == "true"


def test_normalisation_happens_where_the_value_enters_the_bag() -> None:
    """Not at each call site. ``set`` is the one door, so no future writer has
    to remember which path a value came in through."""
    src = inspect.getsource(FlowVariables.set)
    assert "_as_text(value)" in src


def test_a_non_boolean_is_untouched() -> None:
    variables = FlowVariables({"n": 42, "s": "True", "none": None})
    assert variables.get("n") == "42"
    # A caller who really wrote the string keeps it. Only bools are respelled.
    assert variables.get("s") == "True"
    assert variables.get("none") == ""


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


def test_the_row_is_served_as_unreadable_not_as_unauthored() -> None:
    assert studio._prompt_flow(CORRUPT) == {"flow": {}, "flowUnreadable": True}
    assert studio._prompt_flow({}) == {"flow": {}, "flowUnreadable": False}


def test_an_autosave_cannot_erase_it(db_tx) -> None:
    vid = _draft(db_tx)
    assert studio._refuses_flow_write(db_tx, vid, SENTINEL, {"flow": SENTINEL})
    assert _stored(db_tx, vid) == CORRUPT


def test_the_refusal_is_a_409_not_a_silent_skip(db_tx) -> None:
    """Silently dropping the write would leave the editor believing it saved."""
    vid = _draft(db_tx)
    with pytest.raises(ValueError, match="flow_unreadable_not_replaced"):
        studio.patch_prompt_version(vid, {"flow": SENTINEL})
    assert _stored(db_tx, vid) == CORRUPT


def test_an_explicit_replacement_goes_through(db_tx) -> None:
    vid = _draft(db_tx)
    studio.patch_prompt_version(vid, {"flow": SENTINEL, "replaceUnreadable": True})
    assert _stored(db_tx, vid) == SENTINEL


def test_loading_the_built_in_script_needs_no_flag(db_tx) -> None:
    """Recovering by replacing the corrupt row with a real graph must not
    require the operator to find a switch."""
    vid = _draft(db_tx)
    graph = fg.empty_graph().model_dump()
    graph["nodes"].append(
        {
            "id": "n-1",
            "key": "greet",
            "type": "conversation",
            "position": {"x": 0, "y": 0},
            "data": {"name": "Greet", "instructions": "hello", "isStart": True},
        }
    )
    assert not studio._refuses_flow_write(db_tx, vid, graph, {"flow": graph})


def test_a_readable_row_is_never_protected(db_tx) -> None:
    """An author who genuinely wants to clear a good graph still can."""
    vid = _draft(db_tx)
    db_tx.execute(
        text("UPDATE prompt_versions SET flow = CAST(:f AS jsonb) WHERE id = :id"),
        {"id": vid, "f": json.dumps(SENTINEL)},
    )
    assert not studio._refuses_flow_write(db_tx, vid, SENTINEL, {"flow": SENTINEL})


def test_a_version_with_no_stored_graph_is_never_protected(db_tx) -> None:
    vid = _draft(db_tx)
    db_tx.execute(
        text("UPDATE prompt_versions SET flow = '{}'::jsonb WHERE id = :id"), {"id": vid}
    )
    assert not studio._refuses_flow_write(db_tx, vid, SENTINEL, {"flow": SENTINEL})


def test_the_editor_holds_an_unreadable_flow_at_null() -> None:
    """The other half, and the one that stops the request being sent at all."""

    route = frontend_file("src", "routes", "prompt-studio.lazy.tsx")
    body = route.read_text(encoding="utf-8")
    assert "setFlow(start.flowUnreadable ? null : (start.flow ?? null));" in body
    assert "setFlow(start.flow ?? null);" not in body
    # The panel promised a recovery it offered no button for.
    assert "Replace with the built-in script" in body
    assert "Nothing has been changed." not in body
