// -----------------------------------------------------------------------------
// Routing & Logic Builder — data access seam.
//   Reads: GET /routing-rules + /routing-audit
//   Writes: create / patch / reorder / delete
// -----------------------------------------------------------------------------

import { useQuery } from "@tanstack/react-query";

import type {
  ActionKey,
  AuditEntry,
  Rule,
  RuleAction,
  RuleCategory,
  RuleEval,
  SimContext,
} from "@/api/types/routing";
import { FIELDS } from "@/lib/routing";
import { apiDelete, apiGet, apiPatch, apiPost } from "./config";

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

/** RoutingSimulateResponse -- POST /routing-rules/simulate. */
interface SimulateApi {
  results: {
    ruleId: string;
    matched: boolean;
    nodes: {
      nodeId: string;
      isOr: boolean;
      matched: boolean;
      conditions: { id: string; matched: boolean }[];
    }[];
  }[];
  firingRuleId: string | null;
}

function conditionLabel(rule: Rule, id: string): string {
  for (const node of rule.when) {
    const conds = "or" in node ? node.or : [node];
    const c = conds.find((x) => x.id === id);
    if (c) {
      const f = FIELDS.find((x) => x.key === c.field);
      return `${f?.label ?? c.field} ${c.op} ${String(c.value)}`;
    }
  }
  return id;
}

/** Dry-run of the rule library on the server's evaluator; writes nothing. */
export async function simulateRoutingRules(
  rules: Rule[],
  context: SimContext,
): Promise<{ results: RuleEval[]; firing: Rule | undefined }> {
  const out = await apiPost<SimulateApi>("/routing-rules/simulate", { context });
  const byId = new Map(rules.map((r) => [r.id, r]));
  const results: RuleEval[] = [];
  for (const r of out.results) {
    const rule = byId.get(r.ruleId);
    if (!rule) continue;
    results.push({
      rule,
      matched: r.matched,
      nodes: r.nodes.map((n) => ({
        nodeId: n.nodeId,
        isOr: n.isOr,
        matched: n.matched,
        conditions: n.conditions.map((c) => ({ ...c, label: conditionLabel(rule, c.id) })),
      })),
    });
  }
  return { results, firing: out.firingRuleId ? byId.get(out.firingRuleId) : undefined };
}

export async function fetchRoutingRules(): Promise<Rule[]> {
  const rows = await apiGet<RoutingRuleApi[]>("/routing-rules");
  return rows.map(mapRule);
}

export function useRoutingRules() {
  return useQuery({
    queryKey: ["routing-rules"],
    queryFn: fetchRoutingRules,
  });
}

export async function fetchRoutingAudit(): Promise<AuditEntry[]> {
  return apiGet<AuditEntry[]>("/routing-audit");
}

export function useRoutingAudit() {
  return useQuery({
    queryKey: ["routing-audit"],
    queryFn: fetchRoutingAudit,
  });
}

export async function createRoutingRule(rule: Rule): Promise<Rule> {
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
  const row = await apiPatch<RoutingRuleApi>(`/routing-rules/${id}`, { enabled });
  return mapRule(row);
}

export async function reorderRoutingRules(orderedIds: string[]): Promise<Rule[]> {
  const rows = await apiPost<RoutingRuleApi[]>("/routing-rules/reorder", { orderedIds });
  return rows.map(mapRule);
}

export async function deleteRoutingRule(id: string): Promise<void> {
  await apiDelete(`/routing-rules/${id}`);
}
