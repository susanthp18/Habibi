-- Refresh the operator console book so every screen has current, linked rows.
-- Idempotent. IDs are prefixed LIVE- so re-runs update rather than duplicate.
-- Does not place calls or send WhatsApp; it only writes Postgres rows.
--
-- Stories share the same borrowers: a bounce, a PTP, a dispute, a callback,
-- a live call, a WhatsApp thread and a treatment decision all hang off the
-- same customer/account.

BEGIN;

CREATE TEMP TABLE book AS
SELECT
  c.id AS customer_id,
  c.name AS customer_name,
  a.id AS account_id,
  COALESCE(a.outstanding, 25000) AS outstanding,
  COALESCE(a.minimum_due, 2500) AS minimum_due,
  COALESCE(NULLIF(c.assigned_user_id, ''), 'priya-nair') AS agent_id,
  row_number() OVER (
    ORDER BY
      CASE c.risk WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
      a.outstanding DESC NULLS LAST,
      c.id
  ) AS n
FROM customers c
JOIN LATERAL (
  SELECT id, outstanding, minimum_due, status
  FROM accounts
  WHERE customer_id = c.id
  ORDER BY CASE WHEN status = 'active' THEN 0 ELSE 1 END, created_at, id
  LIMIT 1
) a ON TRUE;

CREATE TEMP TABLE refs AS
SELECT
  (SELECT id FROM tenants LIMIT 1) AS tenant_id,
  (SELECT id FROM bots ORDER BY CASE WHEN id = 'collectionsbot-v2-4' THEN 0 ELSE 1 END, id LIMIT 1) AS bot_id,
  (SELECT id FROM teams WHERE id = 'card-collections' LIMIT 1) AS team_id,
  (SELECT id FROM document_templates ORDER BY CASE WHEN doc_type ILIKE '%statement%' THEN 0 ELSE 1 END LIMIT 1) AS statement_template,
  (SELECT id FROM document_templates ORDER BY CASE WHEN doc_type ILIKE '%noc%' THEN 0 ELSE 1 END LIMIT 1) AS noc_template,
  (SELECT id FROM products ORDER BY id LIMIT 1) AS product_id,
  (SELECT id FROM webhook_endpoints ORDER BY id LIMIT 1) AS webhook_endpoint,
  (SELECT id FROM event_types ORDER BY id LIMIT 1) AS event_type,
  (SELECT id FROM qa_rubrics ORDER BY id LIMIT 1) AS rubric_id,
  (SELECT id FROM compliance_rules ORDER BY id LIMIT 1) AS rule_id;

-- ---------------------------------------------------------------------------
-- 1. Re-date the existing seed so 14/30-day windows are not empty.
-- ---------------------------------------------------------------------------
UPDATE interactions
   SET started_at = now() - ((mod(abs(hashtext(id)), 26) + 1) || ' days')::interval
                 - ((mod(abs(hashtext(id)), 8) + 1) || ' hours')::interval,
       ended_at   = now() - ((mod(abs(hashtext(id)), 26)) || ' days')::interval
                 - ((mod(abs(hashtext(id)), 3)) || ' hours')::interval,
       updated_at = now()
 WHERE status = 'completed';

UPDATE promises
   SET created_at  = now() - ((mod(abs(hashtext(id)), 20) + 2) || ' days')::interval,
       promised_at = now() - ((mod(abs(hashtext(id)), 12) + 1) || ' days')::interval,
       updated_at  = now()
 WHERE status IN ('kept', 'broken', 'partial');

UPDATE leads
   SET created_at  = now() - ((mod(abs(hashtext(id)), 20) + 1) || ' days')::interval,
       captured_at = now() - ((mod(abs(hashtext(id)), 18) + 1) || ' days')::interval,
       closed_at   = CASE WHEN stage IN ('won', 'lost')
                          THEN now() - ((mod(abs(hashtext(id)), 8) + 1) || ' days')::interval
                          ELSE closed_at END,
       updated_at  = now();

UPDATE followups
   SET due_at = now() + ((mod(abs(hashtext(id)), 5) - 1) || ' days')::interval,
       updated_at = now()
 WHERE status IN ('open', 'in_progress', 'snoozed');

UPDATE conversations SET updated_at = now() - ((mod(abs(hashtext(id)), 6)) || ' hours')::interval;
UPDATE messages
   SET sent_at = now() - ((mod(abs(hashtext(id)), 12)) || ' hours')::interval,
       created_at = now() - ((mod(abs(hashtext(id)), 12)) || ' hours')::interval;
UPDATE violations
   SET created_at = now() - ((mod(abs(hashtext(id)), 18) + 1) || ' days')::interval;
UPDATE qa_scorecards
   SET scored_at = now() - ((mod(abs(hashtext(id)), 14) + 1) || ' days')::interval,
       created_at = now() - ((mod(abs(hashtext(id)), 14) + 1) || ' days')::interval
 WHERE status <> 'unscored';
UPDATE live_alerts
   SET created_at = now() - ((mod(abs(hashtext(id)), 40) + 2) || ' minutes')::interval
 WHERE acknowledged_at IS NULL;

INSERT INTO ledger_entries (id, account_id, type, description, amount, posted_at, created_at)
SELECT
  'SEED-RECENT-' || a.id || '-' || d.n,
  a.id,
  'payment',
  'EMI collection',
  -1 * ROUND(COALESCE(a.minimum_due, 2500) * (0.6 + mod(d.n * 7, 5) * 0.15), 2),
  now() - (d.n || ' days')::interval,
  now()
FROM (
  SELECT id, minimum_due, row_number() OVER (ORDER BY id) AS rn
  FROM accounts
  WHERE status = 'active'
) a
CROSS JOIN generate_series(1, 44) AS d(n)
WHERE mod(d.n + a.rn::int, 6) = 0
ON CONFLICT (id) DO UPDATE SET
  amount = EXCLUDED.amount,
  posted_at = EXCLUDED.posted_at;

