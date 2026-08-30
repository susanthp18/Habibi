// Routing & Logic Builder — synthetic rule engine

export type FieldType = "enum" | "number" | "boolean" | "string";

export type FieldMeta = {
  key: string;
  label: string;
  type: FieldType;
  options?: string[];
  unit?: string;
};

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

export type RuleOperator = "=" | "!=" | ">" | "<" | ">=" | "<=" | "in" | "contains";

export type Condition = {
  id: string;
  field: string;
  op: RuleOperator;
  value: string | number | boolean | string[];
};

// AND-list at top; each entry may itself be an OR-group of Conditions.
export type ConditionNode = Condition | { id: string; or: Condition[] };

export type ActionKey =
  | "route_tier2"
  | "route_specialist"
  | "handoff_human"
  | "play_disclosure"
  | "send_sms"
  | "log_flag"
  | "stop_upsell"
  | "slow_tts"
  | "escalate_supervisor";

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

export type RuleAction = {
  key: ActionKey;
  params?: Record<string, string>;
};

export type RuleCategory = "Escalation" | "Handoff" | "Throttle" | "Compliance" | "Routing";

export type Rule = {
  id: string;
  name: string;
  description: string;
  category: RuleCategory;
  enabled: boolean;
  when: ConditionNode[]; // AND across list
  then: RuleAction;
  triggersLast24h: number;
};

export type AuditEntry = {
  id: string;
  at: string; // ISO
  author: string;
  ruleId?: string;
  ruleName: string;
  action: "created" | "edited" | "reordered" | "toggled" | "deleted" | "duplicated";
  summary: string;
};

export type SimContext = {
  sentiment: string;
  intent: string;
  overdue_amount: number;
  dpd: number;
  verification_status: string;
  consent_dnd: boolean;
  channel: string;
  product: string;
  turn_count: number;
  guardrail_flag: string;
};

const cid = () => Math.random().toString(36).slice(2, 9);

const cond = (field: string, op: RuleOperator, value: Condition["value"]): Condition => ({
  id: cid(),
  field,
  op,
  value,
});

export const RULES_SEED: Rule[] = [
  {
    id: "r1",
    name: "Abusive language → immediate supervisor",
    description: "Barge supervisor when abusive language or legal threats detected.",
    category: "Escalation",
    enabled: true,
    when: [
      {
        id: cid(),
        or: [
          cond("guardrail_flag", "=", "abusive-language"),
          cond("guardrail_flag", "=", "legal-threat"),
        ],
      },
    ],
    then: { key: "escalate_supervisor" },
    triggersLast24h: 4,
  },
  {
    id: "r2",
    name: "High-value angry customer → Tier 2",
    description: "Angry customers with high overdue routed to Tier 2 collections.",
    category: "Routing",
    enabled: true,
    when: [cond("sentiment", "=", "angry"), cond("overdue_amount", ">", 25000)],
    then: { key: "route_tier2" },
    triggersLast24h: 12,
  },
  {
    id: "r3",
    name: "Hardship intent → human handoff",
    description: "Hand off when customer expresses financial hardship.",
    category: "Handoff",
    enabled: true,
    when: [cond("intent", "=", "hardship")],
    then: { key: "handoff_human", params: { team: "Hardship Desk" } },
    triggersLast24h: 7,
  },
  {
    id: "r4",
    name: "Verification failed twice → drop upsell",
    description: "Stop upsell attempts when caller verification fails.",
    category: "Throttle",
    enabled: true,
    when: [cond("verification_status", "=", "failed"), cond("turn_count", ">=", 4)],
    then: { key: "stop_upsell" },
    triggersLast24h: 2,
  },
  {
    id: "r5",
    name: "DND active → SMS follow-up only",
    description: "If DND is on, close voice call and send scheduled SMS.",
    category: "Compliance",
    enabled: true,
    when: [cond("consent_dnd", "=", true), cond("channel", "=", "voice")],
    then: { key: "send_sms", params: { template: "dnd_followup_v2" } },
    triggersLast24h: 5,
  },
  {
    id: "r6",
    name: "Waiver request → disclosure + specialist",
    description: "Play waiver policy disclosure then route to waiver desk.",
    category: "Compliance",
    enabled: true,
    when: [cond("intent", "=", "waiver_request")],
    then: { key: "play_disclosure", params: { doc: "waiver_policy_v3" } },
    triggersLast24h: 9,
  },
  {
    id: "r7",
    name: "High DPD → priority Tier 2 queue",
    description: "Anyone above 60 DPD goes to Tier 2 regardless of sentiment.",
    category: "Routing",
    enabled: false,
    when: [cond("dpd", ">", 60)],
    then: { key: "route_tier2" },
    triggersLast24h: 0,
  },
  {
    id: "r8",
    name: "Frustrated caller → slow TTS pace",
    description: "Slow down speech and add empathy tokens for frustrated callers.",
    category: "Throttle",
    enabled: true,
    when: [cond("sentiment", "=", "frustrated")],
    then: { key: "slow_tts" },
    triggersLast24h: 18,
  },
];

