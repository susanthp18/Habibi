// -----------------------------------------------------------------------------
// Redaction & Export Hub — data access seam.
//   Reads: GET /redaction-records + /redaction-rules + /export-jobs
//   Writes: finding accept, audio mute, mark reviewed, rule toggle, export jobs
// -----------------------------------------------------------------------------

import { useQuery } from "@tanstack/react-query";

import {
  DEFAULT_RULES,
  ENTITY_TYPES,
  initialExports,
  records as seedRecords,
  type ExportFormat,
  type ExportJob,
  type ExportScope,
  type PiiEntityType,
  type RedactionRecord,
  type RedactionRules,
  type RuleConfig,
} from "@/data/redaction-seed";
import { apiGet, apiPatch, apiPost, mockDelay, USE_MOCK } from "./config";

interface RedactionRuleApi {
  piiType: PiiEntityType;
  enabled: boolean;
  replacement: string;
  label: string;
}

function cloneRules(source: RedactionRules): RedactionRules {
  const next = {} as RedactionRules;
  for (const t of ENTITY_TYPES) {
    next[t] = { ...source[t] };
  }
  return next;
}

let _mockRules: RedactionRules = cloneRules(DEFAULT_RULES);

export async function fetchRedactionRecords(): Promise<RedactionRecord[]> {
  if (USE_MOCK) return mockDelay(seedRecords);
  return apiGet<RedactionRecord[]>("/redaction-records");
}

export function useRedactionRecords() {
  return useQuery({
    queryKey: ["redaction-records"],
    queryFn: fetchRedactionRecords,
    staleTime: 15_000,
  });
}

export async function fetchRedactionRules(): Promise<RedactionRules> {
  if (USE_MOCK) return mockDelay(cloneRules(_mockRules));
  const rows = await apiGet<RedactionRuleApi[]>("/redaction-rules");
  const next = cloneRules(DEFAULT_RULES);
  for (const row of rows) {
    if (!ENTITY_TYPES.includes(row.piiType)) continue;
    next[row.piiType] = {
      enabled: row.enabled,
      replacement: row.replacement,
      label: row.label || DEFAULT_RULES[row.piiType].label,
    } satisfies RuleConfig;
  }
  return next;
}

export function useRedactionRules() {
  return useQuery({
    queryKey: ["redaction-rules"],
    queryFn: fetchRedactionRules,
    staleTime: 5 * 60_000,
  });
}

let _mockExports: ExportJob[] = [...initialExports];

export async function fetchExportJobs(): Promise<ExportJob[]> {
  if (USE_MOCK) return mockDelay(_mockExports);
  return apiGet<ExportJob[]>("/export-jobs");
}

export function useExportJobs() {
  return useQuery({
    queryKey: ["export-jobs"],
    queryFn: fetchExportJobs,
    staleTime: 15_000,
  });
}

export async function toggleFindingAccepted(
  findingId: string,
  accepted: boolean,
): Promise<void> {
  if (USE_MOCK) {
    for (const r of seedRecords) {
      const f = r.findings.find((x) => x.id === findingId);
      if (f) f.accepted = accepted;
    }
    await mockDelay(undefined);
    return;
  }
  await apiPatch(`/pii-findings/${findingId}`, { accepted });
}

export async function toggleAudioMuted(
  redactionId: string,
  findingId: string,
  muted: boolean,
): Promise<void> {
  if (USE_MOCK) {
    const r = seedRecords.find((x) => x.id === redactionId);
    if (r) {
      for (const s of r.audioSegments) {
        if (s.findingId === findingId) s.muted = muted;
      }
    }
    await mockDelay(undefined);
    return;
  }
  await apiPatch(`/redaction-records/${redactionId}/audio-mute`, { findingId, muted });
}

export async function markRedactionReviewed(redactionId: string): Promise<void> {
  if (USE_MOCK) {
    const r = seedRecords.find((x) => x.id === redactionId);
    if (r) r.reviewed = true;
    await mockDelay(undefined);
    return;
  }
  await apiPatch(`/redaction-records/${redactionId}`, { reviewed: true });
}

export async function patchRedactionRuleEnabled(
  piiType: PiiEntityType,
  enabled: boolean,
): Promise<void> {
  if (USE_MOCK) {
    _mockRules[piiType].enabled = enabled;
    await mockDelay(undefined);
    return;
  }
  await apiPatch(`/redaction-rules/${piiType}`, { enabled });
}

export async function createExportJob(input: {
  recordIds: string[];
  format: ExportFormat;
  scope: ExportScope[];
  watermark: string;
  actorRole: string;
}): Promise<ExportJob> {
  if (USE_MOCK) {
    const job: ExportJob = {
      id: `EX-${2050 + _mockExports.length}`,
      at: new Date().toISOString(),
      actor: "You",
      actorRole: input.actorRole,
      recordIds: input.recordIds,
      format: input.format,
      scope: input.scope,
      watermark: input.watermark,
      status: "ready",
      downloadCount: 0,
      entitiesRedacted: 0,
    };
    _mockExports = [job, ..._mockExports];
    return mockDelay(job);
  }
  return apiPost<ExportJob>("/export-jobs", input);
}

export async function bumpExportDownload(jobId: string): Promise<ExportJob> {
  if (USE_MOCK) {
    _mockExports = _mockExports.map((e) =>
      e.id === jobId ? { ...e, downloadCount: e.downloadCount + 1 } : e,
    );
    const row = _mockExports.find((e) => e.id === jobId);
    if (!row) throw new Error("export_job_not_found");
    return mockDelay(row);
  }
  return apiPatch<ExportJob>(`/export-jobs/${jobId}`, { bumpDownload: true });
}

export async function retryExportJob(jobId: string): Promise<ExportJob> {
  if (USE_MOCK) {
    _mockExports = _mockExports.map((e) =>
      e.id === jobId ? { ...e, status: "ready" as const } : e,
    );
    const row = _mockExports.find((e) => e.id === jobId);
    if (!row) throw new Error("export_job_not_found");
    return mockDelay(row);
  }
  return apiPatch<ExportJob>(`/export-jobs/${jobId}`, { status: "ready" });
}
