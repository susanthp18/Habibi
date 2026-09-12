/**
 * Dispute SLA fields the API sends on every dispute row.
 *
 * The server owns the computation (`backend/db.py::_dispute_sla`); nothing in
 * the browser recomputes a label or a tone from slaDueAt.
 */

export type SlaTone = "ok" | "warn" | "breach" | "done";

/** Structured SLA carried by every dispute the API returns. */
export interface DisputeSla {
  sla: SlaTone;
  slaLabel: string;
  /** Signed minutes: positive is time remaining, negative is time overdue. */
  slaMinutes: number;
}
