import type {
  KbDocType,
  KbStatus,
  KbChunk,
  KbDocument,
  FaqPair,
  RetrievalResult,
} from "@/api/types/kb";

export const DOC_TYPE_LABEL: Record<KbDocType, string> = {
  policy: "Policy",
  sop: "SOP",
  product: "Product",
  compliance: "Compliance",
  faq: "FAQ",
  benefits: "Benefits",
};

export const STATUS_LABEL: Record<KbStatus, string> = {
  indexed: "Indexed",
  indexing: "Indexing",
  stale: "Stale",
  failed: "Failed",
  draft: "Draft",
};
