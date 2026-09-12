CREATE TABLE IF NOT EXISTS consent_records (
  id TEXT PRIMARY KEY,
  customer_id TEXT NOT NULL UNIQUE REFERENCES customers(id) ON DELETE CASCADE,
  dnd_registry boolean NOT NULL DEFAULT false,
  expires_at timestamptz,
  allowed_days TEXT,
  allowed_hours TEXT,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS channel_consents (
  id TEXT PRIMARY KEY,
  consent_id TEXT NOT NULL REFERENCES consent_records(id) ON DELETE CASCADE,
  channel TEXT NOT NULL CHECK (channel IN ('voice','whatsapp','sms','email','chat')),
  status TEXT NOT NULL CHECK (status IN ('opted_in','opted_out','dnd','expired')),
  source TEXT,
  weekly_frequency_cap INTEGER,
  used_this_week INTEGER NOT NULL DEFAULT 0,
  captured_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (consent_id, channel)
);
CREATE INDEX IF NOT EXISTS idx_channel_consents_consent_id ON channel_consents(consent_id);

CREATE TABLE IF NOT EXISTS optout_events (
  id TEXT PRIMARY KEY,
  consent_id TEXT NOT NULL REFERENCES consent_records(id) ON DELETE CASCADE,
  channel TEXT NOT NULL CHECK (channel IN ('voice','whatsapp','sms','email','chat','all')),
  source TEXT NOT NULL,
  actor_kind TEXT NOT NULL CHECK (actor_kind IN ('human','bot','customer','system','regulator')),
  actor_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  note TEXT,
  occurred_at timestamptz NOT NULL DEFAULT now(),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_optout_events_consent_id ON optout_events(consent_id);