export const AUDIT_SEED: AuditEntry[] = [
  {
    id: cid(),
    at: "2026-07-20T09:12:00Z",
    author: "Priya Menon",
    ruleId: "r1",
    ruleName: "Abusive language → immediate supervisor",
    action: "created",
    summary: "Rule created",
  },
  {
    id: cid(),
    at: "2026-07-20T09:35:00Z",
    author: "Priya Menon",
    ruleId: "r2",
    ruleName: "High-value angry customer → Tier 2",
    action: "created",
    summary: "Rule created",
  },
  {
    id: cid(),
    at: "2026-07-20T11:02:00Z",
    author: "Rahul Verma",
    ruleId: "r2",
    ruleName: "High-value angry customer → Tier 2",
    action: "edited",
    summary: "overdue_amount > 20000 → > 25000",
  },
  {
    id: cid(),
    at: "2026-07-20T14:20:00Z",
    author: "Priya Menon",
    ruleId: "r7",
    ruleName: "High DPD → priority Tier 2 queue",
    action: "toggled",
    summary: "Disabled",
  },
  {
    id: cid(),
    at: "2026-07-21T08:11:00Z",
    author: "Rahul Verma",
    ruleId: "r5",
    ruleName: "DND active → SMS follow-up only",
    action: "created",
    summary: "Rule created",
  },
  {
    id: cid(),
    at: "2026-07-21T08:44:00Z",
    author: "Priya Menon",
    ruleId: "r8",
    ruleName: "Frustrated caller → slow TTS pace",
    action: "created",
    summary: "Rule created",
  },
  {
    id: cid(),
    at: "2026-07-21T09:15:00Z",
    author: "Priya Menon",
    ruleId: "r3",
    ruleName: "Hardship intent → human handoff",
    action: "reordered",
    summary: "priority 5 → 3",
  },
  {
    id: cid(),
    at: "2026-07-21T10:02:00Z",
    author: "You",
    ruleId: "r6",
    ruleName: "Waiver request → disclosure + specialist",
    action: "edited",
    summary: "action → play_disclosure(waiver_policy_v3)",
  },
];

// ---------- Evaluation ----------

function coerce(a: unknown, b: Condition["value"]): [unknown, unknown] {
  if (typeof a === "number" || typeof b === "number") {
    const nb = typeof b === "string" ? Number(b) : b;
    return [Number(a), nb];
  }
  return [a, b];
}

function evalCondition(c: Condition, ctx: SimContext): boolean {
  const raw = ctx[c.field as keyof SimContext];
  const [av, bv] = coerce(raw, c.value);
  switch (c.op) {
    case "=":
      return av === bv;
    case "!=":
      return av !== bv;
    case ">":
      return Number(av) > Number(bv);
    case "<":
      return Number(av) < Number(bv);
    case ">=":
      return Number(av) >= Number(bv);
    case "<=":
      return Number(av) <= Number(bv);
    case "in":
      return Array.isArray(bv)
        ? bv.includes(String(av))
        : String(bv)
            .split(",")
            .map((s) => s.trim())
            .includes(String(av));
    case "contains":
      return String(av).toLowerCase().includes(String(bv).toLowerCase());
  }
}

export type NodeEval = {
  nodeId: string;
  matched: boolean;
  conditions: { id: string; matched: boolean; label: string }[];
  isOr: boolean;
};

export type RuleEval = {
  rule: Rule;
  matched: boolean;
  nodes: NodeEval[];
  latencyMs: number;
};

function labelCondition(c: Condition) {
  const f = FIELDS.find((f) => f.key === c.field);
  return `${f?.label ?? c.field} ${c.op} ${String(c.value)}`;
}

export function evaluateRule(rule: Rule, ctx: SimContext): RuleEval {
  const nodes: NodeEval[] = rule.when.map((n) => {
    if ("or" in n) {
      const conds = n.or.map((c) => ({
        id: c.id,
        matched: evalCondition(c, ctx),
        label: labelCondition(c),
      }));
      return { nodeId: n.id, matched: conds.some((c) => c.matched), conditions: conds, isOr: true };
    }
    const matched = evalCondition(n, ctx);
    return {
      nodeId: n.id,
      matched,
      conditions: [{ id: n.id, matched, label: labelCondition(n) }],
      isOr: false,
    };
  });
  const matched = nodes.every((n) => n.matched) && nodes.length > 0;
  const latencyMs = Math.round((0.15 + Math.random() * 0.4) * 100) / 100;
  return { rule, matched, nodes, latencyMs };
}

export function evaluateRules(rules: Rule[], ctx: SimContext) {
  const results = rules.filter((r) => r.enabled).map((r) => evaluateRule(r, ctx));
  const firing = results.find((r) => r.matched);
  return { results, firing };
}

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
