/**
 * Domain / wire types for the workspace surface.
 *
 * The wire shape the api/ module for this surface reads and writes.
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
