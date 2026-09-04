/**
 * Domain / wire types for the compliance surface.
 *
 * Lived in a `data/*-seed.ts` mock factory. Moved here so live `api/`
 * modules do not import their contract from fixtures (WP-048).
 */

import type { TranscriptTurn } from "./audit";

export type Severity = "critical" | "high" | "medium" | "low";
export type ViolationStatus = "open" | "in_review" | "acknowledged" | "resolved";
export type ActorKind = "bot" | "human";
export type RuleCategory =
  "disclosure" | "prohibited-language" | "consent" | "verification" | "sentiment";
export interface ComplianceRule {
  id: string;
  code: string;
  label: string;
  category: RuleCategory;
  severity: Severity;
  description: string;
}
export interface ViolationNote {
  at: string;
  author: string;
  text: string;
}
export interface Violation {
  id: string;
  callId: string;
  customerName: string;
  ruleId: string;
  severity: Severity;
  occurredAt: string;
  atSec: number;
  actor: { kind: ActorKind; name: string };
  evidence: {
    snippet: string;
    preceding?: TranscriptTurn;
    offending: TranscriptTurn;
    following?: TranscriptTurn;
  };
  status: ViolationStatus;
  assignee?: string;
  notes: ViolationNote[];
}
// ---------- filters ----------
export type CompDateRange = "today" | "7d" | "30d" | "all";
export interface ComplianceFilterState {
  q: string;
  dateRange: CompDateRange;
  severities: Set<Severity>;
  ruleId: "all" | string;
  actor: "all" | ActorKind;
  agent: "all" | string;
  status: "all" | ViolationStatus;
}
