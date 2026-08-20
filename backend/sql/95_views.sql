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
-- A lead's due date is its next open follow-up, not the moment it was
-- captured. captured_at is by definition in the past, so every open lead
-- sorted into the queue as permanently overdue and the one signal that says
-- when the work is actually due — the scheduled follow-up — was ignored.
-- Leads with no follow-up scheduled fall back to a capture SLA so a lead
-- nobody has planned still ages into view instead of disappearing.
SELECT
  'lead',
  l.id,
  l.customer_id,
  l.owner_user_id,
  l.stage,
  l.priority,
  COALESCE(f.next_due, l.captured_at + INTERVAL '3 days'),
  'leads',
  l.created_at
FROM leads l
LEFT JOIN LATERAL (
  SELECT MIN(due_at) AS next_due
  FROM followups
  WHERE lead_id = l.id AND status IN ('open','in_progress','snoozed')
) f ON TRUE
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
-- Lead-linked follow-ups are folded into the lead row above. Emitting both
-- put one piece of work in the agent's queue twice, under two entity types,
-- with two different due dates. Promise-linked follow-ups have no such parent
-- row in this view and still stand on their own.
WHERE status IN ('open','in_progress','snoozed') AND lead_id IS NULL
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

