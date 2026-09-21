import type { RedactionRecord } from "@/api/types/redaction";

export type AuditExportPlan =
  { ok: true; recordIds: string[] } | { ok: false; missingCallIds: string[] };

/** Map audit trail call ids (interactions.id) onto redaction_records. */
export function planAuditExport(
  callIds: string[],
  records: Pick<RedactionRecord, "id" | "callId">[],
): AuditExportPlan {
  const byCall = new Map(records.map((r) => [r.callId, r.id]));
  const recordIds: string[] = [];
  const missingCallIds: string[] = [];
  for (const callId of callIds) {
    const redactionId = byCall.get(callId);
    if (redactionId) recordIds.push(redactionId);
    else missingCallIds.push(callId);
  }
  if (missingCallIds.length > 0) return { ok: false, missingCallIds };
  return { ok: true, recordIds };
}
