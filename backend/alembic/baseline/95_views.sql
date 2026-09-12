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
  id,
  customer_id,
  owner_user_id,
  stage,
  priority,
  captured_at,
  'leads',
  created_at
FROM leads
WHERE stage IN ('interested','contacted','qualified')
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
WHERE status IN ('open','in_progress','snoozed');

