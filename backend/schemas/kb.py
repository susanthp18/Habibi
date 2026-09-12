"""Knowledge base: documents, FAQs, retrieval, snapshots.

One module of the ``schemas`` package (was one 6,400-line file); the
router of the same name serves these. ``schemas/__init__`` re-exports every name.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# The authored flow graph is a domain model, not a transport shape — it is
# shared verbatim by the API, the validator and the voice runtime, so it is
# defined once in flow_graph and reused here rather than restated.
from flow_graph import FlowGraph, FlowIssue, FlowValidation  # noqa: F401

# ---------------------------------------------------------------------------
# Knowledge Base / RAG (Phase KB-1 — retrieve spine)
# ---------------------------------------------------------------------------


class KbRetrievalResultItem(BaseModel):
    """Mirrors Habibi RetrievalResult in kb-seed.ts."""

    model_config = ConfigDict(extra="forbid")

    chunkId: str
    docId: str
    docTitle: str
    docType: str | None = None
    heading: str
    snippet: str
    score: float
    matchedTerms: list[str]


class KbRetrieveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str
    topK: int = Field(default=4, ge=1, le=20)
    includeDraftAnswer: bool = True
    source: str = "test"


class KbRetrieveResponse(BaseModel):
    """The full shape of ``kb_retrieve.retrieve()``, not a subset of it.

    ``extra="forbid"`` is right and stays. What was wrong is that retrieval grew
    four fields — the top1-top2 margin, the per-stage timing split, whether the
    reranker ran, and whether the row came from the result cache — and this model
    was never told. Every one of them is present on both the fresh and the cached
    path, so ``POST /kb/retrieve`` returned a hard 500 on every call, and the
    Test Retrieval screen an operator would use to diagnose a bad answer was the
    one surface that could not produce one.

    A response model that describes less than the handler returns is not a
    stricter contract, it is a broken endpoint. Keep these in step.
    """

    model_config = ConfigDict(extra="forbid")

    results: list[KbRetrievalResultItem]
    draftAnswer: str | None = None
    latencyMs: int
    embeddingModel: str
    chatModel: str | None = None
    logId: str
    #: Top1-top2 score gap. The reported confidence signal (the absolute top
    #: score predicts retrieval success at AUC 0.548 — a coin flip), and what
    #: the KB-gap screen thresholds on.
    margin: float = 0.0
    #: Per-stage milliseconds: rate_ms, embed_ms, ann_ms, rerank_ms, draft_ms.
    stageMs: dict[str, float] = Field(default_factory=dict)
    reranked: bool = False
    cached: bool = False


KbDocType = Literal["policy", "sop", "product", "compliance", "faq", "benefits"]


KbDocStatus = Literal["draft", "indexing", "indexed", "stale", "failed"]


class KbDocumentResponse(BaseModel):
    """Mirrors Habibi KbDocument in kb-seed.ts."""

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    filename: str
    type: KbDocType
    version: str
    status: KbDocStatus
    enabled: bool
    chunks: int
    chunkSize: int
    overlap: int
    embeddingModel: str
    updatedBy: str
    lastIndexed: str
    tags: list[str]


class KbChunkResponse(BaseModel):
    """Mirrors Habibi KbChunk."""

    model_config = ConfigDict(extra="forbid")

    id: str
    docId: str
    index: int
    heading: str
    tokens: int
    text: str
    hits: int


class KbStatsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    docs: int
    activeDocs: int
    faqs: int
    chunks: int
    gaps: int
    lastIndexed: str
    avgScore: float


class KbDocumentPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    title: str | None = None
    tags: list[str] | None = None
    chunkSize: int | None = Field(default=None, ge=64, le=4096)
    overlap: int | None = Field(default=None, ge=0, le=1024)


class KbReindexResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    jobId: str
    documentId: str
    status: str = "queued"


class KbIndexJobResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    documentId: str
    status: str
    chunkSize: int | None = None
    chunkOverlap: int | None = None
    embeddingModel: str | None = None
    startedAt: str | None = None
    completedAt: str | None = None
    error: str | None = None
    createdAt: str
    updatedAt: str


class KbUploadResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document: KbDocumentResponse
    jobId: str | None = None


class KbFaqResponse(BaseModel):
    """Mirrors Habibi FaqPair in kb-seed.ts."""

    model_config = ConfigDict(extra="forbid")

    id: str
    question: str
    answer: str
    intent: str
    enabled: bool
    updatedAt: str
    linkedDocId: str | None = None


class KbFaqCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str
    answer: str
    intent: str = "other"
    enabled: bool = True
    linkedDocId: str | None = None
    gapId: str | None = None  # optional: link analytics gap on create


class KbFaqPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str | None = None
    answer: str | None = None
    intent: str | None = None
    enabled: bool | None = None
    linkedDocId: str | None = None


KbGapSuggestedFix = Literal["kb", "prompt", "both"]


class KbGapResponse(BaseModel):
    """Coverage gap row — mirrors Habibi UnansweredQuestion (+ link state)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    text: str
    hits: int
    lastSeen: str
    topIntent: str
    hasKbDoc: bool
    hasFaq: bool
    resolved: bool
    suggestedFix: KbGapSuggestedFix
    linkedDocumentId: str | None = None
    linkedFaqId: str | None = None
    linkedPromptVersionId: str | None = None


class KbGapLinkRequest(BaseModel):
    """Exactly one of faqPairId | kbDocumentId | promptVersionId."""

    model_config = ConfigDict(extra="forbid")

    faqPairId: str | None = None
    kbDocumentId: str | None = None
    promptVersionId: str | None = None


class KbSnapshotCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str | None = None


class KbSnapshotResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    documentIds: list[str] = []
    faqIds: list[str] = []
    documentCount: int = 0
    faqCount: int = 0
    createdAt: str | None = None


KbPurgeScope = Literal["all", "uploads", "corpus"]


class KbPurgeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: KbPurgeScope = "uploads"
    confirm: bool = False


class KbPurgeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: KbPurgeScope
    documentsDeleted: int
    faqsDeleted: int
    minioObjectsRemoved: int = 0
    documentIds: list[str] = []


class KbDeleteDocumentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deleted: bool
    documentId: str
    faqsDeleted: int = 0
    minioObjectsRemoved: int = 0


class KbIngestSourceDbResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    products: list[str]
    jobsDrained: int
    faqsUpserted: int
    docs: int
    chunks: int
    faqs: int


# ── KB ───────────────────────────────────────────────────────────────────────


class KbReindexAllResponse(BaseModel):
    """`reindex_all_kb_documents` plus the snapshot hook; `snapshot` is None
    when the snapshot could not be taken (the reindex itself succeeded)."""

    jobIds: list[str]
    count: int
    snapshot: KbSnapshotResponse | None = None
