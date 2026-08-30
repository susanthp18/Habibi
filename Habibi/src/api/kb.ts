// Knowledge Base (RAG) — data access seam.
// KB-1: retrieve. KB-2: documents library + stats + upload/reindex.

import { useQuery } from "@tanstack/react-query";

import {
  chunks as seedChunks,
  computeKbStats,
  documents as seedDocs,
  faqs as seedFaqs,
  runMockRetrieval,
  type FaqPair,
  type KbChunk,
  type KbDocType,
  type KbDocument,
  type RetrievalResult,
} from "@/data/kb-seed";
import { unansweredQuestions } from "@/data/bot-analytics-seed";
import { apiDelete, apiGet, apiPatch, apiPost, apiUpload, mockDelay, USE_MOCK } from "./config";

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

  if (USE_MOCK) {
    const { results, latencyMs } = runMockRetrieval(input.query, topK);
    return mockDelay({
      results,
      draftAnswer: includeDraftAnswer
        ? results[0]
          ? `Based on ${results[0].docTitle}: ${results[0].snippet.slice(0, 220)}…`
          : null
        : null,
      latencyMs,
      embeddingModel: "mock-embed",
      chatModel: includeDraftAnswer ? "mock-chat" : null,
      logId: `mock-${Date.now()}`,
    });
  }

  return apiPost<KbRetrieveResponse>("/kb/retrieve", {
    query: input.query,
    topK,
    includeDraftAnswer,
    source: input.source ?? "test",
  });
}

export async function fetchKbStats(): Promise<KbStats> {
  if (USE_MOCK) {
    return mockDelay(computeKbStats(seedDocs, seedFaqs, unansweredQuestions.length));
  }
  return apiGet<KbStats>("/kb/stats");
}

export function useKbStats() {
  return useQuery({ queryKey: ["kb", "stats"], queryFn: fetchKbStats, staleTime: 15_000 });
}

export async function fetchKbDocuments(): Promise<KbDocument[]> {
  if (USE_MOCK) return mockDelay(seedDocs);
  return apiGet<KbDocument[]>("/kb/documents");
}

export function useKbDocuments() {
  return useQuery({ queryKey: ["kb", "documents"], queryFn: fetchKbDocuments, staleTime: 10_000 });
}

export async function fetchKbChunks(documentId: string): Promise<KbChunk[]> {
  if (USE_MOCK) {
    return mockDelay(seedChunks.filter((c) => c.docId === documentId));
  }
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
  if (USE_MOCK) {
    const doc = seedDocs.find((d) => d.id === id);
    if (!doc) throw new Error("kb_document_not_found");
    const next = {
      ...doc,
      ...patch,
      chunkSize: patch.chunkSize ?? doc.chunkSize,
      overlap: patch.overlap ?? doc.overlap,
    };
    const idx = seedDocs.findIndex((d) => d.id === id);
    if (idx >= 0) seedDocs[idx] = next;
    return mockDelay({ document: next, jobId: patch.enabled ? `mock-job-${Date.now()}` : null });
  }
  return apiPatch<KbUploadResult>(`/kb/documents/${id}`, patch);
}

export async function reindexKbDocument(id: string): Promise<KbReindexResult> {
  if (USE_MOCK) {
    return mockDelay({ jobId: `mock-job-${Date.now()}`, documentId: id, status: "queued" }, 400);
  }
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
  if (USE_MOCK) {
    const ids = seedDocs.filter((d) => d.enabled).map((d) => d.id);
    return mockDelay(
      {
        jobIds: ids.map((id) => `mock-${id}`),
        count: ids.length,
        snapshot: {
          id: `mock-snap-${Date.now()}`,
          label: `After reindex-all (${ids.length} jobs)`,
          documentIds: ids,
          faqIds: seedFaqs.filter((f) => f.enabled).map((f) => f.id),
          documentCount: ids.length,
          faqCount: seedFaqs.filter((f) => f.enabled).length,
          createdAt: new Date().toISOString(),
        },
      },
      600,
    );
  }
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
  if (USE_MOCK) {
    const idx = seedDocs.findIndex((d) => d.id === id);
    if (idx < 0) throw new Error("kb_document_not_found");
    seedDocs.splice(idx, 1);
    return mockDelay({
      deleted: true,
      documentId: id,
      faqsDeleted: 0,
      minioObjectsRemoved: 0,
    });
  }
  return apiDelete<KbDeleteDocumentResult>(`/kb/documents/${id}`);
}

