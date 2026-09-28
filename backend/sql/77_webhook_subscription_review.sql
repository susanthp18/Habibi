-- Existing endpoints retain their subscriptions for audit, but must be
-- explicitly reviewed before new event producers may send customer data.
ALTER TABLE webhook_endpoints
  ADD COLUMN IF NOT EXISTS subscriptions_confirmed_at timestamptz;
ALTER TABLE webhook_endpoints
  ADD COLUMN IF NOT EXISTS destination_tested_at timestamptz;
ALTER TABLE webhook_endpoints
  ADD COLUMN IF NOT EXISTS configuration_version bigint NOT NULL DEFAULT 1;

COMMENT ON COLUMN webhook_endpoints.subscriptions_confirmed_at IS
  'NULL blocks new delivery enqueue; an authorized operator confirms the destination and subscribed event contract.';
COMMENT ON COLUMN webhook_endpoints.destination_tested_at IS
  'Last successful signed test delivery to the current destination and signing secret.';
COMMENT ON COLUMN webhook_endpoints.configuration_version IS
  'Incremented when reviewed destination, subscriptions or retry policy changes; binds live probe and operator review.';
