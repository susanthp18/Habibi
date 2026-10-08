-- Demo book for My workspace: every active staff login sees its own recent
-- calls, captured promises and an upcoming callback instead of empty tiles.
--
-- Re-runnable. Rows carry stable DEMO-WS- ids and each run re-dates them
-- relative to now(), because the tiles read rolling windows (calls in the
-- last 7 days against the 7 before, callbacks still ahead). Run it before a
-- demo, or daily: a week after the last run the tiles are empty again.
--
-- Contacts nobody. No callback_reminders, promise_reminders or outbound rows
-- are written, which are what the workers send from. Promises are recorded as
-- kept, so the lifecycle sweep never turns them into broken promises for the
-- treatment engine to chase. Existing rows are never updated or deleted.
--
--   docker exec -i collections_db psql -U collections -d collections \
--     -v ON_ERROR_STOP=1 -v tenant=hdfc.retail < scripts/demo_workspace_book.sql

BEGIN;
SELECT set_config('app.tenant_id', :'tenant', true);

-- Who demos: every active login that came through Entra.
CREATE TEMP TABLE demo_users ON COMMIT DROP AS
SELECT u.id AS user_id, row_number() OVER (ORDER BY u.id) - 1 AS k
  FROM users u
 WHERE u.entra_oid IS NOT NULL AND u.status = 'active';

-- The existing book, one account per customer, numbered for rotation.
CREATE TEMP TABLE demo_customers ON COMMIT DROP AS
SELECT c.id AS customer_id, a.id AS account_id,
       COALESCE(NULLIF(a.minimum_due, 0), 2500) AS minimum_due,
       row_number() OVER (ORDER BY c.id) - 1 AS n,
       count(*) OVER () AS total
  FROM customers c
  JOIN LATERAL (SELECT id, minimum_due FROM accounts
                 WHERE customer_id = c.id ORDER BY created_at, id LIMIT 1) a ON TRUE
 WHERE c.tenant_id = :'tenant';

-- Calls: sixteen this week, six the week before, so the tiles show a rising trend.
CREATE TEMP TABLE demo_calls ON COMMIT DROP AS
SELECT 'DEMO-WS-' || left(u.user_id, 12) || '-C' || s.i AS id,
       u.user_id, u.k, s.i, dc.customer_id, dc.account_id, dc.minimum_due,
       CASE WHEN s.i <= 16
            THEN now() - (s.i * interval '10 hours') - interval '50 minutes'
            ELSE now() - interval '7 days 3 hours' - ((s.i - 16) * interval '22 hours')
       END AS started_at,
       180 + (s.i * 37 + u.k * 11) % 300 AS duration_sec
  FROM demo_users u
 CROSS JOIN generate_series(1, 22) AS s(i)
  JOIN demo_customers dc ON dc.n = (u.k * 5 + s.i) % dc.total;

INSERT INTO interactions (id, tenant_id, customer_id, account_id, handler_kind, handler_user_id,
                          channel, direction, status, query_resolved, ptp_captured,
                          sentiment_label, summary, started_at, ended_at, duration_sec)
SELECT id, :'tenant', customer_id, account_id, 'human', user_id,
       'voice', CASE WHEN i % 3 = 0 THEN 'inbound' ELSE 'outbound' END, 'completed',
       i % 4 <> 0, i IN (1, 3, 5, 7),
       (ARRAY['positive', 'neutral', 'neutral', 'negative'])[1 + i % 4],
       (ARRAY['Customer agreed to clear the overdue instalment and confirmed the date.',
              'Explained the outstanding balance; customer will pay after salary credit.',
              'Customer asked for a callback to discuss a part payment plan.',
              'Customer disputed a late fee; case explained and next step agreed.',
              'Verified the customer and confirmed the payment already made.'])[1 + i % 5],
       started_at, started_at + duration_sec * interval '1 second', duration_sec
  FROM demo_calls
ON CONFLICT (id) DO UPDATE
   SET started_at = EXCLUDED.started_at, ended_at = EXCLUDED.ended_at,
       duration_sec = EXCLUDED.duration_sec, status = 'completed';

-- Promises captured on four of this week's calls, already kept.
INSERT INTO promises (id, customer_id, account_id, interaction_id, owner_kind, owner_user_id,
                      amount, paid_amount, promised_at, status, reminder_status, channel, created_at)
SELECT 'DEMO-WS-' || left(user_id, 12) || '-P' || i, customer_id, account_id, id, 'human', user_id,
       minimum_due, minimum_due,
       least(started_at + interval '2 days', now() - interval '1 hour'),
       'kept', 'off', 'voice', started_at + interval '10 minutes'
  FROM demo_calls
 WHERE i IN (1, 3, 5, 7)
ON CONFLICT (id) DO UPDATE
   SET promised_at = EXCLUDED.promised_at, created_at = EXCLUDED.created_at,
       status = 'kept', reminder_status = 'off';

-- Two callbacks ahead, in IST working hours (11:00 and 15:30), assigned to the
-- user. Past ones lapse to missed on their own; the next run puts them ahead.
INSERT INTO callbacks (id, customer_id, account_id, interaction_id, assignee_user_id, reason,
                       scheduled_at, window_mins, status, priority)
SELECT 'DEMO-WS-' || left(user_id, 12) || '-B' || i, customer_id, account_id, id, user_id,
       CASE i WHEN 2 THEN 'Discuss a part payment plan after salary credit'
              ELSE 'Confirm the revised due date for the overdue instalment' END,
       CASE i WHEN 2 THEN current_date + 1 + time '05:30'
              ELSE current_date + 2 + time '10:00' END AT TIME ZONE 'UTC',
       30, 'scheduled', CASE i WHEN 2 THEN 'high' ELSE 'normal' END
  FROM demo_calls
 WHERE i IN (2, 4)
ON CONFLICT (id) DO UPDATE
   SET scheduled_at = EXCLUDED.scheduled_at, status = 'scheduled';

SELECT (SELECT count(*) FROM demo_users) AS users,
       (SELECT count(*) FROM interactions WHERE id LIKE 'DEMO-WS-%') AS calls,
       (SELECT count(*) FROM promises WHERE id LIKE 'DEMO-WS-%') AS promises,
       (SELECT count(*) FROM callbacks WHERE id LIKE 'DEMO-WS-%' AND scheduled_at > now()) AS callbacks_ahead;
COMMIT;
