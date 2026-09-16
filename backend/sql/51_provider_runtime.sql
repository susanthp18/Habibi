-- What the call host can actually construct, reported by the process that knows.
--
-- `runtime` used to be computed on read, by importing the model's Pipecat
-- service class into whichever process was asked. The API is never that
-- process: `requirements-voice.txt` is kept out of `requirements.txt` so CRM
-- upgrades are not coupled to Pipecat's transitive graph, which means
-- collections_api has no `pipecat` and no `azure.cognitiveservices.speech`.
-- So the API answered "can *I* import this?" to a screen asking "can the thing
-- that runs calls import this?" and returned `unavailable` for all thirteen
-- models on a stack whose calls were running Azure perfectly well. The Agent
-- Studio refused to bind any provider, and the voice inspector reported
-- "ModuleNotFoundError: No module named 'azure'" against Azure itself.
--
-- Same contract as `measured_latency_*` two columns up: ours, written by the
-- process that measured it, never by the seed. NULL means the voice runtime
-- has not reported since it last started, which reads as `unknown` — an honest
-- third state, distinct from a measured no.
ALTER TABLE provider_models
  ADD COLUMN IF NOT EXISTS runtime TEXT
    CHECK (runtime IN ('live','preview_only','unavailable')),
  ADD COLUMN IF NOT EXISTS runtime_detail TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS runtime_checked_at timestamptz;
