-- A job carries the request that made it.
--
-- The API stamps every response with X-Request-Id and every log line written
-- inside the request with it; the moment work crossed into a job table that
-- id was gone, so a slow WhatsApp reply, a stuck approval or a failed webhook
-- could not be joined back to the click that caused it. Nullable: workers
-- and sweeps mint jobs with no request behind them.
ALTER TABLE bot_turn_jobs      ADD COLUMN IF NOT EXISTS request_id TEXT;
ALTER TABLE work_runtime_jobs  ADD COLUMN IF NOT EXISTS request_id TEXT;
ALTER TABLE webhook_deliveries ADD COLUMN IF NOT EXISTS request_id TEXT;