-- ---------------------------------------------------------------------------
-- 2. Live interactions (floor + handoff) and WhatsApp threads (inbox).
-- ---------------------------------------------------------------------------
INSERT INTO interactions (
  id, tenant_id, customer_id, account_id,
  handler_kind, handler_user_id, handler_bot_id,
  channel, direction, status, primary_intent, summary,
  avg_sentiment, sentiment_label, started_at, duration_sec, created_at, updated_at
)
SELECT
  'LIVE-IX-' || lpad(n::text, 2, '0'),
  r.tenant_id,
  b.customer_id,
  b.account_id,
  CASE WHEN n IN (1, 2, 3, 8) THEN 'bot' ELSE 'human' END,
  CASE WHEN n IN (1, 2, 3, 8) THEN NULL ELSE b.agent_id END,
  CASE WHEN n IN (1, 2, 3, 8) THEN r.bot_id ELSE NULL END,
  CASE WHEN n IN (7, 8, 9) THEN 'whatsapp' ELSE 'voice' END,
  CASE WHEN n IN (7, 8) THEN 'inbound' ELSE 'outbound' END,
  'active',
  CASE n
    WHEN 1 THEN 'ptp'
    WHEN 2 THEN 'hardship'
    WHEN 3 THEN 'dispute'
    WHEN 4 THEN 'callback'
    WHEN 5 THEN 'ptp'
    WHEN 6 THEN 'balance_inquiry'
    WHEN 7 THEN 'ptp'
    WHEN 8 THEN 'document_request'
    ELSE 'payment_reminder'
  END,
  CASE n
    WHEN 1 THEN 'Bot collecting EMI; sentiment dropping, waiting for specialist.'
    WHEN 2 THEN 'Borrower reported job loss; hardship path, pending human.'
    WHEN 3 THEN 'Customer disputes last EMI amount; bot escalating.'
    WHEN 4 THEN 'Agent on a promised callback for a broken PTP.'
    WHEN 5 THEN 'Agent negotiating a same-week promise after a NACH bounce.'
    WHEN 6 THEN 'Agent confirming outstanding and offering a pay-link.'
    WHEN 7 THEN 'WhatsApp thread: borrower asking for a statement and a PTP date.'
    WHEN 8 THEN 'Bot WhatsApp: customer sent a receipt photo, needs takeover.'
    ELSE 'Follow-up after yesterday''s bounce notice.'
  END,
  CASE n
    WHEN 1 THEN -0.42
    WHEN 2 THEN -0.55
    WHEN 3 THEN -0.31
    WHEN 4 THEN 0.12
    WHEN 5 THEN -0.08
    WHEN 6 THEN 0.22
    WHEN 7 THEN 0.05
    WHEN 8 THEN -0.18
    ELSE 0.00
  END,
  CASE WHEN n IN (1, 2, 3, 8) THEN 'negative' WHEN n IN (6) THEN 'positive' ELSE 'neutral' END,
  now() - ((n * 7) || ' minutes')::interval,
  n * 90,
  now() - ((n * 7) || ' minutes')::interval,
  now()
FROM book b
CROSS JOIN refs r
WHERE b.n <= 9
ON CONFLICT (id) DO UPDATE SET
  status = EXCLUDED.status,
  started_at = EXCLUDED.started_at,
  ended_at = NULL,
  handler_kind = EXCLUDED.handler_kind,
  handler_user_id = EXCLUDED.handler_user_id,
  handler_bot_id = EXCLUDED.handler_bot_id,
  summary = EXCLUDED.summary,
  avg_sentiment = EXCLUDED.avg_sentiment,
  updated_at = now();

INSERT INTO interaction_participants (id, interaction_id, participant_kind, user_id, bot_id, role, joined_at)
SELECT 'LIVE-IP-C-' || lpad(n::text, 2, '0'), 'LIVE-IX-' || lpad(n::text, 2, '0'),
       'customer', NULL, NULL, 'customer', now() - ((n * 7) || ' minutes')::interval
FROM book WHERE n <= 9
ON CONFLICT (id) DO NOTHING;

INSERT INTO interaction_participants (id, interaction_id, participant_kind, user_id, bot_id, role, joined_at)
SELECT
  'LIVE-IP-H-' || lpad(n::text, 2, '0'),
  'LIVE-IX-' || lpad(n::text, 2, '0'),
  CASE WHEN n IN (1, 2, 3, 8) THEN 'bot' ELSE 'human' END,
  CASE WHEN n IN (1, 2, 3, 8) THEN NULL ELSE agent_id END,
  CASE WHEN n IN (1, 2, 3, 8) THEN (SELECT bot_id FROM refs) ELSE NULL END,
  'primary',
  now() - ((n * 7) || ' minutes')::interval
FROM book WHERE n <= 9
ON CONFLICT (id) DO NOTHING;

