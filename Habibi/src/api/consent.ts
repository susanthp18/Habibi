// -----------------------------------------------------------------------------
// Consent & Communication Preferences — data access seam.
//   fetchConsent() → registry list  (GET /consent)
//   save / renew / opt-out / toggle DND → Phase 3A writes (widened for screen)
//
// Mock branch preserves the in-memory seed mutators exactly. Live branch maps
// to PATCH/POST endpoints; the screen shape is richer than the write response,
// so callers invalidate + refetch.
// -----------------------------------------------------------------------------

import { useQuery } from "@tanstack/react-query";

import {
  captureOptOut as captureSeedOptOut,
  consentRecords as seedConsent,
  renewConsent as renewSeedConsent,
  saveConsentPreferences as saveSeedConsent,
  toggleDndRegistry as toggleSeedDnd,
  type AllowedWindow,
  type ChannelConsent,
  type ConsentChannel,
  type ConsentRecord,
  type OptOutSource,
} from "@/data/consent-seed";
import { apiGet, apiPatch, apiPost, mockDelay, USE_MOCK } from "./config";

export async function fetchConsent(): Promise<ConsentRecord[]> {
  if (USE_MOCK) return mockDelay(seedConsent);
  return apiGet<ConsentRecord[]>("/consent");
}

export function useConsent() {
  return useQuery({ queryKey: ["consent"], queryFn: fetchConsent, staleTime: 15_000 });
}

export async function saveConsent(
  rec: ConsentRecord,
  patch: { channels: ChannelConsent[]; allowedWindow: AllowedWindow },
  note: string,
): Promise<void> {
  if (USE_MOCK) {
    saveSeedConsent(rec.id, patch, note);
    return;
  }
  await apiPatch(`/consent/${rec.customerId}`, {
    channels: patch.channels,
    allowedWindow: patch.allowedWindow,
    note: note || "Consent preferences updated.",
  });
}

export async function renewConsent(rec: ConsentRecord): Promise<void> {
  if (USE_MOCK) {
    renewSeedConsent(rec.id);
    return;
  }
  const newExp = new Date();
  newExp.setFullYear(newExp.getFullYear() + 1);
  await apiPatch(`/consent/${rec.customerId}`, {
    consentExpiresAt: newExp.toISOString(),
    channels: rec.channels.map((c) =>
      c.status === "expired" ? { ...c, status: "opted_in" as const } : c,
    ),
    note: "Consent renewed for 12 months.",
  });
}

export async function captureOptOut(
  rec: ConsentRecord,
  evt: { channel: ConsentChannel | "all"; source: OptOutSource; note: string },
): Promise<void> {
  if (USE_MOCK) {
    captureSeedOptOut(rec.id, evt);
    return;
  }
  await apiPost(`/consent/${rec.customerId}/opt-out`, {
    channel: evt.channel,
    source: evt.source,
    note: evt.note,
  });
}

export async function toggleDnd(rec: ConsentRecord, on: boolean): Promise<void> {
  if (USE_MOCK) {
    toggleSeedDnd(rec.id, on);
    return;
  }
  const channels = on
    ? rec.channels.map((c) => (c.channel === "call" ? { ...c, status: "dnd" as const } : c))
    : rec.channels.map((c) =>
        c.channel === "call" && c.status === "dnd" ? { ...c, status: "opted_in" as const } : c,
      );
  await apiPatch(`/consent/${rec.customerId}`, {
    onDndRegistry: on,
    dnd: on,
    channels,
    note: on ? "Added to DND registry (calls blocked)." : "Removed from DND registry.",
  });
}
