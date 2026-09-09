-- The Door · which card answers a contact, as an authored row rather than an env var.
--
-- Today `runtime_entry_bot_id()` reads `os.getenv("BOT_ID") or db.DEFAULT_BOT_ID`
-- and takes no arguments at all -- not the channel, not the dialled number, not
-- the ANI, not the customer. Every inbound contact on every channel therefore
-- resolves the same card, and the other published cards are reachable only by a
-- mid-conversation `handoff_to_agent`.
--
-- One row per (channel, address). `address` is the *dialled* number for voice --
-- the `To` leg, which `voice/bot.py` already parks in `session.extra["to_number"]`
-- and which no routing code has ever read. Routing deliberately does NOT consult
-- the caller (ANI) or the CRM: `twilio_ops.lookup_customer_for_caller` sits under
-- a bare `except`, so letting it choose the answering card would turn one flaky
-- round trip into "a different agent picked up", unauditable after the fact.
--
-- `address IS NULL` is the channel-level default, and it is how the text mouths
-- resolve: `bot_runtime._bot_id()` has no address concept to pass, so WhatsApp
-- matches the NULL row. That asymmetry is inherent to address-keyed routing, and
-- keeping both shapes in one table is what stops it becoming two mechanisms.
--
-- Empty on arrival. `resolve_entry` falls back to today's env lookup when no row
-- matches and when the table is absent, so an unmigrated database and an
-- unconfigured one both behave exactly as they do now.

CREATE TABLE IF NOT EXISTS entry_bindings (
  id            text PRIMARY KEY,
  tenant_id     text NOT NULL,
  channel       text NOT NULL,
  address       text,
  bot_id        text NOT NULL REFERENCES bots(id),
  enabled       boolean NOT NULL DEFAULT true,
  note          text,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now()
);

-- One binding per address per channel, and one default per channel. Two partial
-- uniques rather than one over (channel, address): NULL is distinct from NULL in
-- a UNIQUE constraint, so a plain unique would happily accept four channel
-- defaults and route by whichever the planner returned first.
CREATE UNIQUE INDEX IF NOT EXISTS entry_bindings_addr_uq
  ON entry_bindings (tenant_id, channel, address)
  WHERE address IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS entry_bindings_default_uq
  ON entry_bindings (tenant_id, channel)
  WHERE address IS NULL;
