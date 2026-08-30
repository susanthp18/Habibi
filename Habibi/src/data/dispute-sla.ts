// -----------------------------------------------------------------------------
// Dispute SLA — the fields the API sends, and the mock's copy of the server rule.
//
// The server owns this computation (backend/db.py::_dispute_sla). Every dispute
// it returns — on the queue feed and on the Customer 360 contract — carries the
// same three fields, so the disputes board and the 360 disputes tab render the
// same words for the same dispute. Nothing in the app recomputes a label or a
// tone from slaDueAt; that client-side copy (slaInfo) is what let the board say
// "0h 29m left / at risk" while the 360 tab said "0h left" in plain grey.
//
// mockDisputeSla() exists only for the USE_MOCK branch, where the seed rows
// stand in for the server. It is deliberately a line-for-line mirror of
// _dispute_sla — same thresholds, same label format. Change one, change both.
// -----------------------------------------------------------------------------

export type SlaTone = "ok" | "warn" | "breach" | "done";

/** Structured SLA carried by every dispute the API returns. */
export interface DisputeSla {
  sla: SlaTone;
  slaLabel: string;
  /** Signed minutes: positive is time remaining, negative is time overdue. */
  slaMinutes: number;
}

/** At risk once less than a quarter of the filing→due window remains. */
const WARN_FRACTION = 0.25;

function countdown(ms: number): string {
  const abs = Math.abs(ms);
  const hrs = Math.floor(abs / 3_600_000);
  const mins = Math.floor((abs % 3_600_000) / 60_000);
  return `${hrs}h ${mins}m ${ms < 0 ? "over" : "left"}`;
}

export function mockDisputeSla(d: {
  capturedAt: string;
  slaDueAt?: string | null;
  status: string;
}): DisputeSla {
  if (d.status === "resolved" || d.status === "rejected") {
    return { sla: "done", slaLabel: "Closed", slaMinutes: 0 };
  }
  const due = d.slaDueAt ? Date.parse(d.slaDueAt) : NaN;
  if (Number.isNaN(due)) return { sla: "ok", slaLabel: "Open", slaMinutes: 0 };
  const ms = due - Date.now();
  const slaLabel = countdown(ms);
  const slaMinutes = Math.trunc(ms / 60_000);
  if (ms < 0) return { sla: "breach", slaLabel, slaMinutes };
  const window = due - Date.parse(d.capturedAt);
  if (window > 0 && ms < window * WARN_FRACTION) return { sla: "warn", slaLabel, slaMinutes };
  return { sla: "ok", slaLabel, slaMinutes };
}
