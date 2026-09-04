/**
 * Domain / wire types for the qa surface.
 *
 * Lived in a `data/*-seed.ts` mock factory. Moved here so live `api/`
 * modules do not import their contract from fixtures (WP-048).
 */

export type ScoreBand = "green" | "amber" | "red";
export type ScorecardStatus = "unscored" | "ai_draft" | "final";
export type CoachingStatus = "assigned" | "in_progress" | "done";
export interface RubricCriterion {
  id: string;
  label: string;
  description: string;
  weight: number; // relative within section, %
  critical?: boolean;
}
export interface RubricSection {
  id: string;
  label: string;
  weight: number; // % of total, sections should sum to 100
  criteria: RubricCriterion[];
}
export interface Rubric {
  id: string;
  name: string;
  version: string;
  sections: RubricSection[];
}
export interface ScorecardEntry {
  criterionId: string;
  aiSuggested: number; // 0..5
  score: number; // 0..5 (final)
  note?: string;
  accepted?: boolean;
}
export interface Scorecard {
  id: string;
  callId: string;
  customerName: string;
  disposition: string;
  handledBy: { kind: "bot" | "human" | "handoff"; label: string };
  agentId: string; // reviewed subject (bot key or agent name)
  reviewer?: string;
  status: ScorecardStatus;
  entries: ScorecardEntry[];
  scoredAt?: string;
  createdAt: string;
  rubricId?: string;
}
export interface CoachingAction {
  id: string;
  agentId: string;
  title: string;
  category: string;
  scorecardId?: string;
  callId?: string;
  dueAt: string;
  status: CoachingStatus;
  notes: Array<{ at: string; author: string; text: string }>;
  createdAt: string;
}
export interface CalibrationReviewerScore {
  reviewer: string;
  entries: ScorecardEntry[];
}
export interface CalibrationSession {
  id: string;
  name: string;
  callId: string;
  customerName: string;
  target: ScorecardEntry[]; // target scores
  reviewers: CalibrationReviewerScore[];
  status: "active" | "closed";
  createdAt: string;
}
export interface AgentQaStat {
  agentId: string;
  isBot: boolean;
  scored: number;
  avg: number;
  delta7d: number;
  band: ScoreBand;
  weakestSection: string;
  openCoaching: number;
  trend: number[]; // last 7 avg points
  sectionScores: Array<{ section: string; value: number }>;
}
