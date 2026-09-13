// Knowledge Base (RAG) — data access seam.
// KB-1: retrieve. KB-2: documents library + stats + upload/reindex.

import { useQuery } from "@tanstack/react-query";

import type { FaqPair, KbChunk, KbDocType, KbDocument, RetrievalResult } from "@/api/types/kb";
import { apiDelete, apiGet, apiPatch, apiPost, apiUpload } from "./config";

export type { FaqPair, KbChunk, KbDocument, RetrievalResult };

export interface KbGap {
  id: string;
  text: string;
  hits: number;
  lastSeen: string;
  topIntent: string;
  hasKbDoc: boolean;
  hasFaq: boolean;
  resolved: boolean;
  suggestedFix: "kb" | "prompt" | "both";
  linkedDocumentId?: string | null;
  linkedFaqId?: string | null;
  linkedPromptVersionId?: string | null;
}

export interface KbRetrieveRequest {
  query: string;
  topK?: number;
  includeDraftAnswer?: boolean;
  source?: string;
}

export interface KbRetrieveResponse {
  results: RetrievalResult[];
  draftAnswer: string | null;
  latencyMs: number;
  embeddingModel: string;
  chatModel: string | null;
  logId: string;
}

export interface KbStats {
  docs: number;
  activeDocs: number;
  faqs: number;
  chunks: number;
  gaps: number;
  lastIndexed: string;
  avgScore: number;
}

export interface KbUploadResult {
  document: KbDocument;
  jobId: string | null;
}

export interface KbReindexResult {
  jobId: string;
  documentId: string;
  status: string;
}

