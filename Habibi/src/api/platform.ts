// -----------------------------------------------------------------------------
// Platform switches + the demo dialer.
//
// The master outbound switch decides whether this deployment may telephone real
// people. It is off by default and it is read by four separate processes, so
// the screen must never guess at its state: no optimistic toggle, no cached
// "probably still on". Every mutation refetches, and a failed read is an error,
// never a confident "off".
// -----------------------------------------------------------------------------

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiPatch, apiPost, mockDelay, retryUnlessClientError, USE_MOCK } from "./config";

export type PlatformSwitch = {
  key: string;
  description: string;
  enabled: boolean;
  updatedAt: string | null;
  updatedByUserId: string | null;
  note: string | null;
};

export type DemoOutboundTarget = {
  phone: string;
  customer: { id: string; name: string; phone: string; dnd: boolean } | null;
  /** The card objective the call runs under — decides the brief and the budget. */
  objective: string;
  /**
   * Whether that objective permits an offer. False on every objective this
   * card declares, which makes the agent's brief say, in as many words, not to
   * mention any product. Surfaced so nobody promises a customer an upsell
   * demo that the card forbids.
   */
  offersAllowed: boolean;
  outboundEnabled: boolean;
  /** Whether the demo may dial outside permitted hours. Off by default. */
  demoIgnoresWindow: boolean;
  /**
   * What contact policy says right now, from the dry-run evaluator — so the
   * screen can warn before the click rather than after. `null` means allowed.
   */
  policyReason: string | null;
  /**
   * The refusal the demo waiver is overriding right now, if any. Distinct from
   * `policyReason` being null: one means nothing objected, the other means
   * something did and we are proceeding anyway. A screen that showed them the
   * same way would hide the override at the moment it is being used.
   */
  policyWaived: string | null;
  twilioConfigured: boolean;
};

export type DemoOutboundResult = {
  placed: boolean;
  customerId: string;
  phone: string;
  attemptId: string | null;
  callSid: string | null;
};

/** The master gate on every outbound dial. */
export const OUTBOUND_ENABLED = "outbound.enabled";

/** Lets the demo button dial outside permitted hours. Demo number only. */
export const DEMO_IGNORES_WINDOW = "outbound.demo_ignores_window";

export function usePlatformSwitches() {
  return useQuery({
    queryKey: ["platform-switches"],
    queryFn: async () =>
      USE_MOCK
        ? mockDelay({
            switches: [
              {
                key: OUTBOUND_ENABLED,
                description: "Master switch for outbound calling.",
                enabled: false,
                updatedAt: null,
                updatedByUserId: null,
                note: null,
              },
            ] as PlatformSwitch[],
          })
        : apiGet<{ switches: PlatformSwitch[] }>("/platform/switches"),
    // A switch whose state we could not read must not be rendered as "off" —
    // the screen shows the error instead. Retrying a 403 would not help.
    retry: retryUnlessClientError,
    staleTime: 5_000,
  });
}

export function usePatchPlatformSwitch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: { key: string; enabled: boolean; note?: string }) =>
      apiPatch<{ key: string; enabled: boolean }>(`/platform/switches/${body.key}`, {
        enabled: body.enabled,
        note: body.note,
      }),
    // Refetch rather than patch the cache. The server is the only authority on
    // whether dialling is permitted, and a toggle that showed "on" because the
    // click succeeded locally would be the worst possible lie on this screen.
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ["platform-switches"] });
      void qc.invalidateQueries({ queryKey: ["demo-outbound"] });
    },
  });
}

export function useDemoOutboundTarget() {
  return useQuery({
    queryKey: ["demo-outbound"],
    queryFn: async () =>
      USE_MOCK
        ? mockDelay({
            phone: "919655282324",
            customer: { id: "cust-susanth", name: "Susanth", phone: "919655282324", dnd: false },
            objective: "dpd_reminder",
            offersAllowed: false,
            outboundEnabled: false,
            demoIgnoresWindow: false,
            policyReason: null,
            policyWaived: null,
            twilioConfigured: true,
          } as DemoOutboundTarget)
        : apiGet<DemoOutboundTarget>("/demo/outbound-call"),
    retry: retryUnlessClientError,
    staleTime: 5_000,
  });
}

export function useDemoOutboundCall() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => apiPost<DemoOutboundResult>("/demo/outbound-call", {}),
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ["demo-outbound"] });
    },
  });
}

/**
 * Turn a backend refusal into something an operator can act on.
 *
 * `outside_allowed_window` is the one that matters most: it is not a fault, it
 * is the statutory calling window working, and copy that reads like an error
 * teaches the operator to distrust a control that is behaving correctly.
 */
export function friendlyOutboundError(raw: string): string {
  if (raw.includes("outbound_disabled")) {
    return "Outbound calling is off. Turn it on above, then try again.";
  }
  // Two different refusals that read alike and are not the same thing. The
  // statutory hours are the regulator's; the allowed window is this borrower's
  // own stated preference, which may only ever narrow the statutory one. An
  // operator who conflates them will go looking in the wrong place.
  if (raw.includes("outside_calling_hours")) {
    return "Blocked by the statutory calling hours. Outbound voice is only permitted inside the regulated window — try again during business hours. This is the compliance gate working, not a fault.";
  }
  if (raw.includes("outside_allowed_window")) {
    return "Blocked by this borrower's contact window — they have a narrower preferred window than the statutory one. Try again inside their stated hours. This is the compliance gate working, not a fault.";
  }
  if (raw.includes("dnd") || raw.includes("opt_out") || raw.includes("consent")) {
    return `Blocked by contact policy: ${raw}. The customer's consent or DND state forbids this call.`;
  }
  if (raw.includes("daily") || raw.includes("cap") || raw.includes("cooling")) {
    return `Blocked by contact policy: ${raw}. The attempt budget for this borrower is spent.`;
  }
  if (raw.includes("fleet_busy")) {
    return "All concurrent call slots are in use. Try again in a moment.";
  }
  if (raw.includes("twilio_not_configured")) {
    return "Twilio is not configured on the server.";
  }
  if (raw.includes("demo_customer_not_found")) {
    return "No customer on file with the demo phone number.";
  }
  return raw;
}
