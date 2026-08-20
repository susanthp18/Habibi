"""work_items — a lead is due when its follow-up is due.

Revision ID: 20260817_0082
Revises: 20260817_0081
Create Date: 2026-08-17

Mirrors sql/95_views.sql. SQL is inlined so alembic does not depend on a
sibling Path read at upgrade time.

Two defects in one view:

* The lead branch reported ``captured_at`` as ``sla_due_at``. That timestamp is
  in the past by construction, so every open lead sat in My Workspace as
  permanently overdue, and the scheduled follow-up — the only row that knows
  when the work is actually due — was ignored.
* Lead-linked follow-ups were emitted as their own work item *as well as* the
  lead. One piece of work appeared twice in an agent's queue, under two entity
  types, with two contradictory due dates.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260817_0082"
down_revision: Union[str, Sequence[str], None] = "20260817_0081"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# The whole view, both times: CREATE OR REPLACE VIEW cannot patch one branch of
# a UNION, and the column list must stay identical in name, type and order.
_VIEW = """
CREATE OR REPLACE VIEW work_items AS
SELECT
  'dispute'::TEXT AS entity_type,
  id AS entity_id,
  customer_id,
  assignee_user_id,
  status,
  priority,
  sla_due_at,
  'disputes'::TEXT AS source,
  created_at
FROM disputes
WHERE status IN ('new','under_review','awaiting_customer')
UNION ALL
SELECT
  'callback',
  id,
  customer_id,
  assignee_user_id,
  status,
  priority,
  COALESCE(sla_due_at, scheduled_at),
  'callbacks',
  created_at
FROM callbacks
WHERE status IN ('scheduled','reminded','in_progress','missed','rescheduled')
UNION ALL
SELECT
  'document_request',
  id,
  customer_id,
  assignee_user_id,
  status,
  priority,
  sla_due_at,
  'document_requests',
  created_at
FROM document_requests
WHERE status IN ('requested','generating','failed')
UNION ALL
SELECT
  'promise',
  id,
  customer_id,
  owner_user_id,
  status,
  CASE WHEN status IN ('broken','due_today') THEN 'high' ELSE 'normal' END,
  promised_at,
  'promises',
  created_at
FROM promises
WHERE status IN ('due_today','broken','partial')
UNION ALL
SELECT
  'lead',
  {lead_due},
  'leads',
  l.created_at
FROM leads l
{lead_join}
WHERE l.stage IN ('interested','contacted','qualified')
UNION ALL
SELECT
  'followup',
  id,
  customer_id,
  assignee_user_id,
  status,
  priority,
  due_at,
  'followups',
  created_at
FROM followups
WHERE status IN ('open','in_progress','snoozed'){followup_filter}
UNION ALL
SELECT
  'bounce',
  id,
  customer_id,
  assignee_user_id,
  status,
  'high',
  occurred_at + interval '48 hours',
  'payment_events',
  created_at
FROM payment_events
WHERE kind = 'bounce' AND status IN ('open','in_progress');
"""

_NEW_LEAD_DUE = """  l.id,
  l.customer_id,
  l.owner_user_id,
  l.stage,
  l.priority,
  COALESCE(f.next_due, l.captured_at + INTERVAL '3 days')"""

_NEW_LEAD_JOIN = """LEFT JOIN LATERAL (
  SELECT MIN(due_at) AS next_due
  FROM followups
  WHERE lead_id = l.id AND status IN ('open','in_progress','snoozed')
) f ON TRUE"""

_OLD_LEAD_DUE = """  l.id,
  l.customer_id,
  l.owner_user_id,
  l.stage,
  l.priority,
  l.captured_at"""


def upgrade() -> None:
    op.execute(
        _VIEW.format(
            lead_due=_NEW_LEAD_DUE,
            lead_join=_NEW_LEAD_JOIN,
            followup_filter=" AND lead_id IS NULL",
        )
    )


def downgrade() -> None:
    op.execute(
        _VIEW.format(
            lead_due=_OLD_LEAD_DUE,
            lead_join="",
            followup_filter="",
        )
    )
