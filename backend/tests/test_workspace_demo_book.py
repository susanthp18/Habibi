"""Entra demo logins have no personal queue; the seeded book must still show."""

from __future__ import annotations

import actor_context
import db


def test_empty_personal_queue_falls_back_to_tenant_book(db_tx) -> None:
    token = actor_context.set_actor_user_id("entra-demo-nobody")
    try:
        mine = db.list_work_items(assignee="me")
        whole = db.list_work_items(assignee="all")
    finally:
        actor_context.reset_actor_user_id(token)
    assert mine, "the seeded queue is empty — this is not a demo-book fallback bug"
    assert {row["id"] for row in mine} == {row["id"] for row in whole}


def test_assigned_agent_keeps_a_personal_queue(db_tx) -> None:
    token = actor_context.set_actor_user_id("priya-nair")
    try:
        mine = db.list_work_items(assignee="me")
        whole = db.list_work_items(assignee="all")
    finally:
        actor_context.reset_actor_user_id(token)
    assert mine
    assert all(row["assigneeUserId"] == "priya-nair" for row in mine)
    assert {row["id"] for row in mine} != {row["id"] for row in whole}
