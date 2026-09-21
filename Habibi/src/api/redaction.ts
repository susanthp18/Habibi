// -----------------------------------------------------------------------------
// Redaction & Export Hub — data access seam.
//   Reads: GET /redaction-records + /redaction-rules + /export-jobs
//   Writes: finding accept, audio mute, mark reviewed, rule toggle, export jobs
// -----------------------------------------------------------------------------

import { useQuery } from "@tanstack/react-query";

import type {
  ExportFormat,
  ExportJob,
  ExportScope,
  PiiEntityType,
  RedactionRecord,
  RedactionRules,
} from "@/api/types/redaction";
import { apiGet, apiGetBlob, apiPatch, apiPost } from "./config";

interface RedactionRuleApi {
  piiType: PiiEntityType;
  enabled: boolean;
  replacement: string;
  label: string;
}

export async function fetchRedactionRecords(): Promise<RedactionRecord[]> {
  return apiGet<RedactionRecord[]>("/redaction-records");
}

export function useRedactionRecords() {
  return useQuery({
    queryKey: ["redaction-records"],
    queryFn: fetchRedactionRecords,
  });
}

export async function fetchRedactionRules(): Promise<RedactionRules> {
  // GET /redaction-rules returns every PII type the vocabulary knows, labelled.
  const rows = await apiGet<RedactionRuleApi[]>("/redaction-rules");
  return Object.fromEntries(
    rows.map((row) => [
      row.piiType,
      { enabled: row.enabled, replacement: row.replacement, label: row.label },
    ]),
  ) as RedactionRules;
}

export function useRedactionRules() {
  return useQuery({
    queryKey: ["redaction-rules"],
    queryFn: fetchRedactionRules,
    staleTime: 5 * 60_000,
  });
}

export async function fetchExportJobs(): Promise<ExportJob[]> {
  return apiGet<ExportJob[]>("/export-jobs");
}

export function useExportJobs() {
  return useQuery({
    queryKey: ["export-jobs"],
    queryFn: fetchExportJobs,
  });
}

export async function toggleFindingAccepted(findingId: string, accepted: boolean): Promise<void> {
  await apiPatch(`/pii-findings/${findingId}`, { accepted });
}

export async function toggleAudioMuted(
  redactionId: string,
  findingId: string,
  muted: boolean,
): Promise<void> {
  await apiPatch(`/redaction-records/${redactionId}/audio-mute`, { findingId, muted });
}

export async function markRedactionReviewed(redactionId: string): Promise<void> {
  await apiPatch(`/redaction-records/${redactionId}`, { reviewed: true });
}

export async function patchRedactionRuleEnabled(
  piiType: PiiEntityType,
  enabled: boolean,
): Promise<void> {
  await apiPatch(`/redaction-rules/${piiType}`, { enabled });
}

export async function createExportJob(input: {
  recordIds: string[];
  format: ExportFormat;
  scope: ExportScope[];
  watermark: string;
  actorRole: string;
}): Promise<ExportJob> {
  return apiPost<ExportJob>("/export-jobs", input);
}

export async function downloadExportJob(jobId: string): Promise<void> {
  const { blob, headers } = await apiGetBlob(`/export-jobs/${encodeURIComponent(jobId)}/download`);
  const name =
    headers.get("Content-Disposition")?.match(/filename="([^"]+)"/)?.[1] || `${jobId}.zip`;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

export async function retryExportJob(jobId: string): Promise<ExportJob> {
  return apiPatch<ExportJob>(`/export-jobs/${jobId}`, { status: "ready" });
}
