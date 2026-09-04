/**
 * Domain / wire types for the routing surface.
 *
 * Lived in a `data/*-seed.ts` mock factory. Moved here so live `api/`
 * modules do not import their contract from fixtures (WP-048).
 */

export type FieldType = "enum" | "number" | "boolean" | "string";
export type FieldMeta = {
  key: string;
  label: string;
  type: FieldType;
  options?: string[];
  unit?: string;
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