INSERT INTO interaction_transcript (id, interaction_id, turn_index, speaker, at_sec, text, sentiment_delta, intent)
SELECT * FROM (VALUES
  ('LIVE-TR-01-1', 'LIVE-IX-01', 1, 'bot', 2, 'This call is recorded. I am calling from HDFC collections about your credit card EMI.', 0.00, 'disclosure'),
  ('LIVE-TR-01-2', 'LIVE-IX-01', 2, 'customer', 18, 'I already paid last week. Why are you calling again?', -0.35, 'paid_already'),
  ('LIVE-TR-01-3', 'LIVE-IX-01', 3, 'bot', 32, 'I can see a NACH bounce on the 14th. The EMI of ₹12,400 did not clear.', -0.10, 'bounce_explain'),
  ('LIVE-TR-01-4', 'LIVE-IX-01', 4, 'customer', 51, 'Then talk to a person. I am not discussing this with a bot.', -0.40, 'escalate'),
  ('LIVE-TR-02-1', 'LIVE-IX-02', 1, 'bot', 3, 'This call is recorded. I am reaching you about the overdue EMI.', 0.00, 'disclosure'),
  ('LIVE-TR-02-2', 'LIVE-IX-02', 2, 'customer', 22, 'I lost my job in August. I cannot pay the full EMI this month.', -0.50, 'hardship'),
  ('LIVE-TR-02-3', 'LIVE-IX-02', 3, 'bot', 40, 'I am connecting you to a specialist who can discuss a hardship plan.', -0.05, 'escalate'),
  ('LIVE-TR-03-1', 'LIVE-IX-03', 1, 'bot', 4, 'This call is recorded. About the charge posted on 8 September.', 0.00, 'disclosure'),
  ('LIVE-TR-03-2', 'LIVE-IX-03', 2, 'customer', 19, 'That interest is wrong. I already raised this. Connect me to someone.', -0.30, 'dispute'),
  ('LIVE-TR-04-1', 'LIVE-IX-04', 1, 'agent', 5, 'This call is recorded. I am Priya from collections, returning your callback.', 0.05, 'disclosure'),
  ('LIVE-TR-04-2', 'LIVE-IX-04', 2, 'customer', 16, 'Can we do ₹8,000 this Friday and the rest next month?', 0.10, 'ptp'),
  ('LIVE-TR-05-1', 'LIVE-IX-05', 1, 'agent', 4, 'This call is recorded. Your NACH returned yesterday for insufficient funds.', 0.00, 'disclosure'),
  ('LIVE-TR-05-2', 'LIVE-IX-05', 2, 'customer', 21, 'Salary is on the 25th. I can pay then. Please do not visit.', -0.05, 'ptp'),
  ('LIVE-TR-07-1', 'LIVE-IX-07', 1, 'customer', 0, 'Hi, I need my account statement and I can pay 6,000 on Friday.', 0.05, 'document_request'),
  ('LIVE-TR-07-2', 'LIVE-IX-07', 2, 'agent', 40, 'I can send the statement on WhatsApp and log a promise for Friday.', 0.10, 'ptp'),
  ('LIVE-TR-08-1', 'LIVE-IX-08', 1, 'customer', 0, 'Paid just now. Screenshot attached. Please stop calling.', -0.15, 'paid_already')
) AS t(id, interaction_id, turn_index, speaker, at_sec, text, sentiment_delta, intent)
ON CONFLICT (id) DO UPDATE SET text = EXCLUDED.text, sentiment_delta = EXCLUDED.sentiment_delta;

INSERT INTO live_alerts (id, interaction_id, kind, severity, reason, created_at)
SELECT * FROM (VALUES
  ('LIVE-AL-01', 'LIVE-IX-01', 'sentiment_drop', 'high', 'Customer asked for a human after bounce explanation.', now() - interval '4 minutes'),
  ('LIVE-AL-02', 'LIVE-IX-02', 'escalation', 'high', 'Hardship / job-loss language. Specialist required.', now() - interval '11 minutes'),
  ('LIVE-AL-03', 'LIVE-IX-03', 'compliance', 'medium', 'Disputed amount — stop dunning until reviewed.', now() - interval '18 minutes'),
  ('LIVE-AL-08', 'LIVE-IX-08', 'loop_detected', 'medium', 'Customer repeating paid-already; bot looping.', now() - interval '2 minutes')
) AS t(id, interaction_id, kind, severity, reason, created_at)
ON CONFLICT (id) DO UPDATE SET
  reason = EXCLUDED.reason,
  acknowledged_at = NULL,
  acknowledged_by_user_id = NULL,
  created_at = EXCLUDED.created_at;

INSERT INTO interaction_handoffs (
  id, interaction_id, from_kind, from_bot_id, to_kind, to_user_id, to_team_id,
  reason, queue, requested_at, accepted_at, completed_at, created_at
)
SELECT
  'LIVE-HO-' || lpad(n::text, 2, '0'),
  'LIVE-IX-' || lpad(n::text, 2, '0'),
  'bot',
  (SELECT bot_id FROM refs),
  'human',
  NULL,
  (SELECT team_id FROM refs),
  CASE n WHEN 1 THEN 'sentiment_drop' WHEN 2 THEN 'hardship' ELSE 'dispute' END,
  'card-collections',
  now() - ((n * 6) || ' minutes')::interval,
  NULL, NULL,
  now() - ((n * 6) || ' minutes')::interval
FROM book WHERE n <= 3
ON CONFLICT (id) DO UPDATE SET
  accepted_at = NULL,
  completed_at = NULL,
  to_user_id = NULL,
  requested_at = EXCLUDED.requested_at;

INSERT INTO conversations (id, interaction_id, customer_id, assigned_user_id, status, channel, created_at, updated_at)
SELECT
  'LIVE-CV-' || lpad(n::text, 2, '0'),
  'LIVE-IX-' || lpad(n::text, 2, '0'),
  customer_id,
  CASE WHEN n = 7 THEN agent_id ELSE NULL END,
  CASE n WHEN 7 THEN 'assigned' WHEN 8 THEN 'needs_human' WHEN 9 THEN 'bot' ELSE 'bot' END,
  'whatsapp',
  now() - interval '3 hours',
  now() - ((n) || ' minutes')::interval
FROM book
WHERE n IN (7, 8, 9)
ON CONFLICT (id) DO UPDATE SET
  status = EXCLUDED.status,
  assigned_user_id = EXCLUDED.assigned_user_id,
  updated_at = EXCLUDED.updated_at;

INSERT INTO messages (id, conversation_id, sender, body, delivery_status, sent_at, created_at)
SELECT * FROM (VALUES
  ('LIVE-MSG-07-1', 'LIVE-CV-07', 'customer', 'Hi, please send my latest statement. I can pay 6000 this Friday.', 'delivered', now() - interval '50 minutes', now() - interval '50 minutes'),
  ('LIVE-MSG-07-2', 'LIVE-CV-07', 'agent', 'I have logged a promise for Friday and I am generating the statement now.', 'delivered', now() - interval '46 minutes', now() - interval '46 minutes'),
  ('LIVE-MSG-07-3', 'LIVE-CV-07', 'customer', 'Ok. After 6pm please, I am at work till then.', 'delivered', now() - interval '12 minutes', now() - interval '12 minutes'),
  ('LIVE-MSG-08-1', 'LIVE-CV-08', 'customer', 'Paid just now. Screenshot attached. Stop calling.', 'delivered', now() - interval '18 minutes', now() - interval '18 minutes'),
  ('LIVE-MSG-08-2', 'LIVE-CV-08', 'bot', 'I cannot confirm a payment from a screenshot. An agent will review this.', 'delivered', now() - interval '16 minutes', now() - interval '16 minutes'),
  ('LIVE-MSG-09-1', 'LIVE-CV-09', 'bot', 'Your EMI of last week did not clear. Reply PAY for a link, or TALK to speak to us.', 'delivered', now() - interval '25 minutes', now() - interval '25 minutes'),
  ('LIVE-MSG-09-2', 'LIVE-CV-09', 'customer', 'PAY', 'delivered', now() - interval '8 minutes', now() - interval '8 minutes')
) AS t(id, conversation_id, sender, body, delivery_status, sent_at, created_at)
ON CONFLICT (id) DO UPDATE SET body = EXCLUDED.body, sent_at = EXCLUDED.sent_at;