export async function purgeKbDocuments(scope: KbPurgeScope): Promise<KbPurgeResult> {
  if (USE_MOCK) {
    let removed: typeof seedDocs = [];
    let faqsDeleted = 0;
    if (scope === "all") {
      removed = [...seedDocs];
      faqsDeleted = seedFaqs.length;
      seedDocs.splice(0, seedDocs.length);
      seedFaqs.splice(0, seedFaqs.length);
    } else if (scope === "uploads") {
      removed = seedDocs.filter((d) => d.id.startsWith("d-") || d.id.startsWith("kb-upload-"));
      for (const d of removed) {
        const i = seedDocs.findIndex((x) => x.id === d.id);
        if (i >= 0) seedDocs.splice(i, 1);
      }
    } else {
      removed = seedDocs.filter((d) => !d.id.startsWith("d-") && !d.id.startsWith("kb-upload-"));
      for (const d of removed) {
        const i = seedDocs.findIndex((x) => x.id === d.id);
        if (i >= 0) seedDocs.splice(i, 1);
      }
    }
    return mockDelay({
      scope,
      documentsDeleted: removed.length,
      faqsDeleted,
      minioObjectsRemoved: 0,
      documentIds: removed.map((d) => d.id),
    });
  }
  return apiPost<KbPurgeResult>("/kb/documents/purge", { scope, confirm: true });
}

export async function ingestSourceDb(product?: string): Promise<KbIngestSourceDbResult> {
  if (USE_MOCK) {
    return mockDelay(
      {
        products: product ? [product] : ["car", "travel", "home"],
        jobsDrained: 6,
        faqsUpserted: 40,
        docs: seedDocs.length,
        chunks: seedChunks.length,
        faqs: seedFaqs.length,
      },
      800,
    );
  }
  const q = product ? `?product=${encodeURIComponent(product)}` : "";
  return apiPost<KbIngestSourceDbResult>(`/kb/ingest/source-db${q}`, {});
}

export async function uploadKbDocument(input: KbUploadInput): Promise<KbUploadResult> {
  if (USE_MOCK) {
    const doc: KbDocument = {
      id: `d-${Date.now()}`,
      title: input.title?.trim() || input.file.name.replace(/\.[^.]+$/, ""),
      filename: input.file.name,
      type: input.type,
      version: "v1.0",
      status: input.indexNow ? "indexing" : "draft",
      enabled: input.indexNow,
      chunks: 0,
      chunkSize: input.chunkSize,
      overlap: input.overlap,
      embeddingModel: "text-embedding-3-small",
      updatedBy: "You",
      lastIndexed: new Date().toISOString(),
      tags: input.tags ?? [],
    };
    seedDocs.unshift(doc);
    return mockDelay({ document: doc, jobId: input.indexNow ? `mock-job-${doc.id}` : null });
  }

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
  if (USE_MOCK) {
    const doc = seedDocs.find((d) => d.id === id);
    if (!doc) throw new Error("kb_document_not_found");
    const next = {
      ...doc,
      filename: file.name,
      version: doc.version.replace(/(\d+)$/, (_, n) => String(Number(n) + 1)),
      status: "indexing" as const,
      lastIndexed: new Date().toISOString(),
    };
    const idx = seedDocs.findIndex((d) => d.id === id);
    if (idx >= 0) seedDocs[idx] = next;
    return mockDelay({ document: next, jobId: `mock-job-${Date.now()}` });
  }
  const form = new FormData();
  form.append("file", file);
  return apiUpload<KbUploadResult>(`/kb/documents/${id}/versions`, form);
}

