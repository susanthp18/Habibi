// -----------------------------------------------------------------------------
// Consent & Communication Preferences — data access seam.
//   fetchConsent() → registry list  (GET /consent)
//   save / renew / opt-out / toggle DND → Phase 3A writes (widened for screen)
//
// Writes map to PATCH/POST endpoints; the screen shape is richer than the write
// response, so callers invalidate + refetch.
// -----------------------------------------------------------------------------

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";

import type {
  AllowedWindow,
  ChannelConsent,
  ConsentChannel,
  ConsentPreferencesPatch,
  ConsentRecord,
  OptOutSource,
} from "@/api/types/consent";
import { allowedWindowsEqual } from "@/lib/consent";
import type { QueryClient } from "@tanstack/react-query";
import { apiGet, apiPatch, apiPost } from "./config";
import { customerSchema } from "./customers";
import { toast } from "sonner";

// -----------------------------------------------------------------------------
// Wire schema — field-for-field with ConsentListResponse (extra="forbid").
// No exclude_unset on GET /consent, so `| None = None` is `.nullable()`. The
// writes answer with CustomerResponse; customerSchema covers those.
// -----------------------------------------------------------------------------

const consentChannelSchema = z.enum(["call", "whatsapp", "sms", "email"]);
const optOutSourceSchema = z.enum([
  "IVR",
  "Agent",
  "Web",
  "Regulator",
  "Bulk Import",
  "WhatsApp Reply",
]);

const consentRecordSchema = z.object({
  id: z.string(),
  customerId: z.string(),
  customerName: z.string(),
  accountId: z.string(),
  phone: z.string(),
  email: z.string(),
  timezone: z.string(),
  segment: z.enum(["Retail", "SME", "Priority"]),
  channels: z.array(
    z.object({
      channel: consentChannelSchema,
      status: z.enum(["opted_in", "opted_out", "dnd", "expired"]),
      capturedAt: z.string(),
      source: z.enum([...optOutSourceSchema.options, "Onboarding"]),
      frequencyCapPerWeek: z.number(),
      usedThisWeek: z.number(),
    }),
  ),
  allowedWindow: z.object({
    days: z.array(z.number()),
    startHour: z.number(),
    endHour: z.number(),
  }),
  consentExpiresAt: z.string(),
  onDndRegistry: z.boolean(),
  optOutLog: z.array(
    z.object({
      id: z.string(),
      at: z.string(),
      channel: z.enum([...consentChannelSchema.options, "all"]),
      source: optOutSourceSchema,
      actor: z.string(),
      note: z.string(),
    }),
  ),
  audit: z.array(
    z.object({ id: z.string(), at: z.string(), actor: z.string(), action: z.string() }),
  ),
  outreachToday: z.number(),
  dailyCap: z.number(),
  lastDecisionReason: z.string().nullable(),
  contactable: z.object({
    status: z.enum(["green", "amber", "red"]),
    reasons: z.array(z.string()),
  }),
});

export async function fetchConsent(): Promise<ConsentRecord[]> {
  return apiGet<ConsentRecord[]>("/consent", { schema: z.array(consentRecordSchema) });
}

export function useConsent() {
  return useQuery({ queryKey: ["consent"], queryFn: fetchConsent });
}

export function consentPatchBody(
  rec: ConsentRecord,
  patch: ConsentPreferencesPatch,
  note: string,
): { channels: ChannelConsent[]; note: string; allowedWindow?: AllowedWindow } {
  const body: { channels: ChannelConsent[]; note: string; allowedWindow?: AllowedWindow } = {
    channels: patch.channels,
    note: note || "Consent preferences updated.",
  };
  if (
    patch.allowedWindow !== undefined &&
    !allowedWindowsEqual(patch.allowedWindow, rec.allowedWindow)
  ) {
    body.allowedWindow = patch.allowedWindow;
  }
  return body;
}

export async function saveConsent(
  rec: ConsentRecord,
  patch: ConsentPreferencesPatch,
  note: string,
): Promise<void> {
  await apiPatch(`/consent/${rec.customerId}`, consentPatchBody(rec, patch, note), {
    schema: customerSchema,
  });
}

export async function renewConsent(rec: ConsentRecord): Promise<void> {
  const newExp = new Date();
  newExp.setFullYear(newExp.getFullYear() + 1);
  await apiPatch(
    `/consent/${rec.customerId}`,
    {
      consentExpiresAt: newExp.toISOString(),
      channels: rec.channels.map((c) =>
        c.status === "expired" ? { ...c, status: "opted_in" as const } : c,
      ),
      note: "Consent renewed for 12 months.",
    },
    { schema: customerSchema },
  );
}

export async function captureOptOut(
  rec: ConsentRecord,
  evt: { channel: ConsentChannel | "all"; source: OptOutSource; note: string },
): Promise<void> {
  await apiPost(
    `/consent/${rec.customerId}/opt-out`,
    { channel: evt.channel, source: evt.source, note: evt.note },
    { schema: customerSchema },
  );
}

export async function toggleDnd(rec: ConsentRecord, on: boolean): Promise<void> {
  const channels = on
    ? rec.channels.map((c) => (c.channel === "call" ? { ...c, status: "dnd" as const } : c))
    : rec.channels.map((c) =>
        c.channel === "call" && c.status === "dnd" ? { ...c, status: "opted_in" as const } : c,
      );
  await apiPatch(
    `/consent/${rec.customerId}`,
    {
      onDndRegistry: on,
      dnd: on,
      channels,
      note: on ? "Added to DND registry (calls blocked)." : "Removed from DND registry.",
    },
    { schema: customerSchema },
  );
}

// ---------- mutations ----------

/** A consent change moves what the 360, the contact policy and the threads may say. */
function invalidateConsentReads(qc: QueryClient) {
  for (const key of ["consent", "customer", "customers", "contact-policy", "conversations"]) {
    void qc.invalidateQueries({ queryKey: [key] });
  }
}

export function useSaveConsent() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "toast" },
    mutationFn: (v: { rec: ConsentRecord; patch: ConsentPreferencesPatch; note: string }) =>
      saveConsent(v.rec, v.patch, v.note),
    onSuccess: () => {
      invalidateConsentReads(qc);
      toast.success("Consent preferences saved", {
        description: "Change captured in the audit trail.",
      });
    },
  });
}

export function useRenewConsent() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "toast" },
    mutationFn: (rec: ConsentRecord) => renewConsent(rec),
    onSuccess: () => {
      invalidateConsentReads(qc);
      toast.success("Consent renewed", { description: "New expiry set 12 months out." });
    },
  });
}

export function useCaptureOptOut() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "toast" },
    mutationFn: (v: {
      rec: ConsentRecord;
      evt: { channel: ConsentChannel | "all"; source: OptOutSource; note: string };
    }) => captureOptOut(v.rec, v.evt),
    onSuccess: () => {
      invalidateConsentReads(qc);
      toast.success("Opt-out logged", {
        description: "Bot will honor this immediately on next contact attempt.",
      });
    },
  });
}

export function useToggleDnd() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "toast" },
    mutationFn: (v: { rec: ConsentRecord; on: boolean }) => toggleDnd(v.rec, v.on),
    onSuccess: (_r, v) => {
      invalidateConsentReads(qc);
      toast.success(v.on ? "Marked on DND registry" : "Removed from DND registry");
    },
  });
}