INSERT INTO ai_response_suggestions (id, conversation_id, interaction_id, suggestion_text, source, created_at)
VALUES
  ('LIVE-SUG-07', 'LIVE-CV-07', 'LIVE-IX-07', 'I can send the account statement on this chat and hold collections until Friday if you confirm ₹6,000.', 'rag', now()),
  ('LIVE-SUG-08', 'LIVE-CV-08', 'LIVE-IX-08', 'Please take over and match the receipt against ledger before we stop outreach.', 'rag', now())
ON CONFLICT (id) DO UPDATE SET suggestion_text = EXCLUDED.suggestion_text;

-- ---------------------------------------------------------------------------
-- 3. Promises, plans, follow-ups — fill every pipeline column.
-- ---------------------------------------------------------------------------
INSERT INTO payment_plans (id, customer_id, account_id, status, total_amount, created_at, updated_at)
SELECT
  'LIVE-PLAN-' || lpad(n::text, 2, '0'),
  customer_id, account_id, 'active',
  ROUND(minimum_due * 3, 2),
  now() - interval '2 days', now()
FROM book WHERE n <= 6
ON CONFLICT (id) DO UPDATE SET total_amount = EXCLUDED.total_amount, status = 'active';

INSERT INTO promises (
  id, customer_id, account_id, interaction_id, owner_kind, owner_user_id, owner_bot_id,
  plan_id, amount, promised_at, status, reminder_status, paid_amount, channel, created_at, updated_at
)
SELECT
  'LIVE-PTP-' || lpad(n::text, 2, '0'),
  customer_id, account_id,
  CASE WHEN n <= 9 THEN 'LIVE-IX-' || lpad(n::text, 2, '0') ELSE NULL END,
  CASE WHEN n IN (1, 9) THEN 'bot' ELSE 'human' END,
  CASE WHEN n IN (1, 9) THEN NULL ELSE agent_id END,
  CASE WHEN n IN (1, 9) THEN (SELECT bot_id FROM refs) ELSE NULL END,
  CASE WHEN n <= 6 THEN 'LIVE-PLAN-' || lpad(n::text, 2, '0') ELSE NULL END,
  ROUND(minimum_due * (0.4 + (n % 3) * 0.2), 2),
  CASE
    WHEN n IN (1, 2) THEN date_trunc('day', now() AT TIME ZONE 'Asia/Kolkata') AT TIME ZONE 'Asia/Kolkata' + interval '16 hours'
    WHEN n IN (3, 4, 5) THEN now() + ((n) || ' days')::interval
    WHEN n = 6 THEN now() - interval '2 days'
    WHEN n IN (7, 8) THEN now() - interval '5 days'
    ELSE now() - interval '9 days'
  END,
  CASE
    WHEN n IN (1, 2) THEN 'due_today'
    WHEN n IN (3, 4, 5) THEN 'upcoming'
    WHEN n = 6 THEN 'partial'
    WHEN n IN (7, 8) THEN 'broken'
    ELSE 'kept'
  END,
  CASE WHEN n IN (1, 2, 3) THEN 'scheduled' WHEN n IN (7, 8) THEN 'sent' ELSE 'acknowledged' END,
  CASE WHEN n = 6 THEN ROUND(minimum_due * 0.2, 2) WHEN n = 9 THEN ROUND(minimum_due * 0.4, 2) ELSE 0 END,
  CASE WHEN n IN (7, 8, 9) THEN 'whatsapp' WHEN n IN (1) THEN 'voice' ELSE 'voice' END,
  now() - interval '1 day',
  now()
FROM book WHERE n <= 9
ON CONFLICT (id) DO UPDATE SET
  status = EXCLUDED.status,
  promised_at = EXCLUDED.promised_at,
  amount = EXCLUDED.amount,
  paid_amount = EXCLUDED.paid_amount,
  updated_at = now();

INSERT INTO promise_installments (id, plan_id, installment_index, due_date, amount, paid_status)
SELECT
  'LIVE-INST-' || lpad(n::text, 2, '0') || '-' || i,
  'LIVE-PLAN-' || lpad(n::text, 2, '0'),
  i,
  now() + ((i * 10) || ' days')::interval,
  ROUND(minimum_due, 2),
  CASE i WHEN 1 THEN 'due_today' WHEN 2 THEN 'upcoming' ELSE 'upcoming' END
FROM book
CROSS JOIN generate_series(1, 3) AS i
WHERE n <= 6
ON CONFLICT (id) DO UPDATE SET due_date = EXCLUDED.due_date, paid_status = EXCLUDED.paid_status;

INSERT INTO promise_reminders (id, promise_id, channel, kind, scheduled_at, status)
SELECT
  'LIVE-PREM-' || lpad(n::text, 2, '0'),
  'LIVE-PTP-' || lpad(n::text, 2, '0'),
  'whatsapp', 'due',
  now() + interval '12 hours',
  'scheduled'
FROM book
WHERE n <= 9
ON CONFLICT (id) DO UPDATE SET scheduled_at = EXCLUDED.scheduled_at, status = 'scheduled';