export async function fetchKbIndexJob(jobId: string): Promise<KbIndexJob> {
  if (USE_MOCK) {
    return mockDelay({
      id: jobId,
      documentId: "mock",
      status: "succeeded",
      chunkSize: 512,
      chunkOverlap: 64,
      embeddingModel: "mock-embed",
      startedAt: new Date().toISOString(),
      completedAt: new Date().toISOString(),
      error: null,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    });
  }
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
  if (USE_MOCK) return mockDelay(seedFaqs);
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
  if (USE_MOCK) {
    const faq: FaqPair = {
      id: `f-${Date.now()}`,
      question: input.question,
      answer: input.answer,
      intent: input.intent,
      enabled: input.enabled ?? true,
      updatedAt: new Date().toISOString(),
      linkedDocId: input.linkedDocId,
    };
    seedFaqs.unshift(faq);
    return mockDelay(faq);
  }
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
  if (USE_MOCK) {
    const idx = seedFaqs.findIndex((f) => f.id === id);
    if (idx < 0) throw new Error("faq_not_found");
    const next = {
      ...seedFaqs[idx],
      ...patch,
      linkedDocId:
        patch.linkedDocId === null ? undefined : (patch.linkedDocId ?? seedFaqs[idx].linkedDocId),
      updatedAt: new Date().toISOString(),
    };
    seedFaqs[idx] = next;
    return mockDelay(next);
  }
  return apiPatch<FaqPair>(`/kb/faqs/${id}`, patch);
}

export async function deleteKbFaq(id: string): Promise<void> {
  if (USE_MOCK) {
    const idx = seedFaqs.findIndex((f) => f.id === id);
    if (idx < 0) throw new Error("faq_not_found");
    seedFaqs.splice(idx, 1);
    return mockDelay(undefined);
  }
  await apiDelete(`/kb/faqs/${id}`);
}

export async function fetchKbGaps(): Promise<KbGap[]> {
  if (USE_MOCK) {
    return mockDelay(
      unansweredQuestions.map((q) => ({
        id: q.id,
        text: q.text,
        hits: q.hits,
        lastSeen: q.lastSeen,
        topIntent: q.topIntent,
        hasKbDoc: q.hasKbDoc,
        hasFaq: false,
        resolved: q.hasKbDoc,
        suggestedFix: q.suggestedFix,
        linkedDocumentId: q.hasKbDoc ? "d1" : null,
        linkedFaqId: null,
      })),
    );
  }
  return apiGet<KbGap[]>("/kb/gaps");
}

export function useKbGaps() {
  return useQuery({ queryKey: ["kb", "gaps"], queryFn: fetchKbGaps, staleTime: 10_000 });
}

export async function linkKbGap(
  gapId: string,
  link: { faqPairId?: string; kbDocumentId?: string; promptVersionId?: string },
): Promise<KbGap> {
  if (USE_MOCK) {
    return mockDelay({
      id: gapId,
      text: unansweredQuestions.find((q) => q.id === gapId)?.text ?? "",
      hits: 0,
      lastSeen: new Date().toISOString(),
      topIntent: "other",
      hasKbDoc: Boolean(link.kbDocumentId),
      hasFaq: Boolean(link.faqPairId),
      resolved: true,
      suggestedFix: link.promptVersionId ? "prompt" : "kb",
      linkedDocumentId: link.kbDocumentId ?? null,
      linkedFaqId: link.faqPairId ?? null,
      linkedPromptVersionId: link.promptVersionId ?? null,
    });
  }
  return apiPost<KbGap>(`/kb/gaps/${gapId}/link`, link);
}

export async function promoteGapToSkill(
  gapId: string,
): Promise<{ id: string; slug: string; signatureStatus?: string }> {
  if (USE_MOCK) {
    return mockDelay({
      id: `skill-gardener-${gapId}`,
      slug: `gardener-${gapId}`,
      signatureStatus: "unsigned",
    });
  }
  return apiPost(`/kb/gaps/${gapId}/promote-skill`, {});
}

export async function fetchKbSnapshots(): Promise<KbSnapshot[]> {
  if (USE_MOCK) {
    return mockDelay([
      {
        id: "mock-snap-1",
        label: "Mock snapshot",
        documentIds: seedDocs.filter((d) => d.enabled).map((d) => d.id),
        faqIds: seedFaqs.filter((f) => f.enabled).map((f) => f.id),
        documentCount: seedDocs.filter((d) => d.enabled).length,
        faqCount: seedFaqs.filter((f) => f.enabled).length,
        createdAt: new Date().toISOString(),
      },
    ]);
  }
  return apiGet<KbSnapshot[]>("/kb/snapshots");
}

export function useKbSnapshots() {
  return useQuery({ queryKey: ["kb", "snapshots"], queryFn: fetchKbSnapshots, staleTime: 15_000 });
}
