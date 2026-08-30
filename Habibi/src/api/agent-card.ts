/**
 * The Agent Card, as the backend defines it.
 *
 * Mirrors `backend/agent_core/cards/schema.py` — that Pydantic model is the
 * source of truth and this is a hand-written reflection of it. Keys are
 * snake_case because the wire format is: the card round-trips through
 * `prompt_versions.agent_card` as JSON and is parsed by `parse_card`, so the
 * shape here has to be the shape on the wire, not the shape a TypeScript
 * codebase would have chosen.
 *
 * Why this file exists at all
 * ---------------------------
 * The studio used to hold the card as `Record<string, unknown>` and hand it to
 * six tabs as `card={effectiveCard as never}`. `as never` does not loosen a
 * check, it removes it — so nothing verified that the keys Tools, Skills,
 * Connectors, Policy, Evals and Agent graph read and write exist, are spelled
 * the way the backend spells them, or still match after a schema change.
 *
 * That matters more here than in most places, because **every model in
 * schema.py sets `extra="forbid"`**. An unknown key is not ignored; it fails
 * validation. So a typo'd or invented field does not degrade gracefully — it
 * makes the card unpublishable, and the first sign of it is a publish that
 * rejects a card the editor was perfectly happy to build.
 *
 * Everything is optional
 * ----------------------
 * Not laziness, and not a copy of the backend's required/default split. This
 * type describes a card *in the editor*, and the editor's own starting value is
 * `{}` — a bot that has never been authored has no identity, which is precisely
 * what `isAuthored()` tests for before letting anything be saved. Marking
 * `identity` required would make that guard unexpressible and push every panel
 * back to casting.
 */

/** `AgentCard.schema_version` — bumped only by a migration. */
export const CARD_SCHEMA_VERSION = "1";

export type Channel = "voice" | "whatsapp" | "sms" | "internal" | "mcp" | "a2a";
export type DataClass = "pii" | "money" | "marketing" | "internal";
export type MemoryScope = "turn" | "call" | "case" | "customer";
export type PinMode = "exact" | "caret";
/** Single-valued today. A binding exists to be *checked*, not to be chosen. */
export type PolicyBinding = "required";
export type EvalRequire = "regression" | "redteam" | "capability" | "twin" | "outbound";
/**
 * The three on the first line describe a canary that is *slow*. The three on the
 * second describe one that is *harmful*, and outbound needed its own: an inbound
 * bug annoys one caller who rang us, and by the time a latency percentile has
 * moved on an outbound bug, the calls have been made.
 */
export const ROLLBACK_TRIGGERS = [
  "slo_miss",
  "live_qa_burn",
  "eval_fail",
  "abandon_rate",
  "third_party_leak",
  "optout_spike",
] as const;

export type RollbackTrigger = (typeof ROLLBACK_TRIGGERS)[number];

/**
 * Narrow whatever the API returned to triggers the card can actually hold.
 *
 * `card.experiment.auto_rollback` is a Literal on a model with
 * `extra="forbid"`, so a value outside the list does not degrade - it makes the
 * card fail validation, and the first symptom is a publish rejecting a card
 * this editor was happy to build. Dropping the unknown value here is the
 * quieter failure and the recoverable one.
 */
export function asRollbackTriggers(raw: unknown): RollbackTrigger[] {
  if (!Array.isArray(raw)) return [];
  const known = new Set<string>(ROLLBACK_TRIGGERS);
  return raw.filter((t): t is RollbackTrigger => typeof t === "string" && known.has(t));
}
export type HumanGateRequire = "identity" | "floor" | "both";
export type Direction = "inbound" | "outbound" | "both";
export type VoicemailMode = "always" | "never" | "first_attempt_only" | "engine";
export type TimeOfDay = "engine" | "fixed" | "spread";
export type PoolKind = "service_1600" | "promotional" | "general";
export type PostCallQa = "always" | "sampled" | "never";

