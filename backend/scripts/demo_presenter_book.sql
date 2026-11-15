-- A demo loan book on a presenter's own WhatsApp number.
--
-- A presenter (Susanth, Azhar) demos from their own phone. Its first message
-- files the number as a stub, cust-wa-<number>, with an empty account
-- (outstanding 0, no loan facts), so the agents say "your pending due is $0"
-- and contact policy refuses outreach as settled. This gives the stub a
-- loan with a history the agents can talk through: balance and minimum due,
-- an EMI schedule, ledger, consents, a kept and a broken promise, a resolved
-- fee dispute, a sent statement, a cured bounce.
--
-- Usage (idempotent; ids derive from the customer id):
--   psql -v ON_ERROR_STOP=1 -v cid=cust-wa-<number> < demo_presenter_book.sql
--
-- Everything here is in a terminal state: nothing schedules a reminder, a
-- callback or a send, and the treatment row is mode=simulated. A non-zero
-- balance does make the number reachable by outreach, as the presenter's
-- own phone should be.

SET demo.cid = :'cid';

DO $$
DECLARE
  cid text := current_setting('demo.cid');
  aid text;
  tid text;
  consent text;
  actor text;
  ix_voice text;
BEGIN
  aid := (SELECT id FROM accounts WHERE customer_id = cid ORDER BY created_at LIMIT 1);
  tid := (SELECT tenant_id FROM customers_pii WHERE id = cid);
  IF aid IS NULL OR tid IS NULL THEN
    RAISE EXCEPTION 'demo presenter book: no customer or account for %', cid;
  END IF;
  actor := (SELECT id FROM users WHERE id = 'priya-nair');

  INSERT INTO products (id, tenant_id, name, type)
  VALUES ('personal-loan', tid, 'Personal loan', 'loan')
  ON CONFLICT (id) DO NOTHING;

  UPDATE accounts SET
    product_id = 'personal-loan',
    outstanding = 48750,
    minimum_due = 3900,
    dpd = 18,
    bucket = '0-30',
    apr = 13.75,
    sanctioned_amount = 180000,
    opened_on = COALESCE(opened_on, (now() - interval '300 days')::date),
    status = 'active',
    updated_at = now()
  WHERE id = aid;

  UPDATE customers SET
    timezone = 'Asia/Kolkata',
    language = COALESCE(language, 'en-IN'),
    preferred_window = COALESCE(preferred_window, '10:00-19:00 IST'),
    risk = 'medium',
    risk_score = 58,
    segment = COALESCE(segment, 'retail'),
    dnd = false,
    last_contact_at = now() - interval '3 days'
  WHERE id = cid;

  INSERT INTO emi_installments (id, account_id, installment_index, due_date, amount, paid_on, paid_amount, status)
  VALUES
    ('EMI-' || aid || '-1', aid, 1, now() - interval '78 days', 3900, now() - interval '76 days', 3900, 'paid'),
    ('EMI-' || aid || '-2', aid, 2, now() - interval '48 days', 3900, now() - interval '45 days', 3900, 'paid'),
    ('EMI-' || aid || '-3', aid, 3, now() - interval '18 days', 3900, NULL, NULL, 'overdue'),
    ('EMI-' || aid || '-4', aid, 4, now() + interval '12 days', 3900, NULL, NULL, 'upcoming')
  ON CONFLICT (id) DO UPDATE SET
    due_date = EXCLUDED.due_date, paid_on = EXCLUDED.paid_on,
    paid_amount = EXCLUDED.paid_amount, status = EXCLUDED.status;

  INSERT INTO ledger_entries (id, account_id, type, description, amount, posted_at)
  VALUES
    ('LED-' || aid || '-1', aid, 'charge', 'EMI due', 3900, now() - interval '48 days'),
    ('LED-' || aid || '-2', aid, 'payment', 'UPI payment', -3900, now() - interval '45 days'),
    ('LED-' || aid || '-3', aid, 'fee', 'Late fee', 300, now() - interval '44 days'),
    ('LED-' || aid || '-4', aid, 'waiver', 'Goodwill late-fee waiver', -300, now() - interval '40 days'),
    ('LED-' || aid || '-5', aid, 'charge', 'EMI due (current)', 3900, now() - interval '18 days')
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
    (consent || '-voice', consent, 'voice', 'servicing', 'opted_in', 'demo_book', 5, now() - interval '30 days'),
    (consent || '-whatsapp', consent, 'whatsapp', 'servicing', 'opted_in', 'demo_book', 5, now() - interval '30 days'),
    (consent || '-sms', consent, 'sms', 'servicing', 'opted_in', 'demo_book', 5, now() - interval '30 days'),
    (consent || '-email', consent, 'email', 'servicing', 'opted_out', 'demo_book', 5, now() - interval '30 days')
  ON CONFLICT ON CONSTRAINT ux_channel_consents_consent_channel_purpose DO UPDATE SET status = EXCLUDED.status;

  INSERT INTO customer_notes (id, customer_id, author_user_id, text, pinned)
  VALUES
    ('NOTE-' || cid || '-1', cid, actor, 'Demo book. Outstanding is deliberately non-zero so outreach is not refused as settled.', true),
    ('NOTE-' || cid || '-2', cid, actor, 'Prefers WhatsApp. Salary is credited on the 5th. Email is opted out.', false)
  ON CONFLICT (id) DO UPDATE SET text = EXCLUDED.text, pinned = EXCLUDED.pinned;

  IF actor IS NULL THEN
    RAISE NOTICE 'demo presenter book: balance and consent only (no staff user) for %', cid;
    RETURN;
  END IF;

  ix_voice := 'IX-' || cid || '-VOICE';
  INSERT INTO interactions (
    id, tenant_id, customer_id, account_id, handler_kind, handler_user_id,
    channel, direction, status, disposition, primary_intent, query_resolved, ptp_captured,
    sentiment_label, summary, started_at, ended_at, duration_sec
  ) VALUES (
    ix_voice, tid, cid, aid, 'human', actor,
    'voice', 'outbound', 'completed', 'PTP captured (broken)', 'collections', true, true,
    'neutral', 'Outbound call. Promised this month''s EMI for payday, then missed it.',
    now() - interval '20 days', now() - interval '20 days' + interval '5 minutes', 288
  )
  ON CONFLICT (id) DO UPDATE SET summary = EXCLUDED.summary, status = EXCLUDED.status;

  INSERT INTO promises (
    id, customer_id, account_id, interaction_id, owner_kind, owner_user_id,
    amount, promised_at, status, reminder_status, paid_amount, channel
  ) VALUES
    ('PTP-' || cid || '-KEPT', cid, aid, NULL, 'human', actor,
     3900, now() - interval '45 days', 'kept', 'acknowledged', 3900, 'whatsapp'),
    ('PTP-' || cid || '-BROKEN', cid, aid, ix_voice, 'human', actor,
     3900, now() - interval '16 days', 'broken', 'sent', 0, 'voice')
  ON CONFLICT (id) DO UPDATE SET
    status = EXCLUDED.status, promised_at = EXCLUDED.promised_at, paid_amount = EXCLUDED.paid_amount;

  INSERT INTO disputes (
    id, customer_id, account_id, interaction_id, assignee_user_id, type, disputed_amount,
    source, status, priority, resolution_code, resolution_notes, sla_due_at, transcript_snippet
  ) VALUES (
    'D-' || cid, cid, aid, NULL, actor, 'fee_waiver', 300,
    'whatsapp', 'resolved', 'normal', 'valid_waive_fee', 'Late fee waived as a goodwill gesture.',
    now() - interval '41 days', 'Can you waive the late fee? I paid three days late.'
  )
  ON CONFLICT (id) DO UPDATE SET
    status = EXCLUDED.status, resolution_code = EXCLUDED.resolution_code,
    resolution_notes = EXCLUDED.resolution_notes;

  INSERT INTO document_requests (
    id, customer_id, account_id, template_id, assignee_user_id, doc_type, period,
    requested_via, delivery_channel, status, attempts, priority, size_kb
  )
  SELECT
    'DOC-' || cid, cid, aid, t.id, actor, 'statement', 'last_6_months',
    'agent', 'whatsapp', 'sent', 1, 'normal', 164
  FROM (SELECT id FROM document_templates WHERE id = 'template-statement') t
  ON CONFLICT (id) DO UPDATE SET status = EXCLUDED.status;

  INSERT INTO payment_events (
    id, tenant_id, customer_id, account_id, kind, reason, amount, bounce_fee,
    source, source_ref, status, occurred_at
  ) VALUES (
    'PE-' || cid, tid, cid, aid, 'bounce', 'insufficient_funds', 3900, 250,
    'nach', 'demo-bounce-' || cid, 'cured', now() - interval '48 days'
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

  INSERT INTO activity_events (
    id, tenant_id, entity_type, entity_id, at, actor_kind, actor_user_id, kind, label, note
  ) VALUES
    ('ACT-' || cid || '-1', tid, 'customer', cid, now() - interval '45 days', 'human', actor, 'promise_kept', 'PTP kept', '$3,900 paid by UPI'),
    ('ACT-' || cid || '-2', tid, 'customer', cid, now() - interval '40 days', 'human', actor, 'dispute_resolved', 'Fee waiver', 'Late fee of $300 waived'),
    ('ACT-' || cid || '-3', tid, 'customer', cid, now() - interval '16 days', 'human', actor, 'promise_broken', 'PTP broken', '$3,900 voice promise missed')
  ON CONFLICT (id) DO NOTHING;

  RAISE NOTICE 'demo presenter book ready for % / %', cid, aid;
END $$;