export interface KbIndexJob {
  id: string;
  documentId: string;
  status: string;
  chunkSize: number | null;
  chunkOverlap: number | null;
  embeddingModel: string | null;
  startedAt: string | null;
  completedAt: string | null;
  error: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface KbUploadInput {
  file: File;
  title?: string;
  type: KbDocType;
  chunkSize: number;
  overlap: number;
  indexNow: boolean;
  tags?: string[];
}

export async function retrieveKb(input: KbRetrieveRequest): Promise<KbRetrieveResponse> {
  const topK = input.topK ?? 4;
  const includeDraftAnswer = input.includeDraftAnswer ?? true;

  return apiPost<KbRetrieveResponse>("/kb/retrieve", {
    query: input.query,
    topK,
    includeDraftAnswer,
    source: input.source ?? "test",
  });
}

export async function fetchKbStats(): Promise<KbStats> {
  return apiGet<KbStats>("/kb/stats");
}

export function useKbStats() {
  return useQuery({ queryKey: ["kb", "stats"], queryFn: fetchKbStats });
}

export async function fetchKbDocuments(): Promise<KbDocument[]> {
  return apiGet<KbDocument[]>("/kb/documents");
}

export function useKbDocuments() {
  return useQuery({ queryKey: ["kb", "documents"], queryFn: fetchKbDocuments, staleTime: 10_000 });
}

export async function fetchKbChunks(documentId: string): Promise<KbChunk[]> {
  return apiGet<KbChunk[]>(`/kb/documents/${documentId}/chunks`);
}

export function useKbChunks(documentId: string | null) {
  return useQuery({
    queryKey: ["kb", "chunks", documentId],
    queryFn: () => fetchKbChunks(documentId!),
    enabled: Boolean(documentId),
    staleTime: 10_000,
  });
}

export async function patchKbDocument(
  id: string,
  patch: {
    enabled?: boolean;
    title?: string;
    tags?: string[];
    chunkSize?: number;
    overlap?: number;
  },
): Promise<KbUploadResult> {
  return apiPatch<KbUploadResult>(`/kb/documents/${id}`, patch);
}

export async function reindexKbDocument(id: string): Promise<KbReindexResult> {
  return apiPost<KbReindexResult>(`/kb/documents/${id}/reindex`, {});
}

export interface KbSnapshot {
  id: string;
  label: string;
  documentIds: string[];
  faqIds: string[];
  documentCount: number;
  faqCount: number;
  createdAt: string | null;
}

export async function reindexAllKbDocuments(): Promise<{
  jobIds: string[];
  count: number;
  snapshot?: KbSnapshot | null;
}> {
  return apiPost<{ jobIds: string[]; count: number; snapshot?: KbSnapshot | null }>(
    "/kb/reindex-all",
    {},
  );
}

export type KbPurgeScope = "all" | "uploads" | "corpus";

export interface KbDeleteDocumentResult {
  deleted: boolean;
  documentId: string;
  faqsDeleted: number;
  minioObjectsRemoved: number;
}

export interface KbPurgeResult {
  scope: KbPurgeScope;
  documentsDeleted: number;
  faqsDeleted: number;
  minioObjectsRemoved: number;
  documentIds: string[];
}

export interface KbIngestSourceDbResult {
  products: string[];
  jobsDrained: number;
  faqsUpserted: number;
  docs: number;
  chunks: number;
  faqs: number;
}

export async function deleteKbDocument(id: string): Promise<KbDeleteDocumentResult> {
  return apiDelete<KbDeleteDocumentResult>(`/kb/documents/${id}`);
}

export async function purgeKbDocuments(scope: KbPurgeScope): Promise<KbPurgeResult> {
  return apiPost<KbPurgeResult>("/kb/documents/purge", { scope, confirm: true });
}

export async function ingestSourceDb(product?: string): Promise<KbIngestSourceDbResult> {
  const q = product ? `?product=${encodeURIComponent(product)}` : "";
  return apiPost<KbIngestSourceDbResult>(`/kb/ingest/source-db${q}`, {});
}

export async function uploadKbDocument(input: KbUploadInput): Promise<KbUploadResult> {
  const form = new FormData();
  form.append("file", input.file);
  form.append("title", input.title ?? "");
  form.append("type", input.type);
  form.append("chunkSize", String(input.chunkSize));
  form.append("overlap", String(input.overlap));
  form.append("indexNow", String(input.indexNow));
  form.append("tags", JSON.stringify(input.tags ?? []));
  return apiUpload<KbUploadResult>("/kb/documents", form);
}

export async function uploadKbDocumentVersion(id: string, file: File): Promise<KbUploadResult> {
  const form = new FormData();
  form.append("file", file);
  return apiUpload<KbUploadResult>(`/kb/documents/${id}/versions`, form);
}

export async function fetchKbIndexJob(jobId: string): Promise<KbIndexJob> {
  return apiGet<KbIndexJob>(`/kb/index-jobs/${jobId}`);
}

/** Poll until job leaves queued/running (or timeout). */
export async function pollKbIndexJob(
  jobId: string,
  opts: { intervalMs?: number; timeoutMs?: number } = {},
): Promise<KbIndexJob> {
  const intervalMs = opts.intervalMs ?? 1500;
  const timeoutMs = opts.timeoutMs ?? 120_000;
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    const job = await fetchKbIndexJob(jobId);
    if (job.status === "succeeded" || job.status === "failed") return job;
    await new Promise((r) => setTimeout(r, intervalMs));
  }
  throw new Error(`index job ${jobId} timed out`);
}

/** Poll many index jobs with bounded concurrency; returns settled results (never throws). */
export async function pollKbIndexJobs(
  jobIds: string[],
  opts: { intervalMs?: number; timeoutMs?: number; concurrency?: number } = {},
): Promise<{ succeeded: number; failed: number; timedOut: number; jobs: KbIndexJob[] }> {
  const concurrency = Math.max(1, Math.min(opts.concurrency ?? 4, jobIds.length || 1));
  const jobs: KbIndexJob[] = new Array(jobIds.length);
  let cursor = 0;

  async function worker() {
    while (cursor < jobIds.length) {
      const i = cursor;
      cursor += 1;
      const id = jobIds[i]!;
      try {
        jobs[i] = await pollKbIndexJob(id, opts);
      } catch {
        jobs[i] = {
          id,
          documentId: "",
          status: "failed",
          chunkSize: null,
          chunkOverlap: null,
          embeddingModel: null,
          startedAt: null,
          completedAt: null,
          error: "timed out or unreachable",
          createdAt: new Date().toISOString(),
          updatedAt: new Date().toISOString(),
        } satisfies KbIndexJob;
      }
    }
  }

  await Promise.all(Array.from({ length: Math.min(concurrency, jobIds.length) }, () => worker()));

  let succeeded = 0;
  let failed = 0;
  let timedOut = 0;
  for (const job of jobs) {
    if (job.status === "succeeded") succeeded += 1;
    else if (job.error?.includes("timed out")) timedOut += 1;
    else failed += 1;
  }
  return { succeeded, failed, timedOut, jobs };
}

