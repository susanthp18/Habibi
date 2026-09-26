-- Demo book for the handset POST /demo/outbound-call dials.
--
-- The button resolves DEMO_OUTBOUND_PHONE. On the CloudUnity demo that number
-- already exists as the WhatsApp stub cust-wa-…, whose account was inserted
-- at outstanding 0, so contact_policy refuses outreach as `settled`.
-- A fresh database has no stub; this creates cust-susanth instead, which is
-- the same persona seed_susanth.py upserts when it is allowed to run.
--
-- Idempotent. Does not place a call or queue a send: reminders are already
-- acknowledged, the treatment row is mode=simulated, and no outbound job
-- is inserted. Child rows that need a user or a bot are skipped when neither
-- reference row exists (a schema-only database, before seed_postgres).

DO $$
DECLARE
  cid text;
  aid text;
  tid text;
  consent text;
  bot text;
  actor text;
  team text;
  ix_wa text;
  ix_voice text;
  conv text;
  ptp_up text;
  ptp_broken text;
  ptp_kept text;
  plan text;
BEGIN
  bot := (SELECT id FROM bots WHERE id = 'collectionsbot-v2-4');
  actor := (SELECT id FROM users WHERE id = 'priya-nair');
  team := (SELECT id FROM teams WHERE id = 'retail-collections');

  IF EXISTS (SELECT 1 FROM customers_pii WHERE id = 'cust-wa-919655282324') THEN
    cid := 'cust-wa-919655282324';
    aid := 'AC-WA-919655282324';
    UPDATE accounts SET
      outstanding = 62400,
      minimum_due = 4800,
      dpd = 32,
      bucket = '31-60',
      apr = COALESCE(apr, 14.5),
      sanctioned_amount = COALESCE(sanctioned_amount, 250000),
      status = 'active',
      updated_at = now()
    WHERE id = aid;
    UPDATE customers SET
      timezone = 'Asia/Kolkata',
      language = COALESCE(language, 'en-IN'),
      preferred_window = COALESCE(preferred_window, '10:00-19:00 IST'),
      risk = 'high',
      risk_score = 72,
      segment = COALESCE(segment, 'retail'),
      dnd = false,
      last_contact_at = now() - interval '2 days'
    WHERE id = cid;
  ELSIF NOT EXISTS (SELECT 1 FROM customers_pii WHERE id = 'cust-susanth')
        AND EXISTS (SELECT 1 FROM tenants WHERE id = 'hdfc.retail') THEN
    INSERT INTO products (id, tenant_id, name, type)
    VALUES ('personal-loan', 'hdfc.retail', 'Personal loan', 'loan')
    ON CONFLICT (id) DO NOTHING;
    INSERT INTO customers (
      id, tenant_id, assigned_user_id, name, phone_primary, email, address,
      timezone, language, preferred_window, dnd, segment, risk, risk_score, last_contact_at
    ) VALUES (
      'cust-susanth', 'hdfc.retail', actor, 'Susanth', '919655282324',
      'susanth@example.com', '12, MG Road, Chennai 600002',
      'Asia/Kolkata', 'en-IN', '10:00-19:00 IST', false, 'retail', 'high', 72,
      now() - interval '2 days'
    );
    cid := 'cust-susanth';
    aid := 'AC-SUSANTH';
    INSERT INTO accounts (
      id, customer_id, product_id, apr, sanctioned_amount, outstanding,
      minimum_due, dpd, bucket, status, opened_on
    ) VALUES (
      aid, cid, 'personal-loan', 14.5, 250000, 62400, 4800, 32, '31-60', 'active',
      now() - interval '420 days'
    )
    ON CONFLICT (id) DO UPDATE SET
      outstanding = EXCLUDED.outstanding,
      minimum_due = EXCLUDED.minimum_due,
      dpd = EXCLUDED.dpd,
      bucket = EXCLUDED.bucket,
      status = EXCLUDED.status;
  ELSE
    RETURN;
  END IF;

  tid := (SELECT tenant_id FROM customers_pii WHERE id = cid);

  INSERT INTO emi_installments (id, account_id, installment_index, due_date, amount, paid_on, paid_amount, status)
  VALUES
    ('EMI-' || aid || '-1', aid, 1, now() - interval '60 days', 4800, now() - interval '55 days', 4800, 'paid'),
    ('EMI-' || aid || '-2', aid, 2, now() - interval '30 days', 4800, now() - interval '28 days', 4800, 'paid'),
    ('EMI-' || aid || '-3', aid, 3, now(), 4800, NULL, NULL, 'overdue'),
    ('EMI-' || aid || '-4', aid, 4, now() + interval '30 days', 4800, NULL, NULL, 'upcoming')
  ON CONFLICT (id) DO UPDATE SET status = EXCLUDED.status, due_date = EXCLUDED.due_date;

  INSERT INTO ledger_entries (id, account_id, type, description, amount, posted_at)
  VALUES
    ('LED-' || aid || '-1', aid, 'charge', 'EMI due', 4800, now() - interval '40 days'),
    ('LED-' || aid || '-2', aid, 'payment', 'UPI payment', -4800, now() - interval '37 days'),
    ('LED-' || aid || '-3', aid, 'fee', 'Late fee', 350, now() - interval '35 days'),
    ('LED-' || aid || '-4', aid, 'waiver', 'Goodwill late-fee waiver', -350, now() - interval '32 days'),
    ('LED-' || aid || '-5', aid, 'charge', 'EMI due (current)', 4800, now() - interval '10 days'),
    ('LED-' || aid || '-6', aid, 'payment', 'Partial UPI', -9600, now() - interval '2 days')
  ON CONFLICT (id) DO NOTHING;

  INSERT INTO consent_records (id, customer_id, dnd_registry, allowed_days, allowed_hours)
  VALUES ('consent-' || cid, cid, false, 'Mon-Sat', '10:00-19:00')
  ON CONFLICT (customer_id) DO UPDATE SET
    allowed_days = EXCLUDED.allowed_days,
    allowed_hours = EXCLUDED.allowed_hours,
    dnd_registry = false;
  consent := (SELECT id FROM consent_records WHERE customer_id = cid);

  INSERT INTO channel_consents (id, consent_id, channel, purpose, status, source, weekly_frequency_cap, captured_at)
  VALUES
    (consent || '-voice', consent, 'voice', 'servicing', 'opted_in', 'demo_book', 5, now() - interval '14 days'),
    (consent || '-whatsapp', consent, 'whatsapp', 'servicing', 'opted_in', 'demo_book', 5, now() - interval '14 days'),
    (consent || '-sms', consent, 'sms', 'servicing', 'opted_in', 'demo_book', 5, now() - interval '14 days'),
    (consent || '-email', consent, 'email', 'servicing', 'opted_out', 'demo_book', 5, now() - interval '14 days')
  ON CONFLICT ON CONSTRAINT ux_channel_consents_consent_channel_purpose DO UPDATE SET status = EXCLUDED.status;

  INSERT INTO customer_notes (id, customer_id, author_user_id, text, pinned)
  VALUES
    ('NOTE-' || cid || '-1', cid, actor, 'Demo book. Outstanding is deliberately non-zero so outreach is not refused as settled.', true),
    ('NOTE-' || cid || '-2', cid, actor, 'Prefers WhatsApp. EMI date can move within 7 days. Email is opted out.', false)
  ON CONFLICT (id) DO UPDATE SET text = EXCLUDED.text, pinned = EXCLUDED.pinned;

  IF bot IS NULL AND actor IS NULL THEN
    RAISE NOTICE 'demo book: balance and consent only (no bot or user yet) for %', cid;
    RETURN;
  END IF;

  ix_wa := 'IX-' || cid || '-WA';
  ix_voice := 'IX-' || cid || '-VOICE';
  conv := 'CV-' || cid || '-WA';

  INSERT INTO interactions (
    id, tenant_id, customer_id, account_id, handler_kind, handler_user_id, handler_bot_id,
    channel, direction, status, disposition, primary_intent, query_resolved, ptp_captured,
    sentiment_label, summary, started_at, ended_at, duration_sec
  ) VALUES (
    ix_voice, tid, cid, aid,
    CASE WHEN actor IS NOT NULL THEN 'human' ELSE 'bot' END,
    CASE WHEN actor IS NOT NULL THEN actor ELSE NULL END,
    CASE WHEN actor IS NOT NULL THEN NULL ELSE bot END,
    'voice', 'outbound', 'completed', 'PTP captured (broken)', 'collections', true, true,
    'negative', 'Outbound call. Committed the EMI, then missed it. Asked for WhatsApp follow-up.',
    now() - interval '28 days', now() - interval '28 days' + interval '6 minutes', 312
  )
  ON CONFLICT (id) DO UPDATE SET summary = EXCLUDED.summary, status = EXCLUDED.status;

  INSERT INTO interactions (
    id, tenant_id, customer_id, account_id, handler_kind, handler_bot_id,
    channel, direction, status, disposition, primary_intent, query_resolved,
    sentiment_label, summary, started_at, ended_at, duration_sec
  )
  SELECT
    ix_wa, tid, cid, aid, 'bot', bot,
    'whatsapp', 'inbound', 'completed', 'Bot contained', 'payment_arrangement', true,
    'neutral', 'WhatsApp thread. Balance, a Friday promise, and a late-fee question.',
    now() - interval '12 minutes', now() - interval '5 minutes', 420
  WHERE bot IS NOT NULL
  ON CONFLICT (id) DO UPDATE SET summary = EXCLUDED.summary, status = EXCLUDED.status;

  IF bot IS NOT NULL THEN
    INSERT INTO interaction_transcript (id, interaction_id, turn_index, speaker, at_sec, text)
    VALUES
      ('TR-' || ix_wa || '-0', ix_wa, 0, 'customer', 0, 'Can I pay the EMI next Friday?'),
      ('TR-' || ix_wa || '-1', ix_wa, 1, 'bot', 20, 'Outstanding is ₹62,400. Minimum due is ₹4,800. I can log a promise for Friday.'),
      ('TR-' || ix_wa || '-2', ix_wa, 2, 'customer', 45, 'Friday works. Please confirm here, not by email.')
    ON CONFLICT (id) DO UPDATE SET text = EXCLUDED.text;

    INSERT INTO conversations (id, interaction_id, customer_id, status, channel, created_at, updated_at)
    VALUES (conv, ix_wa, cid, 'bot', 'whatsapp', now() - interval '12 minutes', now() - interval '5 minutes')
    ON CONFLICT (id) DO UPDATE SET status = EXCLUDED.status, updated_at = EXCLUDED.updated_at;

    INSERT INTO messages (id, conversation_id, sender, body, delivery_status, sent_at)
    VALUES
      ('MSG-' || cid || '-0', conv, 'customer', 'Can I pay the EMI next Friday?', 'delivered', now() - interval '12 minutes'),
      ('MSG-' || cid || '-1', conv, 'bot', 'Outstanding is ₹62,400. Minimum due is ₹4,800. I can log a promise for Friday.', 'delivered', now() - interval '10 minutes'),
      ('MSG-' || cid || '-2', conv, 'customer', 'Friday works. Please confirm here, not by email.', 'delivered', now() - interval '5 minutes')
    ON CONFLICT (id) DO UPDATE SET body = EXCLUDED.body;
  END IF;

  plan := 'PLAN-' || cid;
  INSERT INTO payment_plans (id, customer_id, account_id, status, total_amount)
  VALUES (plan, cid, aid, 'active', 9600)
  ON CONFLICT (id) DO UPDATE SET total_amount = EXCLUDED.total_amount, status = EXCLUDED.status;

  ptp_up := 'PTP-' || cid || '-UP';
  ptp_broken := 'PTP-' || cid || '-BROKEN';
  ptp_kept := 'PTP-' || cid || '-KEPT';

  IF bot IS NOT NULL THEN
    INSERT INTO promises (
      id, customer_id, account_id, interaction_id, owner_kind, owner_bot_id, plan_id,
      amount, promised_at, status, reminder_status, paid_amount, channel
    ) VALUES (
      ptp_up, cid, aid, CASE WHEN bot IS NOT NULL THEN ix_wa ELSE NULL END,
      'bot', bot, plan, 4800, now() + interval '5 days', 'upcoming', 'acknowledged', 0, 'whatsapp'
    )
    ON CONFLICT (id) DO UPDATE SET
      status = EXCLUDED.status, promised_at = EXCLUDED.promised_at, reminder_status = EXCLUDED.reminder_status;
  ELSIF actor IS NOT NULL THEN
    INSERT INTO promises (
      id, customer_id, account_id, owner_kind, owner_user_id, plan_id,
      amount, promised_at, status, reminder_status, paid_amount, channel
    ) VALUES (
      ptp_up, cid, aid, 'human', actor, plan, 4800, now() + interval '5 days', 'upcoming', 'acknowledged', 0, 'whatsapp'
    )
    ON CONFLICT (id) DO UPDATE SET status = EXCLUDED.status, promised_at = EXCLUDED.promised_at;
  END IF;

  IF actor IS NOT NULL THEN
    INSERT INTO promises (
      id, customer_id, account_id, interaction_id, owner_kind, owner_user_id,
      amount, promised_at, status, reminder_status, paid_amount, channel
    ) VALUES (
      ptp_broken, cid, aid, ix_voice, 'human', actor,
      4800, now() - interval '20 days', 'broken', 'sent', 0, 'voice'
    )
    ON CONFLICT (id) DO UPDATE SET status = EXCLUDED.status;

    INSERT INTO promises (
      id, customer_id, account_id, owner_kind, owner_user_id,
      amount, promised_at, status, reminder_status, paid_amount, channel
    ) VALUES (
      ptp_kept, cid, aid, 'human', actor,
      2400, now() - interval '45 days', 'kept', 'acknowledged', 2400, 'whatsapp'
    )
    ON CONFLICT (id) DO UPDATE SET status = EXCLUDED.status, paid_amount = EXCLUDED.paid_amount;
  END IF;

  INSERT INTO promise_reminders (id, promise_id, channel, kind, scheduled_at, sent_at, status)
  VALUES (
    'REM-' || ptp_up, ptp_up, 'whatsapp', 'due', now() - interval '1 day', now() - interval '1 day', 'acknowledged'
  )
  ON CONFLICT (id) DO UPDATE SET status = 'acknowledged', sent_at = EXCLUDED.sent_at;

  INSERT INTO promise_installments (id, plan_id, installment_index, due_date, amount, paid_status)
  VALUES
    ('PI-' || plan || '-1', plan, 1, now() + interval '5 days', 4800, 'upcoming'),
    ('PI-' || plan || '-2', plan, 2, now() + interval '35 days', 4800, 'upcoming')
  ON CONFLICT (id) DO NOTHING;

  INSERT INTO followups (id, promise_id, customer_id, assignee_user_id, status, priority, due_at, note, channel)
  VALUES (
    'FU-' || cid, ptp_up, cid, actor, 'open', 'high', now() + interval '4 days',
    'Confirm the Friday EMI before the due reminder.', 'whatsapp'
  )
  ON CONFLICT (id) DO UPDATE SET status = EXCLUDED.status, due_at = EXCLUDED.due_at;

  INSERT INTO disputes (
    id, customer_id, account_id, interaction_id, assignee_user_id, type, disputed_amount,
    source, status, priority, sla_due_at, transcript_snippet
  ) VALUES (
    'D-' || cid, cid, aid, ix_voice, actor, 'fee_waiver', 350,
    'whatsapp', 'under_review', 'normal', now() + interval '2 days',
    'Can you waive the late fee from last month?'
  )
  ON CONFLICT (id) DO UPDATE SET status = EXCLUDED.status, disputed_amount = EXCLUDED.disputed_amount;

  INSERT INTO document_requests (
    id, customer_id, account_id, template_id, assignee_user_id, doc_type, period,
    requested_via, delivery_channel, status, attempts, priority, size_kb
  )
  SELECT
    'DOC-' || cid, cid, aid, t.id, actor, 'statement', 'last_6_months',
    'agent', 'whatsapp', 'sent', 1, 'normal', 180
  FROM (SELECT id FROM document_templates WHERE id = 'template-statement') t
  ON CONFLICT (id) DO UPDATE SET status = EXCLUDED.status;

  INSERT INTO callbacks (
    id, customer_id, account_id, interaction_id, assignee_user_id, team_id,
    reason, scheduled_at, window_mins, status, priority, transcript_snippet, outcome_notes
  ) VALUES (
    'CB-' || cid, cid, aid, ix_voice, actor, team,
    'Confirm the Friday EMI on WhatsApp', now() + interval '1 day', 30,
    'scheduled', 'normal', 'Friday works.', NULL
  )
  ON CONFLICT (id) DO UPDATE SET status = EXCLUDED.status, scheduled_at = EXCLUDED.scheduled_at;

  INSERT INTO payment_events (
    id, tenant_id, customer_id, account_id, kind, reason, amount, bounce_fee,
    source, source_ref, status, occurred_at
  ) VALUES (
    'PE-' || cid, tid, cid, aid, 'bounce', 'insufficient_funds', 4800, 250,
    'nach', 'demo-bounce-' || cid, 'cured', now() - interval '33 days'
  )
  ON CONFLICT (id) DO UPDATE SET status = 'cured';

  INSERT INTO treatment_decisions (
    id, tenant_id, customer_id, account_id, trigger_kind, mode,
    recommender, recommender_version, feature_schema_version,
    chosen_action, chosen_channel, rationale
  ) VALUES (
    'TD-' || cid, tid, cid, aid, 'broken_ptp', 'simulated',
    'demo_book', '1', '1',
    'voice_bot', 'voice', 'Demo row only. Simulated so the executor does not dial.'
  )
  ON CONFLICT (id) DO UPDATE SET mode = 'simulated', rationale = EXCLUDED.rationale;

  IF tid IS NOT NULL THEN
    INSERT INTO activity_events (
      id, tenant_id, entity_type, entity_id, at, actor_kind, actor_user_id, kind, label, note
    ) VALUES
      ('ACT-' || cid || '-1', tid, 'customer', cid, now() - interval '28 days', 'human', actor, 'promise_broken', 'PTP broken', '₹4,800 voice promise missed'),
      ('ACT-' || cid || '-2', tid, 'customer', cid, now() - interval '10 days', 'human', actor, 'dispute_opened', 'Fee waiver', 'Late fee of ₹350 under review'),
      ('ACT-' || cid || '-3', tid, 'customer', cid, now() - interval '5 minutes', 'bot', NULL, 'promise_captured', 'Promise logged', '₹4,800 next Friday')
    ON CONFLICT (id) DO NOTHING;
  END IF;

  RAISE NOTICE 'demo book ready for % / %', cid, aid;
END $$;
