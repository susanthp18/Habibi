/**
 * Dispute SLA fields the API sends on every dispute row.
 *
 * The server owns the computation (`backend/db.py::_dispute_sla`).
 * `data/dispute-sla.ts` keeps the mock copy of that rule; this module
 * owns the shape so live `api/` modules do not import it from fixtures.
 */

export type SlaTone = "ok" | "warn" | "breach" | "done";

/** Structured SLA carried by every dispute the API returns. */
export interface DisputeSla {
  sla: SlaTone;
  slaLabel: string;
  /** Signed minutes: positive is time remaining, negative is time overdue. */
  slaMinutes: number;
}