/**
 * Mirrors `flow_graph.OBJECTIVES`. The graph owns this vocabulary because the
 * graph is what must contain a matching entry node; the card restates it so a
 * typo fails at parse rather than at dial time.
 */
export type Objective =
  | "inbound"
  | "pre_due_reminder"
  | "bounce_cure"
  | "dpd_reminder"
  | "broken_ptp_chase"
  | "hardship_intake"
  | "mandate_reregistration"
  | "document_chase"
  | "callback_honour"
  | "welcome_onboarding"
  | "retention_save"
  | "cross_sell"
  | "manual_outbound";

/**
 * Engines the author cannot unbind. All four must appear on `tools.locked`;
 * two are catalog tools the mouth may call, two are Python engines with no
 * mouth tool yet.
 */
export const LOCKED_POLICY_ENGINES = [
  "recommend_next_offer",
  "recommend_treatment",
  "evaluate_authority",
  "evaluate_live_qa",
] as const;

/** Keys `PolicyBindings` must carry. Compile gate G3 checks all six. */
export const REQUIRED_POLICY_KEYS = [
  "reco",
  "treatment",
  "authority",
  "live_qa",
  "routing",
  "dnd",
] as const;

export type PolicyKey = (typeof REQUIRED_POLICY_KEYS)[number];

export type CardIdentity = {
  bot_id?: string;
  slug?: string;
  display_name?: string;
  purpose?: string;
  owner_user_id?: string | null;
  channels?: Channel[];
  data_class?: DataClass[];
  regulator_tags?: string[];
};

/** Pointers, not copies — the columns on `prompt_versions` are canonical. */
export type CardMouthRef = {
  flow_ref?: string | null;
  languages?: string[];
};

export type CardSkillRef = {
  skill_id?: string;
  version?: string;
  pin?: PinMode;
};

export type CardTools = {
  include?: string[];
  locked?: string[];
  max_voice_tools?: number;
};

export type CardHandoff = {
  to_bot_id?: string;
  payload_schema?: Record<string, unknown>;
  when?: string;
};

export type CardConnector = {
  connector_id?: string;
  allow_prefixes?: string[];
};

export type PolicyBindings = Partial<Record<PolicyKey, PolicyBinding>>;

export type Compaction = {
  raw_last_n?: number;
  summarize_over_budget?: boolean;
};

export type CardMemory = {
  scopes?: MemoryScope[];
  compaction?: Compaction;
};

export type HumanGate = {
  tool_name?: string;
  require?: HumanGateRequire;
};

export type CardEval = {
  suite_id?: string | null;
  require?: EvalRequire[];
};

/**
 * What to do when a machine answers. Silence is a decision too.
 *
 * `include_grievance_contact` is not a nicety: a voicemail is a recovery
 * communication, and RBI para 100AA requires the grievance officer's details in
 * all of them, so "please call us back" alone is a communication made without a
 * disclosure that was owed.
 */
export type VoicemailPolicy = {
  leave?: VoicemailMode;
  /** 5–60. */
  max_sec?: number;
  include_grievance_contact?: boolean;
};

/** One mission this agent can be sent on. */
export type CardObjective = {
  key?: Objective;
  /** Node key in `prompt_versions.flow` whose `entryFor` claims this mission.
   *  Compile gate G-OB2 checks the two agree. */
  entry_node?: string;
  /** Outcome codes from the Closer's taxonomy that close the case. */
  success?: string[];
  partial?: string[];
  /** 30–1800. */
  max_duration_sec?: number;
  /** Empty means no product may be mentioned on this mission at all — the safe
   *  default rather than an omission, because a servicing call is not a sales
   *  call and the borrower did not ask to be sold to. */
  allowed_offers?: string[];
  /** Named cap in `agent_core.authority`. */
  authority_profile?: string | null;
  voicemail?: VoicemailPolicy;
  cadence?: string;
};