INSERT INTO followups (id, promise_id, lead_id, customer_id, assignee_user_id, status, priority, due_at, note, channel)
SELECT
  'LIVE-FU-PTP-' || lpad(n::text, 2, '0'),
  'LIVE-PTP-' || lpad(n::text, 2, '0'),
  NULL,
  customer_id,
  agent_id,
  'open',
  CASE WHEN n IN (1, 7, 8) THEN 'high' ELSE 'normal' END,
  CASE WHEN n IN (1, 2) THEN now() + interval '3 hours' ELSE now() + ((n) || ' days')::interval END,
  'Follow up the live promise on this account.',
  'voice'
FROM book WHERE n <= 9
ON CONFLICT (id) DO UPDATE SET due_at = EXCLUDED.due_at, status = 'open';

-- ---------------------------------------------------------------------------
-- 4. Callbacks — scheduled today / tomorrow, not only July misses.
-- ---------------------------------------------------------------------------
INSERT INTO callbacks (
  id, customer_id, account_id, interaction_id, assignee_user_id, team_id,
  reason, scheduled_at, window_mins, dnd_active, status, priority,
  transcript_snippet, sla_due_at, created_at, updated_at
)
SELECT
  'LIVE-CB-' || lpad(n::text, 2, '0'),
  customer_id, account_id,
  CASE WHEN n <= 9 THEN 'LIVE-IX-' || lpad(n::text, 2, '0') ELSE NULL END,
  agent_id,
  (SELECT team_id FROM refs),
  CASE n WHEN 1 THEN 'broken_ptp' WHEN 2 THEN 'hardship' WHEN 3 THEN 'dispute' ELSE 'general' END,
  CASE
    WHEN n = 1 THEN now() + interval '45 minutes'
    WHEN n = 2 THEN now() + interval '2 hours'
    WHEN n = 3 THEN now() + interval '1 day'
    WHEN n = 4 THEN now() + interval '2 days'
    WHEN n = 5 THEN now() - interval '20 minutes'
    ELSE now() + ((n) || ' hours')::interval
  END,
  30,
  FALSE,
  CASE n WHEN 5 THEN 'in_progress' WHEN 6 THEN 'reminded' ELSE 'scheduled' END,
  CASE WHEN n <= 2 THEN 'high' ELSE 'normal' END,
  'Please call me after work. Do not send the field agent.',
  CASE
    WHEN n = 1 THEN now() + interval '45 minutes'
    WHEN n = 5 THEN now() - interval '20 minutes'
    ELSE now() + interval '1 day'
  END,
  now() - interval '6 hours',
  now()
FROM book WHERE n <= 6
ON CONFLICT (id) DO UPDATE SET
  status = EXCLUDED.status,
  scheduled_at = EXCLUDED.scheduled_at,
  sla_due_at = EXCLUDED.sla_due_at,
  updated_at = now();

INSERT INTO callback_reminders (id, callback_id, channel, scheduled_at, status)
SELECT 'LIVE-CBR-' || lpad(n::text, 2, '0'), 'LIVE-CB-' || lpad(n::text, 2, '0'),
       'whatsapp', now() + interval '30 minutes', 'scheduled'
FROM book WHERE n <= 6
ON CONFLICT (id) DO UPDATE SET scheduled_at = EXCLUDED.scheduled_at, status = 'scheduled';

-- Keep a couple of the original missed rows, but move two onto today's book.
UPDATE callbacks
   SET status = 'scheduled',
       scheduled_at = now() + interval '5 hours',
       sla_due_at = now() + interval '5 hours',
       updated_at = now()
 WHERE id IN (SELECT id FROM callbacks WHERE id LIKE 'CB-%' ORDER BY id LIMIT 2);

-- ---------------------------------------------------------------------------
-- 5. Disputes — every board column, tied to the live calls.
-- ---------------------------------------------------------------------------
INSERT INTO disputes (
  id, customer_id, account_id, interaction_id, assignee_user_id, type,
  disputed_amount, source, status, priority, sla_due_at, transcript_snippet,
  created_at, updated_at
)
SELECT
  'LIVE-DSP-' || lpad(n::text, 2, '0'),
  customer_id, account_id,
  CASE WHEN n <= 9 THEN 'LIVE-IX-' || lpad(n::text, 2, '0') ELSE NULL END,
  CASE WHEN n = 1 THEN NULL ELSE agent_id END,
  CASE n
    WHEN 1 THEN 'paid_already'
    WHEN 2 THEN 'wrong_amount'
    WHEN 3 THEN 'fee_waiver'
    WHEN 4 THEN 'duplicate_charge'
    WHEN 5 THEN 'fraud'
    ELSE 'not_my_account'
  END,
  ROUND(minimum_due * (0.3 + n * 0.05), 2),
  CASE WHEN n <= 3 THEN 'bot' ELSE 'agent' END,
  CASE n
    WHEN 1 THEN 'new'
    WHEN 2 THEN 'under_review'
    WHEN 3 THEN 'awaiting_customer'
    WHEN 4 THEN 'resolved'
    WHEN 5 THEN 'rejected'
    ELSE 'new'
  END,
  CASE WHEN n IN (1, 5) THEN 'urgent' WHEN n = 2 THEN 'high' ELSE 'normal' END,
  now() + ((CASE WHEN n <= 3 THEN n ELSE 8 END) || ' days')::interval,
  CASE n
    WHEN 1 THEN 'I already paid last week. Why are you calling again?'
    WHEN 2 THEN 'That interest is wrong. I already raised this.'
    WHEN 3 THEN 'Waive the bounce fee. The return was the bank''s delay.'
    ELSE 'Please check the ledger before you call again.'
  END,
  now() - ((n) || ' hours')::interval,
  now()
FROM book WHERE n <= 6
ON CONFLICT (id) DO UPDATE SET
  status = EXCLUDED.status,
  sla_due_at = EXCLUDED.sla_due_at,
  disputed_amount = EXCLUDED.disputed_amount,
  updated_at = now();

INSERT INTO dispute_evidence (id, dispute_id, storage_ref, filename, mime_type, size_bytes, hash, uploaded_by_user_id)
SELECT
  'LIVE-EV-' || lpad(n::text, 2, '0'),
  'LIVE-DSP-' || lpad(n::text, 2, '0'),
  'minio://dispute-evidence/hdfc.retail/LIVE-DSP-' || lpad(n::text, 2, '0') || '.pdf',
  'receipt-' || lpad(n::text, 2, '0') || '.pdf',
  'application/pdf',
  128000,
  md5('LIVE-DSP-' || n::text),
  agent_id
