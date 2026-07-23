import { useEffect, useMemo, useRef, useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { AppShell } from "@/components/shell/AppShell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { KbStatsStrip } from "@/components/kb/KbStatsStrip";
import { KbSnapshotsStrip } from "@/components/kb/KbSnapshotsStrip";
import { DocumentsTable } from "@/components/kb/DocumentsTable";
import { DocumentInspector } from "@/components/kb/DocumentInspector";
import { ChunkModal } from "@/components/kb/ChunkModal";
import { FaqTable } from "@/components/kb/FaqTable";
import { FaqEditorSheet } from "@/components/kb/FaqEditorSheet";
import { AnalyticsGapsTable } from "@/components/kb/AnalyticsGapsTable";
import { TestRetrievalPanel } from "@/components/kb/TestRetrievalPanel";
import { UploadWizard } from "@/components/kb/UploadWizard";
import {
  createKbFaq,
  deleteKbDocument,
  deleteKbFaq,
  ingestSourceDb,
  linkKbGap,
  patchKbDocument,
  patchKbFaq,
  pollKbIndexJob,
  pollKbIndexJobs,
  purgeKbDocuments,
  reindexAllKbDocuments,
  reindexKbDocument,
  uploadKbDocument,
  uploadKbDocumentVersion,
  useKbChunks,
  useKbDocuments,
  useKbFaqs,
  useKbGaps,
  useKbSnapshots,
  useKbStats,
  type FaqPair,
  type KbChunk,
  type KbGap,
  type KbPurgeScope,
  type KbUploadInput,
} from "@/api/kb";
import type { KbDocumentMetaPatch } from "@/components/kb/DocumentInspector";
import { Database, MoreHorizontal, Plus, RefreshCw, Search, Trash2, Upload, X } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { KbDocType } from "@/data/kb-seed";
import { DOC_TYPE_LABEL } from "@/data/kb-seed";

export const Route = createFileRoute("/knowledge-base")({
  validateSearch: (search: Record<string, unknown>): { gapId?: string; q?: string } => ({
    gapId: typeof search.gapId === "string" ? search.gapId : undefined,
    q: typeof search.q === "string" ? search.q : undefined,
  }),
  head: () => ({
    meta: [
      { title: "Knowledge Base (RAG) Manager — BigBound AI" },
      {
        name: "description",
        content:
          "Upload, chunk and manage the policy PDFs, SOPs and FAQ pairs the collections bot retrieves at runtime. Test retrieval, close coverage gaps and control what the bot can quote.",
      },
      { property: "og:title", content: "Knowledge Base (RAG) Manager" },
      {
        property: "og:description",
        content: "RAG source management with chunk inspector, test-query panel and analytics-driven gap closure.",
      },
    ],
  }),
  component: KnowledgeBasePage,
});

function KnowledgeBasePage() {
  const qc = useQueryClient();
  const { gapId: searchGapId, q: searchQ } = Route.useSearch();
  const { data: docs = [], isLoading: docsLoading } = useKbDocuments();
  const { data: faqs = [], isLoading: faqsLoading } = useKbFaqs();
  const { data: gaps = [], isLoading: gapsLoading } = useKbGaps();
  const { data: stats } = useKbStats();
  const { data: snapshots = [] } = useKbSnapshots();
  const [reindexing, setReindexing] = useState<Set<string>>(new Set());
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null);
  const [openChunk, setOpenChunk] = useState<KbChunk | null>(null);
  const [showUpload, setShowUpload] = useState(false);
  const [editingFaq, setEditingFaq] = useState<FaqPair | null>(null);
  const [faqOpen, setFaqOpen] = useState(false);
  const [pendingGapId, setPendingGapId] = useState<string | null>(null);
  const [uploadGapId, setUploadGapId] = useState<string | null>(null);
  const [tab, setTab] = useState("documents");
  const [search, setSearch] = useState("");
  const [savingMeta, setSavingMeta] = useState(false);
  const [reindexAllBusy, setReindexAllBusy] = useState(false);
  const [syncBusy, setSyncBusy] = useState(false);
  const [purgeBusy, setPurgeBusy] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [syncConfirmOpen, setSyncConfirmOpen] = useState(false);
  const [purgeConfirmOpen, setPurgeConfirmOpen] = useState(false);
  const [purgeScope, setPurgeScope] = useState<KbPurgeScope>("uploads");
  const [purgeTyped, setPurgeTyped] = useState("");
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [typeFilter, setTypeFilter] = useState<"all" | KbDocType>("all");
  const [enabledFilter, setEnabledFilter] = useState<"all" | "enabled" | "disabled">("all");
  const versionInputRef = useRef<HTMLInputElement>(null);
  const deepLinkApplied = useRef(false);
  const userDismissedInspector = useRef(false);

  const { data: selectedChunks = [] } = useKbChunks(selectedDocId);

  // Keep selection valid when docs reload / delete — unless the user closed the inspector.
  useEffect(() => {
    if (docs.length === 0) {
      if (selectedDocId) setSelectedDocId(null);
      return;
    }
    if (selectedDocId && docs.some((d) => d.id === selectedDocId)) return;
    if (userDismissedInspector.current && !selectedDocId) return;
    userDismissedInspector.current = false;
    setSelectedDocId(docs[0].id);
  }, [docs, selectedDocId]);

  useEffect(() => {
    if (deepLinkApplied.current) return;
    if (!searchGapId && !searchQ) return;
    deepLinkApplied.current = true;
    if (searchGapId) {
      setPendingGapId(searchGapId);
      setTab("gaps");
    }
    if (searchQ) setSearch(searchQ);
  }, [searchGapId, searchQ]);

  const filteredDocs = useMemo(() => {
    const q = search.trim().toLowerCase();
    return docs.filter((d) => {
      if (typeFilter !== "all" && d.type !== typeFilter) return false;
      if (enabledFilter === "enabled" && !d.enabled) return false;
      if (enabledFilter === "disabled" && d.enabled) return false;
      if (!q) return true;
      return (
        d.title.toLowerCase().includes(q) ||
        d.filename.toLowerCase().includes(q) ||
        d.tags.some((t) => t.includes(q)) ||
        d.id.toLowerCase().includes(q)
      );
    });
  }, [docs, search, typeFilter, enabledFilter]);

  const selectedHiddenByFilter = Boolean(
    selectedDocId && docs.some((d) => d.id === selectedDocId) && !filteredDocs.some((d) => d.id === selectedDocId),
  );

  const filteredFaqs = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return faqs;
    return faqs.filter(
      (f) => f.question.toLowerCase().includes(q) || f.answer.toLowerCase().includes(q) || f.intent.includes(q),
    );
  }, [faqs, search]);

  const filteredGaps = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return gaps;
    return gaps.filter((g) => {
      if (g.text.toLowerCase().includes(q) || g.topIntent.toLowerCase().includes(q)) return true;
      if (g.linkedDocumentId) {
        const doc = docs.find((d) => d.id === g.linkedDocumentId);
        if (doc?.title.toLowerCase().includes(q) || doc?.filename.toLowerCase().includes(q)) return true;
      }
      if (g.linkedFaqId) {
        const faq = faqs.find((f) => f.id === g.linkedFaqId);
        if (faq?.question.toLowerCase().includes(q)) return true;
      }
      return false;
    });
  }, [gaps, search, docs, faqs]);

  const selectedDoc = docs.find((d) => d.id === selectedDocId) ?? null;
  const openGaps = gaps.filter((g) => !g.resolved).length;
  const globalBusy = reindexAllBusy || syncBusy || purgeBusy;

  const stripStats = stats ?? {
    docs: docs.length,
    activeDocs: docs.filter((d) => d.enabled && d.status === "indexed").length,
    faqs: faqs.filter((f) => f.enabled).length,
    chunks: 0,
    gaps: openGaps,
    lastIndexed: docs[0]?.lastIndexed || new Date().toISOString(),
    avgScore: 0,
  };

  const invalidateKb = async () => {
    await Promise.all([
      qc.invalidateQueries({ queryKey: ["kb", "documents"] }),
      qc.invalidateQueries({ queryKey: ["kb", "stats"] }),
      qc.invalidateQueries({ queryKey: ["kb", "chunks"] }),
      qc.invalidateQueries({ queryKey: ["kb", "faqs"] }),
      qc.invalidateQueries({ queryKey: ["kb", "gaps"] }),
      qc.invalidateQueries({ queryKey: ["kb", "snapshots"] }),
    ]);
  };

  const watchJob = async (jobId: string | null | undefined, docId: string, label: string) => {
    if (!jobId) {
      await invalidateKb();
      return;
    }
    setReindexing((s) => new Set(s).add(docId));
    try {
      const job = await pollKbIndexJob(jobId);
      if (job.status === "succeeded") toast.success(label);
      else toast.error(job.error || `${label} failed`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    } finally {
      setReindexing((s) => {
        const next = new Set(s);
        next.delete(docId);
        return next;
      });
      await invalidateKb();
    }
  };

  const toggleDoc = async (id: string, enabled: boolean) => {
    try {
      const result = await patchKbDocument(id, { enabled });
      toast.success(
        `${enabled ? "Enabled" : "Disabled"} — bot will ${enabled ? "start" : "stop"} using this source.`,
      );
      await invalidateKb();
      if (enabled && result.jobId) {
        void watchJob(result.jobId, id, "Re-indexed after enable");
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  };

  const saveDocMeta = async (id: string, patch: KbDocumentMetaPatch) => {
    const doc = docs.find((d) => d.id === id);
    if (!doc) return;
    const chunkChanged = patch.chunkSize !== doc.chunkSize || patch.overlap !== doc.overlap;
    setSavingMeta(true);
    try {
      await patchKbDocument(id, {
        title: patch.title,
        tags: patch.tags,
        chunkSize: patch.chunkSize,
        overlap: patch.overlap,
      });
      toast.success("Document metadata saved");
      await invalidateKb();
      if (chunkChanged && doc.enabled) {
        const result = await reindexKbDocument(id);
        toast.info("Chunk settings changed — re-index queued…");
        void watchJob(result.jobId, id, "Re-indexed with new chunk settings");
      } else if (chunkChanged) {
        toast.info("Chunk settings saved — enable & re-index to apply to retrieval.");
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
      throw err;
    } finally {
      setSavingMeta(false);
    }
  };

  const reindexDoc = async (id: string) => {
    try {
      const result = await reindexKbDocument(id);
      toast.info("Re-index queued…");
      void watchJob(result.jobId, id, "Re-indexed");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  };

  const removeDoc = async (id: string) => {
    setDeletingId(id);
    try {
      const result = await deleteKbDocument(id);
      toast.success(
        `Deleted document${result.faqsDeleted ? ` (+${result.faqsDeleted} FAQs)` : ""}`,
      );
      userDismissedInspector.current = false;
      if (selectedDocId === id) setSelectedDocId(null);
      await invalidateKb();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
      throw err;
    } finally {
      setDeletingId(null);
      setPendingDeleteId(null);
    }
  };

  const reindexAll = async () => {
    if (globalBusy) return;
    setReindexAllBusy(true);
    try {
      const result = await reindexAllKbDocuments();
      toast.info(`Full re-index queued for ${result.count} enabled document(s)…`);
      const ids = new Set(docs.filter((d) => d.enabled).map((d) => d.id));
      setReindexing(ids);

      const settled = result.jobIds.length
        ? await pollKbIndexJobs(result.jobIds, { timeoutMs: 300_000 })
        : { succeeded: 0, failed: 0, timedOut: 0, jobs: [] };

      setReindexing(new Set());
      await invalidateKb();

      if (result.snapshot) {
        toast.success(
          `Snapshot saved: ${result.snapshot.label} (${result.snapshot.documentCount} docs · ${result.snapshot.faqCount} FAQs)`,
        );
      }

      if (!result.jobIds.length) {
        toast.success("No enabled documents to re-index");
        return;
      }

      if (settled.failed === 0 && settled.timedOut === 0) {
        toast.success(`Full re-index complete — ${settled.succeeded}/${result.jobIds.length} succeeded`);
      } else {
        toast.error(
          `Re-index finished with issues — ${settled.succeeded} ok, ${settled.failed} failed, ${settled.timedOut} timed out`,
        );
      }
    } catch (err) {
      setReindexing(new Set());
      toast.error(err instanceof Error ? err.message : String(err));
    } finally {
      setReindexAllBusy(false);
    }
  };

  const runSyncFromSourceDb = async () => {
    setSyncBusy(true);
    setSyncConfirmOpen(false);
    const toastId = toast.loading("Syncing HDFC corpus from source_db… this may take a few minutes");
    try {
      const result = await ingestSourceDb();
      toast.success(
        `Synced ${result.products.length} products — ${result.docs} docs, ${result.chunks} chunks, ${result.faqs} FAQs`,
        { id: toastId },
      );
      await invalidateKb();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err), { id: toastId });
    } finally {
      setSyncBusy(false);
    }
  };

  const runPurge = async () => {
    if (purgeTyped.trim().toUpperCase() !== "DELETE") return;
    setPurgeBusy(true);
    setPurgeConfirmOpen(false);
    try {
      const result = await purgeKbDocuments(purgeScope);
      toast.success(
        `Purged ${result.documentsDeleted} document(s)` +
          (result.faqsDeleted ? `, ${result.faqsDeleted} FAQ(s)` : ""),
      );
      setSelectedDocId(null);
      setPurgeTyped("");
      userDismissedInspector.current = false;
      await invalidateKb();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    } finally {
      setPurgeBusy(false);
    }
  };

  const addDoc = async (input: KbUploadInput) => {
    try {
      const result = await uploadKbDocument(input);
      userDismissedInspector.current = false;
      setSelectedDocId(result.document.id);
      toast.success(
        input.indexNow
          ? `Upload queued for indexing: "${result.document.title}"`
          : `Saved draft "${result.document.title}"`,
      );
      if (uploadGapId) {
        try {
          await linkKbGap(uploadGapId, { kbDocumentId: result.document.id });
          toast.success("Gap linked to uploaded document");
        } catch (err) {
          toast.error(err instanceof Error ? err.message : String(err));
        } finally {
          setUploadGapId(null);
        }
      }
      await invalidateKb();
      if (result.jobId) {
        void watchJob(result.jobId, result.document.id, `Indexed "${result.document.title}"`);
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
      throw err;
    }
  };

  const onNewVersion = () => {
    versionInputRef.current?.click();
  };

  const onVersionFile = async (file: File | null) => {
    if (!file || !selectedDocId) return;
    try {
      const result = await uploadKbDocumentVersion(selectedDocId, file);
      toast.info(`New version ${result.document.version} queued…`);
      void watchJob(result.jobId, selectedDocId, `Indexed ${result.document.version}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  };

  const saveFaq = async (draft: Omit<FaqPair, "id" | "updatedAt"> & { id?: string }) => {
    try {
      if (draft.id) {
        await patchKbFaq(draft.id, {
          question: draft.question,
          answer: draft.answer,
          intent: draft.intent,
          enabled: draft.enabled,
          linkedDocId: draft.linkedDocId ?? null,
        });
        toast.success("FAQ saved");
      } else {
        await createKbFaq({
          question: draft.question,
          answer: draft.answer,
          intent: draft.intent,
          enabled: draft.enabled,
          linkedDocId: draft.linkedDocId,
          gapId: pendingGapId ?? undefined,
        });
        toast.success(pendingGapId ? "FAQ created and gap linked" : "FAQ created");
      }
      setFaqOpen(false);
      setEditingFaq(null);
      setPendingGapId(null);
      await invalidateKb();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
      throw err;
    }
  };

  const removeFaq = async (id: string) => {
    try {
      await deleteKbFaq(id);
      toast.success("FAQ deleted");
      setFaqOpen(false);
      setEditingFaq(null);
      setPendingGapId(null);
      await invalidateKb();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
      throw err;
    }
  };

  const toggleFaq = async (id: string, enabled: boolean) => {
    try {
      await patchKbFaq(id, { enabled });
      await invalidateKb();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  };

  const openCreateFaqFromGap = (gap: KbGap) => {
    setPendingGapId(gap.id);
    setEditingFaq({
      id: "",
      question: gap.text,
      answer: "",
      intent: gap.topIntent || "other",
      enabled: true,
      updatedAt: new Date().toISOString(),
    });
    setFaqOpen(true);
    setTab("faqs");
  };

  const attachDocToGap = async (gapId: string, documentId: string) => {
    try {
      await linkKbGap(gapId, { kbDocumentId: documentId });
      toast.success("Document linked to gap");
      await invalidateKb();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  };

  const pendingDeleteDoc = pendingDeleteId ? docs.find((d) => d.id === pendingDeleteId) : null;
  const searchActive = Boolean(search.trim()) || typeFilter !== "all" || enabledFilter !== "all";
  const docTypeOptions = useMemo(() => {
    const types = new Set(docs.map((d) => d.type));
    return Array.from(types).sort();
  }, [docs]);

  return (
    <AppShell>
      <div className="flex h-full min-h-0 flex-col overflow-hidden">
        <div className="shrink-0 border-b border-[var(--border-token)] bg-surface-card px-4 py-3">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <h1 className="text-[17px] font-semibold text-brand-navy">Knowledge Base (RAG) Manager</h1>
              <p className="text-[12px] text-text-muted">
                HDFC insurance corpus for collections cross-sell / upsell — documents, FAQs and
                retrieval controls.
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <div className="relative">
                <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-muted" />
                <Input
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Filter this page…"
                  aria-label="Filter knowledge base"
                  className="h-9 w-56 pl-8 pr-8"
                />
                {search && (
                  <button
                    type="button"
                    className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-0.5 text-text-muted hover:text-brand-navy"
                    onClick={() => setSearch("")}
                    aria-label="Clear search"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>
              <Button
                variant="outline"
                size="sm"
                disabled={globalBusy}
                onClick={() => setSyncConfirmOpen(true)}
              >
                <Database className={`mr-1 h-3.5 w-3.5 ${syncBusy ? "animate-pulse" : ""}`} />
                {syncBusy ? "Syncing…" : "Sync from source_db"}
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={globalBusy}
                onClick={() => void reindexAll()}
              >
                <RefreshCw className={`mr-1 h-3.5 w-3.5 ${reindexAllBusy ? "animate-spin" : ""}`} />
                {reindexAllBusy ? "Re-indexing…" : "Re-index all"}
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={globalBusy}
                onClick={() => {
                  setPendingGapId(null);
                  setEditingFaq(null);
                  setFaqOpen(true);
                }}
              >
                <Plus className="mr-1 h-3.5 w-3.5" /> Add FAQ
              </Button>
              <Button
                size="sm"
                disabled={globalBusy}
                onClick={() => {
                  setUploadGapId(null);
                  setShowUpload(true);
                }}
              >
                <Upload className="mr-1 h-3.5 w-3.5" /> Upload document
              </Button>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="outline" size="sm" disabled={globalBusy} aria-label="More actions">
                    <MoreHorizontal className="h-4 w-4" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-56">
                  <DropdownMenuLabel>Danger zone</DropdownMenuLabel>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    className="text-red-700 focus:text-red-800"
                    onClick={() => {
                      setPurgeScope("uploads");
                      setPurgeTyped("");
                      setPurgeConfirmOpen(true);
                    }}
                  >
                    <Trash2 className="mr-2 h-3.5 w-3.5" />
                    Delete documents…
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          <KbStatsStrip {...stripStats} />
          <KbSnapshotsStrip snapshots={snapshots} />

          <Tabs value={tab} onValueChange={setTab} className="mt-4">
            <TabsList>
              <TabsTrigger value="documents">
                Documents ({docsLoading ? "…" : docs.length})
              </TabsTrigger>
              <TabsTrigger value="faqs">FAQs ({faqsLoading ? "…" : faqs.length})</TabsTrigger>
              <TabsTrigger value="gaps">
                Analytics Gaps ({gapsLoading ? "…" : openGaps})
              </TabsTrigger>
              <TabsTrigger value="test">Test Retrieval</TabsTrigger>
            </TabsList>

            <TabsContent value="documents" className="mt-3">
              <div className="mb-3 flex flex-wrap items-center gap-2">
                <select
                  className="h-8 rounded-md border border-[var(--border-token)] bg-surface-card px-2 text-[12px] text-text-secondary"
                  value={typeFilter}
                  onChange={(e) => setTypeFilter(e.target.value as "all" | KbDocType)}
                  aria-label="Filter by type"
                >
                  <option value="all">All types</option>
                  {docTypeOptions.map((t) => (
                    <option key={t} value={t}>
                      {DOC_TYPE_LABEL[t]}
                    </option>
                  ))}
                </select>
                <select
                  className="h-8 rounded-md border border-[var(--border-token)] bg-surface-card px-2 text-[12px] text-text-secondary"
                  value={enabledFilter}
                  onChange={(e) => setEnabledFilter(e.target.value as "all" | "enabled" | "disabled")}
                  aria-label="Filter by enabled"
                >
                  <option value="all">All statuses</option>
                  <option value="enabled">Enabled only</option>
                  <option value="disabled">Disabled only</option>
                </select>
                <span className="text-[11px] text-text-muted">
                  Showing {filteredDocs.length}
                  {searchActive ? ` of ${docs.length}` : ""}
                </span>
                {searchActive && (
                  <button
                    type="button"
                    className="text-[11px] font-medium text-brand-primary hover:underline"
                    onClick={() => {
                      setSearch("");
                      setTypeFilter("all");
                      setEnabledFilter("all");
                    }}
                  >
                    Clear filters
                  </button>
                )}
              </div>
              <div className="grid grid-cols-1 gap-3 xl:grid-cols-[minmax(0,1fr)_400px]">
                <DocumentsTable
                  docs={filteredDocs}
                  selectedId={selectedDocId}
                  onSelect={(id) => {
                    userDismissedInspector.current = false;
                    setSelectedDocId(id);
                  }}
                  onToggle={(id, enabled) => void toggleDoc(id, enabled)}
                  onReindex={(id) => void reindexDoc(id)}
                  onDelete={(id) => setPendingDeleteId(id)}
                  reindexing={reindexing}
                  deletingId={deletingId}
                  loading={docsLoading}
                  filteredOutSelected={selectedHiddenByFilter}
                />
                {selectedDoc ? (
                  <div className="min-h-[500px] xl:sticky xl:top-0 xl:self-start xl:max-h-[calc(100vh-8rem)]">
                    <DocumentInspector
                      doc={selectedDoc}
                      chunks={selectedChunks}
                      onClose={() => {
                        userDismissedInspector.current = true;
                        setSelectedDocId(null);
                      }}
                      onReindex={() => void reindexDoc(selectedDoc.id)}
                      onToggle={() => void toggleDoc(selectedDoc.id, !selectedDoc.enabled)}
                      onNewVersion={onNewVersion}
                      onDelete={() => removeDoc(selectedDoc.id)}
                      onOpenChunk={setOpenChunk}
                      onSaveMeta={(patch) => saveDocMeta(selectedDoc.id, patch)}
                      reindexing={reindexing.has(selectedDoc.id)}
                      savingMeta={savingMeta}
                      deleting={deletingId === selectedDoc.id}
                    />
                  </div>
                ) : (
                  <div className="hidden items-center justify-center rounded-lg border border-dashed border-[var(--border-token)] p-6 text-center text-[12px] text-text-muted xl:flex">
                    Select a document to inspect its chunks.
                  </div>
                )}
              </div>
            </TabsContent>

            <TabsContent value="faqs" className="mt-3">
              <FaqTable
                faqs={filteredFaqs}
                onSelect={(f) => {
                  setPendingGapId(null);
                  setEditingFaq(f);
                  setFaqOpen(true);
                }}
                onToggle={(id, enabled) => void toggleFaq(id, enabled)}
                onDelete={(id) => {
                  if (window.confirm("Delete this FAQ permanently?")) {
                    void removeFaq(id);
                  }
                }}
                selectedId={editingFaq?.id || null}
              />
            </TabsContent>

            <TabsContent value="gaps" className="mt-3">
              <AnalyticsGapsTable
                gaps={filteredGaps}
                documents={docs}
                faqs={faqs}
                onCreateFaq={openCreateFaqFromGap}
                onAttachDoc={attachDocToGap}
                onUploadForGap={(gap) => {
                  setUploadGapId(gap.id);
                  setShowUpload(true);
                  setTab("documents");
                  toast.info("Upload a document — it will be linked to this gap.");
                }}
              />
            </TabsContent>

            <TabsContent value="test" className="mt-3">
              <TestRetrievalPanel />
            </TabsContent>
          </Tabs>
        </div>
      </div>

      <input
        ref={versionInputRef}
        type="file"
        accept=".md,.txt,.markdown,text/plain,text/markdown"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0] ?? null;
          e.target.value = "";
          void onVersionFile(file);
        }}
      />

      <ChunkModal chunk={openChunk} onClose={() => setOpenChunk(null)} />
      <FaqEditorSheet
        open={faqOpen}
        faq={editingFaq}
        documents={docs}
        onClose={() => {
          setFaqOpen(false);
          setEditingFaq(null);
          setPendingGapId(null);
        }}
        onSave={saveFaq}
        onDelete={removeFaq}
      />
      <UploadWizard
        open={showUpload}
        onClose={() => {
          setShowUpload(false);
          setUploadGapId(null);
        }}
        onCreate={addDoc}
      />

      <AlertDialog open={syncConfirmOpen} onOpenChange={setSyncConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Sync from source_db?</AlertDialogTitle>
            <AlertDialogDescription>
              Re-reads policy, benefits and FAQ files from disk, re-embeds changed content, and
              replaces product FAQ pairs. Uploaded-only documents are left untouched. Azure embedding
              calls may take several minutes.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={() => void runSyncFromSourceDb()}>
              Sync corpus
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog
        open={purgeConfirmOpen}
        onOpenChange={(open) => {
          setPurgeConfirmOpen(open);
          if (!open) setPurgeTyped("");
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete documents</AlertDialogTitle>
            <AlertDialogDescription>
              Hard-deletes matching documents and related chunks. Type DELETE to confirm.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="space-y-3">
            <div>
              <Label className="text-[11px] uppercase tracking-wide text-text-muted">Scope</Label>
              <select
                className="mt-1 flex h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
                value={purgeScope}
                onChange={(e) => setPurgeScope(e.target.value as KbPurgeScope)}
              >
                <option value="uploads">Uploaded docs only (safe default)</option>
                <option value="corpus">Corpus docs from source_db</option>
                <option value="all">Entire knowledge base</option>
              </select>
            </div>
            <div>
              <Label className="text-[11px] uppercase tracking-wide text-text-muted">
                Type DELETE
              </Label>
              <Input
                className="mt-1"
                value={purgeTyped}
                onChange={(e) => setPurgeTyped(e.target.value)}
                placeholder="DELETE"
                autoComplete="off"
              />
            </div>
          </div>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              className="bg-red-600 hover:bg-red-700"
              disabled={purgeTyped.trim().toUpperCase() !== "DELETE" || purgeBusy}
              onClick={(e) => {
                e.preventDefault();
                void runPurge();
              }}
            >
              {purgeBusy ? "Deleting…" : "Delete permanently"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog
        open={Boolean(pendingDeleteId)}
        onOpenChange={(open) => {
          if (!open) setPendingDeleteId(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              Delete “{pendingDeleteDoc?.title ?? "document"}”?
            </AlertDialogTitle>
            <AlertDialogDescription>
              Permanently removes this document and its chunks. This cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              className="bg-red-600 hover:bg-red-700"
              disabled={!pendingDeleteId || deletingId === pendingDeleteId}
              onClick={(e) => {
                e.preventDefault();
                if (pendingDeleteId) void removeDoc(pendingDeleteId);
              }}
            >
              Delete permanently
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </AppShell>
  );
}
