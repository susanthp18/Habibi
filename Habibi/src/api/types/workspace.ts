/**
 * Domain / wire types for the workspace surface.
 *
 * Lived in a `data/*-seed.ts` mock factory. Moved here so live `api/`
 * modules do not import their contract from fixtures (WP-048).
 */

export type SlaLevel = "ok" | "warn" | "breach";
export interface QueueRow {
  id: string;
  customer: string;
  accountId: string;
  type: string;
  detail: string;
  amount?: number;
  ageHours: number;
  sla: SlaLevel;
  slaLabel: string;
}
