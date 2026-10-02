// -----------------------------------------------------------------------------
// Platform switches, test numbers and the test call.
//
// The master outbound switch decides whether this deployment may telephone real
// people. It is off by default and it is read by four separate processes, so
// the screen must never guess at its state: no optimistic toggle, no cached
// "probably still on". Every mutation refetches, and a failed read is an error,
// never a confident "off".
// -----------------------------------------------------------------------------

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiDelete, apiGet, apiPatch, apiPost, retryUnlessClientError } from "./config";

export type PlatformSwitch = {
  key: string;
  description: string;
  enabled: boolean;
  updatedAt: string | null;
  updatedByUserId: string | null;
  note: string | null;
};

export type TestNumber = {
  id: string;
  e164: string;
  label: string | null;
  addedBy: string | null;
  createdAt: string | null;
  /** The customer on file for this number; the agent gets their account. */
  customer: { id: string; name: string; phone: string; dnd: boolean } | null;
  /** A contact-policy refusal a test call would hit now (not waivable). */
  blocked: string | null;
  /** A refusal the test call is overriding now (hours only behind the switch). */
  waived: string | null;
};

export type TestCallOptions = {
  outboundEnabled: boolean;
  ignoresWindow: boolean;
  agents: { id: number; name: string }[];
  bindings: { objective: string; engine_workflow_id: number; label: string | null }[];
  objectives: string[];
  numbers: TestNumber[];
  /** Why a call could not go right now: configuration, not policy. */
  problems: string[];
};

export type TestCallResult = {
  placed: boolean;
  attemptId: string | null;
  runId: string | null;
  customerId: string | null;
};

/** The master gate on every outbound dial. */
export const OUTBOUND_ENABLED = "outbound.enabled";

/** Lets a test call ring outside permitted hours. Test numbers only. */
export const DEMO_IGNORES_WINDOW = "outbound.demo_ignores_window";

/** The treatment engine carries out its live decisions (NBA). */
export const TREATMENT_ENACT_ENABLED = "treatment.enact.enabled";

/** Offers decided from conversations are sent to customers. */
export const RECO_ENABLED = "reco.enabled";

export function usePlatformSwitches() {
  return useQuery({
    queryKey: ["platform-switches"],
    queryFn: async () => apiGet<{ switches: PlatformSwitch[] }>("/platform/switches"),
    // A switch whose state we could not read must not be rendered as "off" —
    // the screen shows the error instead. Retrying a 403 would not help.
    retry: retryUnlessClientError,
    staleTime: 5_000,
  });
}

export function usePatchPlatformSwitch() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "caller" },
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
      void qc.invalidateQueries({ queryKey: ["test-call"] });
    },
  });
}

export function useTestCallOptions() {
  return useQuery({
    queryKey: ["test-call"],
    queryFn: async () => apiGet<TestCallOptions>("/voice-studio/test-call"),
    retry: retryUnlessClientError,
    staleTime: 5_000,
  });
}

export function useTestCallPreview(
  body: { workflowId: number; numberId: string; objective: string } | null,
) {
  return useQuery({
    queryKey: ["test-call-preview", body],
    enabled: body !== null,
    queryFn: async () =>
      apiPost<{ context: Record<string, unknown>; customer: TestNumber["customer"] }>(
        "/voice-studio/test-call/preview",
        body,
      ),
    retry: retryUnlessClientError,
  });
}

export function usePlaceTestCall() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "caller" },
    mutationFn: async (body: { workflowId: number; numberId: string; objective: string }) =>
      apiPost<TestCallResult>("/voice-studio/test-call", body),
    onSettled: () => void qc.invalidateQueries({ queryKey: ["test-call"] }),
  });
}

export function useTestNumberMutations() {
  const qc = useQueryClient();
  const refresh = () => void qc.invalidateQueries({ queryKey: ["test-call"] });
  return {
    add: useMutation({
      meta: { errors: "caller" },
      mutationFn: async (body: { e164: string; label?: string }) =>
        apiPost<{ numbers: TestNumber[] }>("/settings/test-numbers", body),
      onSettled: refresh,
    }),
    remove: useMutation({
      meta: { errors: "caller" },
      mutationFn: async (id: string) =>
        apiDelete<{ numbers: TestNumber[] }>(`/settings/test-numbers/${id}`),
      onSettled: refresh,
    }),
  };
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
  if (raw.includes("contact_windows_conflict")) {
    return "Blocked: this borrower's consent hours and preferred window never overlap, so there is no time they may be called. Correct whichever one is wrong on their consent record; waiting will not clear this.";
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
  if (raw.includes("telephony_not_configured")) {
    return "Telephony is not configured on the server.";
  }
  if (raw.includes("test_number_not_found")) {
    return "That test number was removed. Pick another.";
  }
  return raw;
}
