import { useEffect, useMemo, useReducer, useRef } from "react";
import { createLazyFileRoute, useNavigate } from "@tanstack/react-router";
import { toast } from "sonner";
import { Database, MoreHorizontal, Plus, RefreshCw, Trash2, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Lozenge } from "@/components/ui/lozenge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { KbStatsStrip, type KbTab } from "@/components/kb/KbStatsStrip";
import { KbSnapshotsStrip } from "@/components/kb/KbSnapshotsStrip";
import { KbToolbar } from "@/components/kb/KbToolbar";
import { DocumentsTable } from "@/components/kb/DocumentsTable";
import { DocumentInspector } from "@/components/kb/DocumentInspector";
import { ChunkModal } from "@/components/kb/ChunkModal";
import { FaqTable } from "@/components/kb/FaqTable";
import { FaqEditorSheet } from "@/components/kb/FaqEditorSheet";
import { AnalyticsGapsTable } from "@/components/kb/AnalyticsGapsTable";
import { TestRetrievalPanel } from "@/components/kb/TestRetrievalPanel";
import { UploadWizard } from "@/components/kb/UploadWizard";
import { KbConfirmDialogs } from "@/components/kb/KbConfirmDialogs";
import { INITIAL_KB_STATE, kbReducer } from "@/components/kb/kbState";
import { useKbActions } from "@/components/kb/useKbActions";
import {
  useKbChunks,
  useKbDocuments,
  useKbFaqs,
  useKbGaps,
  useKbSnapshots,
  useKbStats,
} from "@/api/kb";
import type { KnowledgeBaseSearch } from "./_app.knowledge-base";

export const Route = createLazyFileRoute("/_app/knowledge-base")({
  component: KnowledgeBaseRoute,
});

function KnowledgeBaseRoute() {
  return <KnowledgeBasePage search={Route.useSearch()} />;
}

