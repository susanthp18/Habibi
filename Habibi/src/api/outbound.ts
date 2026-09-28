// Outbound — the attempt ledger and placing one operator call.
//
// Every number here was uncomputable before the attempt ledger: an unanswered
// dial left no row anywhere, because a CRM interaction is only created once
// media connects. Answer rate, right-party-contact rate and cost per connect
// were guesses, and the reach estimator was being fitted to its own numerator.

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";

import { apiGet, apiPost } from "./config";

// -----------------------------------------------------------------------------
// Wire schemas — field-for-field with backend/schemas.py. A `datetime` is an
// ISO string on the wire. Where a value is `str` server-side but the column
// carries a CHECK constraint (sql/21_outbound.sql, sql/22_campaigns.sql) or the
// card model pins a Literal (agent_core/cards/schema.py), the enum here is that
// list; everything else is z.string(). Routes marked exclude_unset below get
// `.optional()` on every defaulted field.
// -----------------------------------------------------------------------------

const isoDate = z.string();

const isoDateOrNull = z.string().nullable();

/** CallAttemptResponse — GET /outbound/attempts. */
const callAttemptSchema = z.object({
  id: z.string(),
  customer_id: z.string(),
  customer_name: z.string(),
  objective: z.string(),
  attempt_no: z.number(),
  state: z.string(),
  suppressed_reason: z.string().nullable(),
  to_phone_last4: z.string().nullable(),
  answered_by: z.string().nullable(),
  right_party: z.boolean().nullable(),
  ring_sec: z.number().nullable(),
  talk_sec: z.number().nullable(),
  provider_call_id: z.string().nullable(),
  provider_status: z.string().nullable(),
  provider_error: z.string().nullable(),
  interaction_id: z.string().nullable(),
  decision_id: z.string().nullable(),
  reserved_at: isoDate,
  placed_at: isoDateOrNull,
  answered_at: isoDateOrNull,
  ended_at: isoDateOrNull,
  connection: z.string().nullable(),
  business: z.string().nullable(),
  objective_met: z.boolean().nullable(),
  nonpayment_reason: z.string().nullable(),
  summary: z.string().nullable(),
  summary_source: z.string().nullable(),
});

/** TwilioOutboundCallResponse — three branches share one model, exclude_unset. */
const placedCallSchema = z.object({
  placed: z.boolean().nullable().optional(),
  attemptId: z.string().nullable().optional(),
  state: z.string().nullable().optional(),
  idempotent: z.boolean().nullable().optional(),
  to: z.string().nullable().optional(),
  callSid: z.string().nullable().optional(),
  status: z.string().nullable().optional(),
  from: z.string().nullable().optional(),
});

export type CallAttempt = {
  id: string;
  customer_id: string;
  customer_name: string | null;
  objective: string;
  attempt_no: number;
  state: string;
  suppressed_reason: string | null;
  to_phone_last4: string | null;
  answered_by: string | null;
  right_party: boolean | null;
  ring_sec: number | null;
  talk_sec: number | null;
  provider_call_id: string | null;
  provider_status: string | null;
  provider_error: string | null;
  interaction_id: string | null;
  decision_id: string | null;
  reserved_at: string;
  placed_at: string | null;
  answered_at: string | null;
  ended_at: string | null;
  connection: string | null;
  business: string | null;
  objective_met: boolean | null;
  nonpayment_reason: string | null;
  summary: string | null;
  summary_source: string | null;
};

export async function fetchAttempts(params: { customerId?: string; limit?: number } = {}) {
  const q = new URLSearchParams();
  if (params.customerId) q.set("customerId", params.customerId);
  q.set("limit", String(params.limit ?? 50));
  return apiGet<CallAttempt[]>(`/outbound/attempts?${q.toString()}`, {
    schema: z.array(callAttemptSchema),
  });
}

/** An attempt in one of these can still change state on its own. */
const IN_FLIGHT_ATTEMPT = new Set(["reserved", "dialing", "ringing", "answered", "live"]);

export function useOutboundAttempts(customerId?: string) {
  return useQuery({
    queryKey: ["outbound", "attempts", customerId ?? "all"],
    queryFn: () => fetchAttempts({ customerId }),
    // A dial moves through ringing to an outcome in seconds; poll only while one is.
    refetchInterval: (q) =>
      q.state.data?.some((a) => IN_FLIGHT_ATTEMPT.has(a.state)) ? 5_000 : false,
  });
}

/** What the dial owner reports back for one operator-placed call. */
export type PlacedCall = z.infer<typeof placedCallSchema>;

/**
 * Place one call to a customer through the dial owner -- reserve, admit,
 * suppress-or-place, every gate. A refusal (statutory window, DND, caps)
 * comes back as a 409 with its reason; the caller shows it, because the
 * refusal is the product working. The key makes a retried click one attempt.
 */
export function usePlaceCall() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "caller" },
    mutationFn: ({
      customerId,
      accountId,
      phone,
      idempotencyKey,
    }: {
      customerId: string;
      /** The account on screen: the briefing, the attempt and the call's tools all use it. */
      accountId?: string;
      phone: string;
      idempotencyKey: string;
    }) =>
      apiPost<PlacedCall>(
        "/twilio/voice/outbound",
        { customerId, accountId, to: phone, objective: "manual_outbound" },
        { headers: { "Idempotency-Key": idempotencyKey }, schema: placedCallSchema },
      ),
    // A refusal leaves a suppressed attempt too, so both outcomes refresh the log.
    onSettled: () => qc.invalidateQueries({ queryKey: ["outbound", "attempts"] }),
  });
}

/** Human label for an attempt state. The raw values are for queries, not people. */
export const ATTEMPT_STATE_LABEL: Record<string, string> = {
  reserved: "reserved",
  suppressed: "blocked by policy",
  dialing: "dialling",
  ringing: "ringing",
  answered: "answered",
  live: "on the call",
  completed: "completed",
  voicemail_left: "voicemail left",
  voicemail_skipped: "voicemail skipped",
  no_answer: "no answer",
  busy: "busy",
  rejected: "rejected",
  failed: "carrier error",
  invalid_number: "bad number",
  canceled: "cancelled",
  transferred: "transferred",
  abandoned: "abandoned",
};
