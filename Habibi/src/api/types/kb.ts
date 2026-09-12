/**
 * Domain / wire types for the kb surface.
 *
 * The wire shape the api/ module for this surface reads and writes.
 */

export type KbDocType = "policy" | "sop" | "product" | "compliance" | "faq" | "benefits";
export type KbStatus = "indexed" | "indexing" | "stale" | "failed" | "draft";
export interface KbChunk {
  id: string;
  docId: string;
  index: number;
  heading: string;
  tokens: number;
  text: string;
  hits: number; // retrieval hits (mock)
}
export interface KbDocument {
  id: string;
  title: string;
  filename: string;
  type: KbDocType;
  version: string;
  status: KbStatus;
  enabled: boolean;
  chunks: number;
  chunkSize: number;
  overlap: number;
  embeddingModel: string;
  updatedBy: string;
  lastIndexed: string; // ISO
  tags: string[];
}
export interface FaqPair {
  id: string;
  question: string;
  answer: string;
  intent: string;
  enabled: boolean;
  updatedAt: string;
  linkedDocId?: string;
}
export interface RetrievalResult {
  chunkId: string;
  docId: string;
  docTitle: string;
  heading: string;
  snippet: string;
  score: number; // 0..1
  matchedTerms: string[];
}