FROM book WHERE n <= 4
ON CONFLICT (id) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 6. Documents — requested / generating / failed sitting on the same people.
-- ---------------------------------------------------------------------------
INSERT INTO document_requests (
  id, customer_id, account_id, template_id, interaction_id, assignee_user_id,
  doc_type, requested_via, delivery_channel, status, attempts, priority, sla_due_at,
  created_at, updated_at
)
SELECT
  'LIVE-DOC-' || lpad(n::text, 2, '0'),
  customer_id, account_id,
  CASE WHEN n % 2 = 0 THEN (SELECT noc_template FROM refs) ELSE (SELECT statement_template FROM refs) END,
  CASE WHEN n IN (7, 8) THEN 'LIVE-IX-' || lpad(n::text, 2, '0') ELSE 'LIVE-IX-07' END,
  agent_id,
  CASE WHEN n % 2 = 0 THEN 'no_dues_certificate' ELSE 'account_statement' END,
  CASE WHEN n <= 3 THEN 'bot_chat' ELSE 'agent' END,
  CASE WHEN n % 2 = 0 THEN 'email' ELSE 'whatsapp' END,
  CASE n WHEN 1 THEN 'requested' WHEN 2 THEN 'generating' WHEN 3 THEN 'failed' ELSE 'sent' END,
  CASE WHEN n = 3 THEN 2 ELSE 1 END,
  CASE WHEN n = 3 THEN 'high' ELSE 'normal' END,
  now() + interval '8 hours',
  now() - interval '2 hours',
  now()
FROM book WHERE n <= 5
ON CONFLICT (id) DO UPDATE SET
  status = EXCLUDED.status,
  sla_due_at = EXCLUDED.sla_due_at,
  updated_at = now();

-- ---------------------------------------------------------------------------
-- 7. Bounces + treatment decisions + holds (decision intelligence + workspace).
-- ---------------------------------------------------------------------------
INSERT INTO payment_events (
  id, tenant_id, customer_id, account_id, kind, reason, amount, bounce_fee,
  source, source_ref, status, assignee_user_id, occurred_at, created_at, updated_at
)
SELECT
  'LIVE-PE-' || lpad(n::text, 2, '0'),
  (SELECT tenant_id FROM refs),
  customer_id, account_id,
  'bounce',
  CASE n WHEN 1 THEN 'insufficient_funds' WHEN 2 THEN 'technical' WHEN 3 THEN 'mandate_expired' ELSE 'insufficient_funds' END,
  ROUND(minimum_due, 2),
  CASE WHEN n IN (1, 4) THEN 350 ELSE NULL END,
  'nach',
  'NACH-LIVE-' || lpad(n::text, 2, '0') || '-' || to_char(now(), 'YYYYMMDD'),
  CASE n WHEN 5 THEN 'in_progress' WHEN 6 THEN 'cured' ELSE 'open' END,
  agent_id,
  now() - ((n * 9) || ' hours')::interval,
  now() - ((n * 9) || ' hours')::interval,
  now()
FROM book WHERE n <= 6
ON CONFLICT (id) DO UPDATE SET
  status = EXCLUDED.status,
  occurred_at = EXCLUDED.occurred_at,
  amount = EXCLUDED.amount,
  updated_at = now();

INSERT INTO treatment_holds (
  id, tenant_id, customer_id, account_id, kind, reason, source,
  interaction_id, placed_by_user_id, sla_due_at, expires_at, confirmation_state, writer
)
SELECT
  'LIVE-HOLD-' || lpad(n::text, 2, '0'),
  (SELECT tenant_id FROM refs),
  customer_id, account_id,
  CASE n WHEN 2 THEN 'hardship' WHEN 3 THEN 'dispute' WHEN 5 THEN 'complaint' ELSE 'hardship' END,
  CASE n
    WHEN 2 THEN 'Job loss reported on the live call. Pause dunning while hardship is assessed.'
    WHEN 3 THEN 'Open amount dispute. Do not represent the mandate until reviewed.'
    WHEN 5 THEN 'Customer mentioned ombudsman. Complaint hold for 14 days.'
    ELSE 'Temporary hold while the bounce is worked with a PTP.'
  END,
  CASE WHEN n <= 3 THEN 'bot' ELSE 'manual' END,
  CASE WHEN n <= 9 THEN 'LIVE-IX-' || lpad(n::text, 2, '0') ELSE NULL END,
  agent_id,
  now() + interval '2 days',
  now() + interval '14 days',
  'confirmed',
  CASE WHEN n <= 3 THEN 'bot' ELSE 'manual' END
FROM book WHERE n IN (2, 3, 5)
ON CONFLICT (id) DO UPDATE SET
  reason = EXCLUDED.reason,
  released_at = NULL,
  expires_at = EXCLUDED.expires_at,
  sla_due_at = EXCLUDED.sla_due_at,
  updated_at = now();

INSERT INTO treatment_decisions (
  id, tenant_id, customer_id, account_id, interaction_id,
  trigger_kind, trigger_ref, mode, recommender, recommender_version, feature_schema_version,
  chosen_action, chosen_channel, expected_value, propensity, explore_kind,
  rationale, enacted, enacted_at, outcome, created_at
)
SELECT
  'LIVE-TD-' || lpad(n::text, 2, '0') || '-' || step,
  (SELECT tenant_id FROM refs),
  customer_id, account_id,
  CASE WHEN n <= 9 THEN 'LIVE-IX-' || lpad(n::text, 2, '0') ELSE NULL END,
  CASE WHEN n IN (7, 8) THEN 'broken_ptp' ELSE 'bounce' END,
  CASE WHEN n IN (7, 8) THEN 'LIVE-PTP-' || lpad(n::text, 2, '0') ELSE 'LIVE-PE-' || lpad(n::text, 2, '0') END,
  'shadow',
  'treatment.v1', '2026.09', 'features.v1',
  CASE step WHEN 1 THEN 'whatsapp' WHEN 2 THEN 'voice_bot' ELSE 'human_call' END,
  CASE step WHEN 1 THEN 'whatsapp' WHEN 2 THEN 'voice' ELSE 'voice' END,
  ROUND(minimum_due * 0.15, 2),
  0.42 + step * 0.1,
  'greedy',
  CASE step
    WHEN 1 THEN 'First touch after the bounce: WhatsApp with pay-link inside the 24h window.'
    WHEN 2 THEN 'No reply. Voice bot retry inside the statutory window.'
    ELSE 'Still open. Escalate to a human callback today.'
  END,
  step < 3,
  CASE WHEN step < 3 THEN now() - ((4 - step) || ' hours')::interval ELSE NULL END,
  CASE WHEN n = 6 AND step = 3 THEN 'ptp' ELSE NULL END,
  now() - ((3 - step) || ' hours')::interval