/**
 * When to try again. Mechanical, and never a decision about the action —
 * only the treatment engine may change *what* is done. That boundary is what
 * stops a dialler quietly inventing an escalation ladder of its own.
 */
export type CardCadence = {
  name?: string;
  /** 1–10. */
  max_attempts?: number;
  /** 1–5, per borrower per day. Bounded again at runtime by contact_policy's
   *  own cap, which a card can only ever lower. */
  per_day?: number;
  /** Hours before attempt 2, 3, … A shorter list repeats its last value. */
  backoff_hours?: number[];
  retry_on?: string[];
  /** Terminal for the case whatever the attempt count says. */
  stop_on?: string[];
  /** A bot_id on the handoff allowlist, or "human". */
  escalate_to?: string | null;
  time_of_day?: TimeOfDay;
};

export type PostCallRule = {
  when?: string;
  do?: string[];
};

export type CardPostCall = {
  on_outcome?: PostCallRule[];
  written_followup?: boolean;
  obligations?: boolean;
  qa?: PostCallQa;
};

/**
 * Everything about being the one who dialled.
 *
 * Lives on the card rather than in a campaigns screen so that the sentence the
 * agent said and the schedule that produced the call carry one version number:
 * `prompt_versions` publishes prompt, persona, voice, guardrails, flow and this
 * atomically. A regulator asking why a borrower got four calls in three days
 * must get one answer, not two audit trails.
 */
export type CardOutbound = {
  direction?: Direction;
  objectives?: CardObjective[];
  cadences?: CardCadence[];
  post_call?: CardPostCall;
  /** Caller-ID pool. A service-only pool (TRAI 1600 series) forbids
   *  promotional content — compile gate G-OB4. */
  number_pool?: string | null;
  pool_kind?: PoolKind;
  /** 0–100. Slots reserved out of the outbound fleet gate so a cross-sell
   *  campaign cannot starve the bounce-cure queue. 0 shares the general pool. */
  concurrency_share?: number;
  carrier_amd?: boolean;
  ivr_traversal?: boolean;
  /** 15–300. */
  ivr_max_sec?: number;
};

export type CardExperiment = {
  /** 0–100. */
  traffic_pct?: number;
  shadow?: boolean;
  auto_rollback?: RollbackTrigger[];
};

export type CardA2A = {
  expose?: boolean;
  skill_ids?: string[];
};

/**
 * One mouth's compile-time contract.
 *
 * Adding a member here without adding it to `schema.py` makes the card
 * unpublishable rather than merely unvalidated — see `extra="forbid"` above.
 * `backend/tests/test_agent_card_schema_drift.py` fails if the two lists of
 * top-level members stop matching.
 */
export type AgentCard = {
  schema_version?: string;
  identity?: CardIdentity;
  mouth?: CardMouthRef;
  skills?: CardSkillRef[];
  tools?: CardTools;
  handoffs?: CardHandoff[];
  connectors?: CardConnector[];
  policy_bindings?: PolicyBindings;
  memory?: CardMemory;
  outbound?: CardOutbound;
  human_gates?: HumanGate[];
  eval?: CardEval;
  experiment?: CardExperiment;
  a2a?: CardA2A | null;
};

/** Every top-level member, for the drift test and for `extra="forbid"` checks. */
export const AGENT_CARD_MEMBERS = [
  "schema_version",
  "identity",
  "mouth",
  "skills",
  "tools",
  "handoffs",
  "connectors",
  "policy_bindings",
  "memory",
  "outbound",
  "human_gates",
  "eval",
  "experiment",
  "a2a",
] as const;

/**
 * A card that has never been authored has no identity, so it cannot be saved.
 *
 * Matches `schema.py::is_authored` in spirit but asks the stricter question the
 * UI actually needs: not "is this non-empty JSON" but "does it name a bot".
 */
export function isAuthoredCard(card: AgentCard | null | undefined): boolean {
  return Boolean(card?.identity?.bot_id);
}
