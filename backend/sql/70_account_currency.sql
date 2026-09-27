-- The currency an account is held in (ISO 4217). Amounts the voice agents
-- speak are formatted in it: "AED 12,500" for a UAE account, "₹12,500" for
-- an Indian one. Existing accounts are rupee accounts.
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS currency TEXT NOT NULL DEFAULT 'INR';
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'accounts_currency_check') THEN
    ALTER TABLE accounts ADD CONSTRAINT accounts_currency_check CHECK (currency ~ '^[A-Z]{3}$');
  END IF;
END $$;
