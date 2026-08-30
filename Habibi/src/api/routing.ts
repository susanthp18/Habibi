// -----------------------------------------------------------------------------
// Routing & Logic Builder — data access seam.
//   Reads: GET /routing-rules + /routing-audit
//   Writes: create / patch / reorder / delete
// -----------------------------------------------------------------------------

import { useQuery } from "@tanstack/react-query";

import {
  AUDIT_SEED,
  RULES_SEED,
  type ActionKey,
  type AuditEntry,
  type Rule,
  type RuleAction,
  type RuleCategory,
} from "@/data/routing-seed";
import { apiDelete, apiGet, apiPatch, apiPost, mockDelay, USE_MOCK } from "./config";

interface RoutingActionApi {
  key: ActionKey;
  params?: Record<string, string> | null;
}

interface RoutingRuleApi {
  id: string;
  name: string;
  description: string;
  category: RuleCategory;
  enabled: boolean;
  priority: number;
  when: Rule["when"];
  then: RoutingActionApi;
  executionCount: number;
  lastFiredAt: string | null;
  triggersLast24h: number;
}

function mapRule(row: RoutingRuleApi): Rule {
  const then: RuleAction = { key: row.then.key };
  if (row.then.params && Object.keys(row.then.params).length > 0) {
    then.params = row.then.params;
  }
  return {
    id: row.id,
    name: row.name,
    description: row.description ?? "",
    category: row.category,
    enabled: row.enabled,
    when: Array.isArray(row.when) ? row.when : [],
    then,
    triggersLast24h: row.triggersLast24h ?? 0,
  };
}

let _mockRules: Rule[] = [...RULES_SEED];
const _mockAudit: AuditEntry[] = [...AUDIT_SEED];

export async function fetchRoutingRules(): Promise<Rule[]> {
  if (USE_MOCK) return mockDelay(_mockRules);
  const rows = await apiGet<RoutingRuleApi[]>("/routing-rules");
  return rows.map(mapRule);
}

export function useRoutingRules() {
  return useQuery({
    queryKey: ["routing-rules"],
    queryFn: fetchRoutingRules,
    staleTime: 15_000,
  });
}

export async function fetchRoutingAudit(): Promise<AuditEntry[]> {
  if (USE_MOCK) return mockDelay(_mockAudit);
  return apiGet<AuditEntry[]>("/routing-audit");
}

export function useRoutingAudit() {
  return useQuery({
    queryKey: ["routing-audit"],
    queryFn: fetchRoutingAudit,
    staleTime: 15_000,
  });
}

export async function createRoutingRule(rule: Rule): Promise<Rule> {
  if (USE_MOCK) {
    _mockRules = [..._mockRules, rule];
    return mockDelay(rule);
  }
  const row = await apiPost<RoutingRuleApi>("/routing-rules", {
    id: rule.id,
    name: rule.name,
    description: rule.description,
    category: rule.category,
    enabled: rule.enabled,
    when: rule.when,
    then: rule.then,
  });
  return mapRule(row);
}

export async function saveRoutingRule(rule: Rule): Promise<Rule> {
  if (USE_MOCK) {
    _mockRules = _mockRules.map((x) => (x.id === rule.id ? rule : x));
    return mockDelay(rule);
  }
  const row = await apiPatch<RoutingRuleApi>(`/routing-rules/${rule.id}`, {
    name: rule.name,
    description: rule.description,
    category: rule.category,
    enabled: rule.enabled,
    when: rule.when,
    then: rule.then,
  });
  return mapRule(row);
}

export async function toggleRoutingRule(id: string, enabled: boolean): Promise<Rule> {
  if (USE_MOCK) {
    _mockRules = _mockRules.map((x) => (x.id === id ? { ...x, enabled } : x));
    const row = _mockRules.find((x) => x.id === id);
    if (!row) throw new Error("routing_rule_not_found");
    return mockDelay(row);
  }
  const row = await apiPatch<RoutingRuleApi>(`/routing-rules/${id}`, { enabled });
  return mapRule(row);
}

export async function reorderRoutingRules(orderedIds: string[]): Promise<Rule[]> {
  if (USE_MOCK) {
    const byId = new Map(_mockRules.map((r) => [r.id, r]));
    _mockRules = orderedIds.map((id) => byId.get(id)).filter(Boolean) as Rule[];
    return mockDelay(_mockRules);
  }
  const rows = await apiPost<RoutingRuleApi[]>("/routing-rules/reorder", { orderedIds });
  return rows.map(mapRule);
}

export async function deleteRoutingRule(id: string): Promise<void> {
  if (USE_MOCK) {
    _mockRules = _mockRules.filter((x) => x.id !== id);
    await mockDelay(undefined);
    return;
  }
  await apiDelete(`/routing-rules/${id}`);
}
