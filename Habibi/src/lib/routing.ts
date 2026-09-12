import type {
  FieldType,
  FieldMeta,
  RuleOperator,
  Condition,
  ConditionNode,
  ActionKey,
  RuleAction,
  RuleCategory,
  Rule,
  AuditEntry,
  SimContext,
  NodeEval,
  RuleEval,
} from "@/api/types/routing";

export const FIELDS: FieldMeta[] = [
  {
    key: "sentiment",
    label: "Sentiment",
    type: "enum",
    options: ["angry", "frustrated", "neutral", "happy"],
  },
  {
    key: "intent",
    label: "Intent",
    type: "enum",
    options: [
      "balance_query",
      "dispute",
      "hardship",
      "waiver_request",
      "payment_intent",
      "upsell_opportunity",
      "escalation",
      "out_of_scope",
    ],
  },
  { key: "overdue_amount", label: "Overdue amount", type: "number", unit: "₹" },
  { key: "dpd", label: "Days past due", type: "number", unit: "d" },
  {
    key: "verification_status",
    label: "Verification status",
    type: "enum",
    options: ["verified", "pending", "failed"],
  },
  { key: "consent_dnd", label: "DND active", type: "boolean" },
  { key: "channel", label: "Channel", type: "enum", options: ["voice", "whatsapp", "sms"] },
  { key: "product", label: "Product", type: "enum", options: ["PL", "HL", "CC", "AL", "BL"] },
  { key: "turn_count", label: "Turn count", type: "number" },
  {
    key: "guardrail_flag",
    label: "Guardrail flag",
    type: "enum",
    options: ["none", "waiver-blocked", "auto-escalate", "legal-threat", "abusive-language"],
  },
];

export const OPERATORS_BY_TYPE: Record<FieldType, RuleOperator[]> = {
  enum: ["=", "!=", "in"],
  number: ["=", "!=", ">", "<", ">=", "<="],
  boolean: ["="],
  string: ["=", "!=", "contains"],
};

export const ACTION_LABEL: Record<ActionKey, string> = {
  route_tier2: "Route to Tier 2",
  route_specialist: "Route to specialist team",
  handoff_human: "Hand off to human agent",
  play_disclosure: "Play compliance disclosure",
  send_sms: "Send SMS template",
  log_flag: "Log flag",
  stop_upsell: "Stop upsell attempts",
  slow_tts: "Slow-down TTS pace",
  escalate_supervisor: "Escalate to supervisor",
};

const cid = () => Math.random().toString(36).slice(2, 9);

const cond = (field: string, op: RuleOperator, value: Condition["value"]): Condition => ({
  id: cid(),
  field,
  op,
  value,
});

export const PRESET_CONTEXTS: { label: string; ctx: SimContext }[] = [
  {
    label: "Angry waiver dispute",
    ctx: {
      sentiment: "angry",
      intent: "waiver_request",
      overdue_amount: 42000,
      dpd: 45,
      verification_status: "verified",
      consent_dnd: false,
      channel: "voice",
      product: "PL",
      turn_count: 6,
      guardrail_flag: "waiver-blocked",
    },
  },
  {
    label: "Hardship — job loss",
    ctx: {
      sentiment: "frustrated",
      intent: "hardship",
      overdue_amount: 18500,
      dpd: 33,
      verification_status: "verified",
      consent_dnd: false,
      channel: "voice",
      product: "HL",
      turn_count: 5,
      guardrail_flag: "none",
    },
  },
  {
    label: "Legal-threat caller",
    ctx: {
      sentiment: "angry",
      intent: "escalation",
      overdue_amount: 60000,
      dpd: 92,
      verification_status: "verified",
      consent_dnd: false,
      channel: "voice",
      product: "PL",
      turn_count: 3,
      guardrail_flag: "legal-threat",
    },
  },
  {
    label: "Happy path — balance query",
    ctx: {
      sentiment: "neutral",
      intent: "balance_query",
      overdue_amount: 5000,
      dpd: 3,
      verification_status: "verified",
      consent_dnd: false,
      channel: "voice",
      product: "CC",
      turn_count: 2,
      guardrail_flag: "none",
    },
  },
  {
    label: "DND-active whatsapp lead",
    ctx: {
      sentiment: "neutral",
      intent: "payment_intent",
      overdue_amount: 12000,
      dpd: 15,
      verification_status: "verified",
      consent_dnd: true,
      channel: "voice",
      product: "CC",
      turn_count: 1,
      guardrail_flag: "none",
    },
  },
];

export const DEFAULT_CONTEXT: SimContext = {
  sentiment: "neutral",
  intent: "balance_query",
  overdue_amount: 10000,
  dpd: 10,
  verification_status: "verified",
  consent_dnd: false,
  channel: "voice",
  product: "PL",
  turn_count: 2,
  guardrail_flag: "none",
};

export function newBlankRule(name = "Untitled rule"): Rule {
  return {
    id: `r_${cid()}`,
    name,
    description: "",
    category: "Routing",
    enabled: true,
    when: [cond("sentiment", "=", "angry")],
    then: { key: "route_tier2" },
    triggersLast24h: 0,
  };
}
