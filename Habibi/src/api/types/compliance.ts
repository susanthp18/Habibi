/**
 * Domain / wire types for the compliance surface.
 *
 * `Violation` is `ViolationListResponse` on the wire: the row carries the
 * code and label of the rule it hit, so nothing here looks a rule up.
 */

import type { TranscriptTurn } from "./audit";

export type Severity = "critical" | "high" | "medium" | "low";
export type ViolationStatus = "open" | "in_review" | "acknowledged" | "resolved";
export type ActorKind = "bot" | "human";
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
  ruleCode: string;
  ruleLabel: string;
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
  ruleId: "all" | (string & {});
  actor: "all" | ActorKind;
  agent: "all" | (string & {});
  status: "all" | ViolationStatus;
}