/**
 * Approximate token windows from real file text (word≈token) for upload preview.
 * Server indexing still uses tiktoken — this is a local estimate only.
 */
export function previewChunksFromText(
  text: string,
  chunkSize: number,
  overlap: number,
  maxChars = 500_000,
): { count: number; samples: string[] } {
  const bounded = (text || "").slice(0, maxChars);
  const tokens = bounded.trim().split(/\s+/).filter(Boolean);
  if (tokens.length === 0) return { count: 0, samples: [] };
  const size = Math.max(1, chunkSize);
  const ov = Math.max(0, Math.min(overlap, size - 1));
  const step = Math.max(1, size - ov);
  const samples: string[] = [];
  let count = 0;
  for (let start = 0; start < tokens.length; start += step) {
    const slice = tokens.slice(start, start + size);
    if (!slice.length) break;
    count += 1;
    if (samples.length < 5) {
      const joined = slice.join(" ");
      samples.push(joined.length > 220 ? `${joined.slice(0, 217)}…` : joined);
    }
    if (start + size >= tokens.length) break;
  }
  return { count: Math.max(1, count), samples };
}

// --- KB-3: FAQs + Gaps ---

export async function fetchKbFaqs(): Promise<FaqPair[]> {
  return apiGet<FaqPair[]>("/kb/faqs");
}

export function useKbFaqs() {
  return useQuery({ queryKey: ["kb", "faqs"], queryFn: fetchKbFaqs, staleTime: 10_000 });
}

export async function createKbFaq(input: {
  question: string;
  answer: string;
  intent: string;
  enabled?: boolean;
  linkedDocId?: string;
  gapId?: string;
}): Promise<FaqPair> {
  return apiPost<FaqPair>("/kb/faqs", input);
}

export async function patchKbFaq(
  id: string,
  patch: {
    question?: string;
    answer?: string;
    intent?: string;
    enabled?: boolean;
    linkedDocId?: string | null;
  },
): Promise<FaqPair> {
  return apiPatch<FaqPair>(`/kb/faqs/${id}`, patch);
}

export async function deleteKbFaq(id: string): Promise<void> {
  await apiDelete(`/kb/faqs/${id}`);
}

export async function fetchKbGaps(): Promise<KbGap[]> {
  return apiGet<KbGap[]>("/kb/gaps");
}

export function useKbGaps() {
  return useQuery({ queryKey: ["kb", "gaps"], queryFn: fetchKbGaps, staleTime: 10_000 });
}

export async function linkKbGap(
  gapId: string,
  link: { faqPairId?: string; kbDocumentId?: string; promptVersionId?: string },
): Promise<KbGap> {
  return apiPost<KbGap>(`/kb/gaps/${gapId}/link`, link);
}

/** Mock promote returns a synthetic id that is not a real skill row. */

export async function promoteGapToSkill(
  gapId: string,
): Promise<{ id: string; slug: string; signatureStatus?: string }> {
  return apiPost(`/kb/gaps/${gapId}/promote-skill`, {});
}

export async function fetchKbSnapshots(): Promise<KbSnapshot[]> {
  return apiGet<KbSnapshot[]>("/kb/snapshots");
}

export function useKbSnapshots() {
  return useQuery({ queryKey: ["kb", "snapshots"], queryFn: fetchKbSnapshots });
}