export function KnowledgeBasePage({ search: params }: { search: KnowledgeBaseSearch }) {
  const { gapId: searchGapId, q: searchQ, tab: searchTab } = params;
  const navigate = useNavigate({ from: "/knowledge-base" });
  const docsQuery = useKbDocuments();
  const faqsQuery = useKbFaqs();
  const gapsQuery = useKbGaps();
  const { data: stats } = useKbStats();
  const { data: snapshots = [] } = useKbSnapshots();
  const docs = useMemo(() => docsQuery.data ?? [], [docsQuery.data]);
  const faqs = useMemo(() => faqsQuery.data ?? [], [faqsQuery.data]);
  const gaps = useMemo(() => gapsQuery.data ?? [], [gapsQuery.data]);

  const [state, dispatch] = useReducer(kbReducer, INITIAL_KB_STATE);
  const { selectedDocId, filters, busy } = state;
  const { search } = filters;
  const versionInputRef = useRef<HTMLInputElement>(null);
  const deepLinkApplied = useRef(false);

  const tab: KbTab = searchTab ?? (searchGapId ? "gaps" : "documents");
  const setTab = (next: KbTab) => {
    void navigate({ search: (prev) => ({ ...prev, tab: next }), replace: true });
  };

  const actions = useKbActions({ state, dispatch, docs, setTab });
  const { globalBusy } = actions;

  const { data: selectedChunks = [] } = useKbChunks(selectedDocId);

  // A selection the list no longer holds is no selection.
  useEffect(() => {
    if (selectedDocId && !docs.some((d) => d.id === selectedDocId)) {
      dispatch({ type: "select", id: null });
    }
  }, [docs, selectedDocId]);

  // The deep link from Bot Analytics: the question it asked, once.
  useEffect(() => {
    if (deepLinkApplied.current || (!searchGapId && !searchQ)) return;
    deepLinkApplied.current = true;
    if (searchQ) dispatch({ type: "filters", patch: { search: searchQ } });
  }, [searchGapId, searchQ]);

  const filteredDocs = useMemo(() => {
    const q = search.trim().toLowerCase();
    return docs.filter((d) => {
      if (filters.type !== "all" && d.type !== filters.type) return false;
      if (filters.enabled === "enabled" && !d.enabled) return false;
      if (filters.enabled === "disabled" && d.enabled) return false;
      if (!q) return true;
      return (
        d.title.toLowerCase().includes(q) ||
        d.filename.toLowerCase().includes(q) ||
        d.tags.some((t) => t.includes(q)) ||
        d.id.toLowerCase().includes(q)
      );
    });
  }, [docs, search, filters.type, filters.enabled]);

  const selectedHiddenByFilter = Boolean(
    selectedDocId &&
    docs.some((d) => d.id === selectedDocId) &&
    !filteredDocs.some((d) => d.id === selectedDocId),
  );

  const filteredFaqs = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return faqs;
    return faqs.filter(
      (f) =>
        f.question.toLowerCase().includes(q) ||
        f.answer.toLowerCase().includes(q) ||
        f.intent.includes(q),
    );
  }, [faqs, search]);

  const filteredGaps = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return gaps;
    return gaps.filter((g) => {
      if (g.text.toLowerCase().includes(q) || g.topIntent.toLowerCase().includes(q)) return true;
      if (g.linkedDocumentId) {
        const doc = docs.find((d) => d.id === g.linkedDocumentId);
        if (doc?.title.toLowerCase().includes(q) || doc?.filename.toLowerCase().includes(q))
          return true;
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

  const stripStats = stats ?? {
    docs: docs.length,
    activeDocs: docs.filter((d) => d.enabled && d.status === "indexed").length,
    faqs: faqs.filter((f) => f.enabled).length,
    chunks: 0,
    gaps: openGaps,
    lastIndexed: docs[0]?.lastIndexed || new Date().toISOString(),
    avgScore: 0,
  };

  const visibleGaps = filters.showResolved ? filteredGaps : filteredGaps.filter((g) => !g.resolved);
  const searchActive =
    Boolean(search.trim()) ||
    (tab === "documents" && (filters.type !== "all" || filters.enabled !== "all"));
  const toolbarVisible =
    tab === "documents"
      ? filteredDocs.length
      : tab === "faqs"
        ? filteredFaqs.length
        : visibleGaps.length;
  const toolbarTotal =
    tab === "documents" ? docs.length : tab === "faqs" ? faqs.length : gaps.length;
  const docTypeOptions = useMemo(() => Array.from(new Set(docs.map((d) => d.type))).sort(), [docs]);

  return (
    <>
      <div className="flex h-full min-h-0 flex-col overflow-hidden bg-surface">
        <div className="shrink-0 border-b border-border px-200 py-150">
          <div className="flex flex-wrap items-center justify-between gap-150">
            <div className="min-w-0">
              <h1 className="heading-small font-semibold leading-none text-text">Knowledge base</h1>
              <p className="mt-050 text-body-small text-text-subtlest">
                Sources the bot retrieves at runtime — documents, FAQs, and coverage gaps.
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-100">
              {(busy.sync || busy.reindexAll) && (
                <Lozenge tone="selected">{busy.sync ? "Syncing corpus…" : "Re-indexing…"}</Lozenge>
              )}
              {tab === "faqs" && (
                <Button
                  variant="primary"
                  size="sm"
                  disabled={globalBusy}
                  onClick={() => dispatch({ type: "faq", open: true })}
                >
                  <Plus className="mr-050 h-3.5 w-3.5" /> Add FAQ
                </Button>
              )}
              {tab !== "faqs" && tab !== "test" && (
                <Button
                  variant="primary"
                  size="sm"
                  disabled={globalBusy}
                  onClick={() => {
                    dispatch({ type: "upload", open: true });
                    setTab("documents");
                  }}
                >
                  <Upload className="mr-050 h-3.5 w-3.5" /> Upload document
                </Button>
              )}
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={globalBusy}
                    aria-label="More actions"
                  >
                    <MoreHorizontal className="h-4 w-4" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-56">
                  <DropdownMenuLabel>Corpus</DropdownMenuLabel>
                  <DropdownMenuItem
                    disabled={globalBusy}
                    onClick={() => dispatch({ type: "confirm", confirm: { kind: "sync" } })}
                  >
                    <Database className="mr-100 h-3.5 w-3.5" />
                    Sync from source_db
                  </DropdownMenuItem>
                  <DropdownMenuItem disabled={globalBusy} onClick={() => void actions.reindexAll()}>
                    <RefreshCw className="mr-100 h-3.5 w-3.5" />
                    Re-index all
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuLabel>Danger zone</DropdownMenuLabel>
                  <DropdownMenuItem
                    className="text-text-danger-bolder focus:text-text-danger-bolder"
                    onClick={() =>
                      dispatch({
                        type: "confirm",
                        confirm: { kind: "purge", scope: "uploads", typed: "" },
                      })
                    }
                  >
                    <Trash2 className="mr-100 h-3.5 w-3.5" />
                    Delete documents…
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          </div>
        </div>

        <KbStatsStrip {...stripStats} tab={tab} onTab={setTab} />
        <KbSnapshotsStrip snapshots={snapshots} />

        <Tabs
          value={tab}
          onValueChange={(v) => setTab(v as KbTab)}
          className="flex min-h-0 flex-1 flex-col overflow-hidden"
        >
          <TabsList className="h-10 w-full shrink-0 justify-start px-200">
            <TabsTrigger value="documents">
              Documents
              <span className="ml-075 tabular text-text-subtlest">
                {docsQuery.isLoading ? "…" : docs.length}
              </span>
            </TabsTrigger>
            <TabsTrigger value="faqs">
              FAQs
              <span className="ml-075 tabular text-text-subtlest">
                {faqsQuery.isLoading ? "…" : faqs.length}
              </span>
            </TabsTrigger>
            <TabsTrigger value="gaps">
              Gaps
              <span className="ml-075 tabular text-text-subtlest">
                {gapsQuery.isLoading ? "…" : openGaps}
              </span>
            </TabsTrigger>
            <TabsTrigger value="test">Test retrieval</TabsTrigger>
          </TabsList>

          <KbToolbar
            tab={tab}
            search={search}
            onSearch={(v) => dispatch({ type: "filters", patch: { search: v } })}
            visibleCount={toolbarVisible}
            totalCount={toolbarTotal}
            searchActive={searchActive}
            onClear={() =>
              dispatch({ type: "filters", patch: { search: "", type: "all", enabled: "all" } })
            }
            docTypeOptions={docTypeOptions}
            filters={{ type: filters.type, enabled: filters.enabled }}
            onFilters={(next) => dispatch({ type: "filters", patch: next })}
            showResolved={filters.showResolved}
            onShowResolved={(v) => dispatch({ type: "filters", patch: { showResolved: v } })}
          />

          <TabsContent
            value="documents"
            className="mt-0 flex min-h-0 flex-1 flex-col overflow-hidden"
          >
            <div className="relative flex min-h-0 flex-1 overflow-hidden">
              <div className="min-h-0 min-w-0 flex-1 overflow-hidden">
                <DocumentsTable
                  docs={filteredDocs}
                  selectedId={selectedDocId}
                  onSelect={(id) => dispatch({ type: "select", id })}
                  onToggle={(id, enabled) => void actions.toggleDoc(id, enabled)}
                  onReindex={(id) => void actions.reindexDoc(id)}
                  onDelete={(id) =>
                    dispatch({ type: "confirm", confirm: { kind: "deleteDoc", id } })
                  }
                  reindexing={busy.reindexing}
                  deletingId={busy.deletingId}
                  loading={docsQuery.isLoading}
                  isError={docsQuery.isError}
                  error={docsQuery.error}
                  filteredOutSelected={selectedHiddenByFilter}
                  emptyFromFilter={searchActive && filteredDocs.length === 0 && docs.length > 0}
                />
              </div>
              {selectedDoc && (
                <div className="absolute inset-y-0 right-0 z-20 flex shadow-overlay xl:static xl:z-auto xl:shadow-none">
                  <DocumentInspector
                    doc={selectedDoc}
                    chunks={selectedChunks}
                    onClose={() => dispatch({ type: "select", id: null })}
                    onReindex={() => void actions.reindexDoc(selectedDoc.id)}
                    onToggle={() => void actions.toggleDoc(selectedDoc.id, !selectedDoc.enabled)}
                    onNewVersion={() => versionInputRef.current?.click()}
                    onDelete={() => actions.removeDoc(selectedDoc.id)}
                    onOpenChunk={(chunk) => dispatch({ type: "openChunk", chunk })}
                    onSaveMeta={(patch) => actions.saveDocMeta(selectedDoc.id, patch)}
                    reindexing={busy.reindexing.has(selectedDoc.id)}
                    savingMeta={busy.savingMeta}
                    deleting={busy.deletingId === selectedDoc.id}
                  />
                </div>
              )}
            </div>
          </TabsContent>

          <TabsContent value="faqs" className="mt-0 flex min-h-0 flex-1 flex-col overflow-hidden">
            <FaqTable
              faqs={filteredFaqs}
              onSelect={(f) => dispatch({ type: "faq", open: true, editing: f })}
              onToggle={(id, enabled) => void actions.toggleFaq(id, enabled)}
              onDelete={(id) => dispatch({ type: "confirm", confirm: { kind: "deleteFaq", id } })}
              selectedId={state.faq.editing?.id || null}
              loading={faqsQuery.isLoading}
              isError={faqsQuery.isError}
              error={faqsQuery.error}
              emptyFromFilter={
                Boolean(search.trim()) && filteredFaqs.length === 0 && faqs.length > 0
              }
            />
          </TabsContent>

          <TabsContent value="gaps" className="mt-0 flex min-h-0 flex-1 flex-col overflow-hidden">
            <AnalyticsGapsTable
              gaps={filteredGaps}
              documents={docs}
              faqs={faqs}
              showResolved={filters.showResolved}
              loading={gapsQuery.isLoading}
              isError={gapsQuery.isError}
              error={gapsQuery.error}
              onCreateFaq={actions.openCreateFaqFromGap}
              onAttachDoc={actions.attachDocToGap}
              onUploadForGap={(gap) => {
                dispatch({ type: "upload", open: true, gapId: gap.id });
                setTab("documents");
                toast.info("Upload a document — it will be linked to this gap.");
              }}
            />
          </TabsContent>

          <TabsContent value="test" className="mt-0 flex min-h-0 flex-1 flex-col overflow-hidden">
            <TestRetrievalPanel />
          </TabsContent>
        </Tabs>
      </div>

      <input
        ref={versionInputRef}
        type="file"
        accept=".md,.txt,.markdown,text/plain,text/markdown"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0] ?? null;
          e.target.value = "";
          void actions.onVersionFile(file);
        }}
      />

      <ChunkModal
        chunk={state.openChunk}
        onClose={() => dispatch({ type: "openChunk", chunk: null })}
      />
      <FaqEditorSheet
        open={state.faq.open}
        faq={state.faq.editing}
        documents={docs}
        onClose={() => dispatch({ type: "faq", open: false })}
        onSave={actions.saveFaq}
        onDelete={actions.removeFaq}
      />
      <UploadWizard
        open={state.upload.open}
        onClose={() => dispatch({ type: "upload", open: false })}
        onCreate={actions.addDoc}
      />
      <KbConfirmDialogs
        state={state}
        dispatch={dispatch}
        docs={docs}
        faqs={faqs}
        onSync={() => void actions.runSyncFromSourceDb()}
        onPurge={() => void actions.runPurge()}
        onDeleteDoc={(id) => void actions.removeDoc(id)}
        onDeleteFaq={(id) => void actions.removeFaq(id)}
      />
    </>
  );
}