FROM book
CROSS JOIN generate_series(1, 3) AS step
WHERE n <= 6
ON CONFLICT (id) DO UPDATE SET
  rationale = EXCLUDED.rationale,
  enacted = EXCLUDED.enacted,
  trigger_ref = EXCLUDED.trigger_ref,
  created_at = EXCLUDED.created_at;

-- ---------------------------------------------------------------------------
-- 8. Leads stay on the same borrowers; refresh open follow-ups.
-- ---------------------------------------------------------------------------
INSERT INTO followups (id, promise_id, lead_id, customer_id, assignee_user_id, status, priority, due_at, note, channel)
SELECT
  'LIVE-FU-LEAD-' || l.id,
  NULL,
  l.id,
  l.customer_id,
  COALESCE(l.owner_user_id, 'priya-nair'),
  'open',
  COALESCE(l.priority, 'normal'),
  now() + interval '1 day',
  'Re-engage the open offer captured on the last contact.',
  'whatsapp'
FROM leads l
WHERE l.stage IN ('interested', 'contacted', 'qualified')
ON CONFLICT (id) DO UPDATE SET due_at = EXCLUDED.due_at, status = 'open';

-- ---------------------------------------------------------------------------
-- 9. Consent, compliance, QA on the live book.
-- ---------------------------------------------------------------------------
INSERT INTO optout_events (id, consent_id, channel, source, actor_kind, created_at)
SELECT
  'LIVE-OPT-' || lpad(b.n::text, 2, '0'),
  cr.id,
  CASE WHEN b.n % 2 = 0 THEN 'email' ELSE 'sms' END,
  'customer_request',
  'customer',
  now() - ((b.n) || ' days')::interval
FROM book b
JOIN consent_records cr ON cr.customer_id = b.customer_id
WHERE b.n IN (2, 5, 8)
ON CONFLICT (id) DO NOTHING;

INSERT INTO violations (
  id, interaction_id, customer_id, rule_id, actor_kind, actor_bot_id, actor_user_id,
  status, assignee_user_id, description, at_sec, created_at, updated_at
)
SELECT
  'LIVE-VIO-01', 'LIVE-IX-01', b.customer_id, r.rule_id,
  'bot', r.bot_id, NULL, 'open', b.agent_id,
  'Customer asked to stop; bot continued the bounce explanation for two more turns.',
  51, now() - interval '8 minutes', now()
FROM book b CROSS JOIN refs r WHERE b.n = 1
ON CONFLICT (id) DO UPDATE SET status = 'open', created_at = EXCLUDED.created_at;

INSERT INTO qa_scorecards (
  id, interaction_id, rubric_id, subject_user_id, subject_bot_id, reviewer_user_id,
  status, total_score, band, scored_at, created_at, updated_at
)
SELECT
  'LIVE-QA-04', 'LIVE-IX-04', r.rubric_id, b.agent_id, NULL, 'anita-rao',
  'final', 86.5, 'strong', now() - interval '10 minutes', now() - interval '10 minutes', now()
FROM book b CROSS JOIN refs r WHERE b.n = 4
ON CONFLICT (id) DO UPDATE SET total_score = EXCLUDED.total_score, scored_at = EXCLUDED.scored_at;

-- ---------------------------------------------------------------------------
-- 10. Knowledge base, billing, webhooks, audit, presence.
-- ---------------------------------------------------------------------------
INSERT INTO kb_documents (
  id, tenant_id, type, version, status, enabled, title, tags, last_indexed_at, created_at, updated_at
)
SELECT * FROM (VALUES
  ('LIVE-KB-PTP', (SELECT tenant_id FROM refs), 'sop', 'v1', 'indexed', TRUE,
   'Promise-to-pay capture and reminder', '["ptp","collections"]'::jsonb, now(), now(), now()),
  ('LIVE-KB-HARDSHIP', (SELECT tenant_id FROM refs), 'policy', 'v1', 'indexed', TRUE,
   'Hardship, bereavement and complaint holds', '["hardship","rbi"]'::jsonb, now(), now(), now()),
  ('LIVE-KB-BOUNCE', (SELECT tenant_id FROM refs), 'sop', 'v1', 'indexed', TRUE,
   'NACH/UPI bounce first touch', '["bounce","nach"]'::jsonb, now(), now(), now()),
  ('LIVE-KB-WA', (SELECT tenant_id FROM refs), 'compliance', 'v1', 'indexed', TRUE,
   'WhatsApp 24-hour service window', '["whatsapp","dpdp"]'::jsonb, now(), now(), now())
) AS t(id, tenant_id, type, version, status, enabled, title, tags, last_indexed_at, created_at, updated_at)
ON CONFLICT (id) DO UPDATE SET status = 'indexed', last_indexed_at = now(), title = EXCLUDED.title;

INSERT INTO kb_chunks (id, document_id, chunk_index, text, created_at)
SELECT * FROM (VALUES
  ('LIVE-CH-PTP-1', 'LIVE-KB-PTP', 0, 'A promise is a dated rupee amount on a specific account. Capture channel, amount and date. Do not invent a date the borrower did not say.', now()),
  ('LIVE-CH-HARD-1', 'LIVE-KB-HARDSHIP', 0, 'Job loss, bereavement and ombudsman mentions are holds. Stop dunning until a specialist releases the hold.', now()),
  ('LIVE-CH-BNC-1', 'LIVE-KB-BOUNCE', 0, 'A NACH bounce is a case. First touch inside 48 hours, prefer WhatsApp if the 24h window is open, else a statutory-window voice attempt.', now()),
  ('LIVE-CH-WA-1', 'LIVE-KB-WA', 0, 'Free-form WhatsApp is allowed only inside 24 hours of a customer message. Outside that window use an approved template.', now())
) AS t(id, document_id, chunk_index, text, created_at)
ON CONFLICT (id) DO UPDATE SET text = EXCLUDED.text;

INSERT INTO faq_pairs (id, linked_document_id, intent, question, answer, enabled)
SELECT * FROM (VALUES
  ('LIVE-FAQ-01', 'LIVE-KB-PTP', 'ptp', 'Can I pay next Friday instead of today?', 'Yes, if you name an amount and a date we will log a promise and pause the bounce case until that morning.', TRUE),
  ('LIVE-FAQ-02', 'LIVE-KB-BOUNCE', 'bounce', 'Why did you call after my EMI date?', 'The auto-debit did not clear. This is a bounce, not a new charge. We will send a pay-link and stop once the amount posts.', TRUE),
  ('LIVE-FAQ-03', 'LIVE-KB-HARDSHIP', 'hardship', 'I lost my job, what happens now?', 'We place a hardship hold, stop extra calls, and a specialist discusses a reduced plan. Keep your registered number reachable.', TRUE)
) AS t(id, linked_document_id, intent, question, answer, enabled)
ON CONFLICT (id) DO UPDATE SET answer = EXCLUDED.answer, enabled = TRUE;

INSERT INTO webhook_deliveries (
  id, endpoint_id, event_type_id, payload, http_status, attempt_number, latency_ms,
  status, delivery_mode, created_at, updated_at
)
SELECT
  'LIVE-WH-' || lpad(g::text, 2, '0'),
  r.webhook_endpoint,
  r.event_type,
  jsonb_build_object('event', 'promise.kept', 'source', 'live-book', 'n', g),
  CASE WHEN g = 3 THEN 500 ELSE 200 END,
  1,
  80 + g * 15,
  CASE WHEN g = 3 THEN 'server_err' WHEN g = 4 THEN 'pending' ELSE 'success' END,
  'simulated',
  now() - ((g) || ' hours')::interval,
  now()
FROM generate_series(1, 6) AS g
CROSS JOIN refs r
WHERE r.webhook_endpoint IS NOT NULL AND r.event_type IS NOT NULL
ON CONFLICT (id) DO UPDATE SET status = EXCLUDED.status, created_at = EXCLUDED.created_at;

INSERT INTO audit_log (id, tenant_id, actor_user_id, action, entity_type, entity_id, payload, created_at)
SELECT
  'LIVE-AUD-' || lpad(n::text, 2, '0'),
  (SELECT tenant_id FROM refs),
  agent_id,
  CASE n WHEN 1 THEN 'promise.create' WHEN 2 THEN 'hold.place' WHEN 3 THEN 'dispute.create' ELSE 'callback.schedule' END,
  CASE n WHEN 1 THEN 'promise' WHEN 2 THEN 'treatment_hold' WHEN 3 THEN 'dispute' ELSE 'callback' END,
  CASE n WHEN 1 THEN 'LIVE-PTP-01' WHEN 2 THEN 'LIVE-HOLD-02' WHEN 3 THEN 'LIVE-DSP-01' ELSE 'LIVE-CB-01' END,
  jsonb_build_object('source', 'live-book'),
  now() - ((n * 20) || ' minutes')::interval
FROM book WHERE n <= 8
ON CONFLICT (id) DO UPDATE SET created_at = EXCLUDED.created_at;

UPDATE agent_presence
   SET status = CASE id
                  WHEN 'priya-nair' THEN 'wrap_up'
                  WHEN 'arjun-mehta' THEN 'available'
                  WHEN 'meera-iyer' THEN 'on_break'
                  WHEN 'sara-khan' THEN 'available'
                  ELSE status
                END,
       updated_at = now()
 WHERE id IN ('priya-nair', 'arjun-mehta', 'meera-iyer', 'sara-khan');

INSERT INTO activity_events (
  id, tenant_id, entity_type, entity_id, at, actor_kind, actor_user_id, kind, label, note
)
SELECT
  'LIVE-ACT-' || lpad(n::text, 2, '0'),
  (SELECT tenant_id FROM refs),
  'customer',
  customer_id,
  now() - ((n * 15) || ' minutes')::interval,
  'human',
  agent_id,
  'note_added',
  'Live book activity',
  'Operational row written so Customer 360, workspace and audit share the same event.'
FROM book WHERE n <= 9
ON CONFLICT (id) DO UPDATE SET at = EXCLUDED.at, note = EXCLUDED.note;

COMMIT;

-- Verify the screens' source tables.
SELECT 'promises' AS t, status, count(*) FROM promises GROUP BY 1,2
UNION ALL SELECT 'callbacks', status, count(*) FROM callbacks GROUP BY 1,2
UNION ALL SELECT 'disputes', status, count(*) FROM disputes GROUP BY 1,2
UNION ALL SELECT 'docs', status, count(*) FROM document_requests GROUP BY 1,2
UNION ALL SELECT 'work_items', entity_type, count(*) FROM work_items GROUP BY 1,2
UNION ALL SELECT 'payment_events', status, count(*) FROM payment_events GROUP BY 1,2
UNION ALL SELECT 'holds', kind, count(*) FROM treatment_holds WHERE released_at IS NULL GROUP BY 1,2
UNION ALL SELECT 'interactions', status, count(*) FROM interactions WHERE id LIKE 'LIVE-%' GROUP BY 1,2
UNION ALL SELECT 'handoffs_open', 'pending', count(*) FROM interaction_handoffs WHERE accepted_at IS NULL AND completed_at IS NULL AND id LIKE 'LIVE-%'
ORDER BY 1,2;
