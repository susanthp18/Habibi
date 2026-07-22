import { useMemo, useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { toast } from "sonner";
import { AppShell } from "@/components/shell/AppShell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { KbStatsStrip } from "@/components/kb/KbStatsStrip";
import { DocumentsTable } from "@/components/kb/DocumentsTable";
import { DocumentInspector } from "@/components/kb/DocumentInspector";
import { ChunkModal } from "@/components/kb/ChunkModal";
import { FaqTable } from "@/components/kb/FaqTable";
import { FaqEditorSheet } from "@/components/kb/FaqEditorSheet";
import { AnalyticsGapsTable } from "@/components/kb/AnalyticsGapsTable";
import { TestRetrievalPanel } from "@/components/kb/TestRetrievalPanel";
import { UploadWizard } from "@/components/kb/UploadWizard";
import {
  chunks as seedChunks,
  computeKbStats,
  documents as seedDocs,
  faqs as seedFaqs,
  type FaqPair,
  type KbChunk,
  type KbDocument,
} from "@/data/kb-seed";
import { unansweredQuestions } from "@/data/bot-analytics-seed";
import { Upload, Plus, RefreshCw, Search } from "lucide-react";

export const Route = createFileRoute("/knowledge-base")({
  head: () => ({
    meta: [
      { title: "Knowledge Base (RAG) Manager — Collections Agent" },
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
  const [docs, setDocs] = useState<KbDocument[]>(seedDocs);
  const [chunkStore, setChunkStore] = useState<KbChunk[]>(seedChunks);
  const [faqs, setFaqs] = useState<FaqPair[]>(seedFaqs);
  const [reindexing, setReindexing] = useState<Set<string>>(new Set());
  const [selectedDocId, setSelectedDocId] = useState<string | null>(docs[0]?.id ?? null);
  const [openChunk, setOpenChunk] = useState<KbChunk | null>(null);
  const [showUpload, setShowUpload] = useState(false);
  const [editingFaq, setEditingFaq] = useState<FaqPair | null>(null);
  const [faqOpen, setFaqOpen] = useState(false);
  const [tab, setTab] = useState("documents");
  const [search, setSearch] = useState("");

  const stats = useMemo(
    () => computeKbStats(docs, faqs, unansweredQuestions.length),
    [docs, faqs],
  );

  const filteredDocs = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return docs;
    return docs.filter(
      (d) =>
        d.title.toLowerCase().includes(q) ||
        d.filename.toLowerCase().includes(q) ||
        d.tags.some((t) => t.includes(q)),
    );
  }, [docs, search]);

  const filteredFaqs = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return faqs;
    return faqs.filter(
      (f) => f.question.toLowerCase().includes(q) || f.answer.toLowerCase().includes(q) || f.intent.includes(q),
    );
  }, [faqs, search]);

  const selectedDoc = docs.find((d) => d.id === selectedDocId) ?? null;
  const selectedChunks = useMemo(
    () => (selectedDoc ? chunkStore.filter((c) => c.docId === selectedDoc.id) : []),
    [chunkStore, selectedDoc],
  );

  const toggleDoc = (id: string, enabled: boolean) => {
    setDocs((prev) => prev.map((d) => (d.id === id ? { ...d, enabled } : d)));
    toast.success(`${enabled ? "Enabled" : "Disabled"} — bot will ${enabled ? "start" : "stop"} using this source.`);
  };

  const reindexDoc = (id: string) => {
    setReindexing((s) => new Set(s).add(id));
    setTimeout(() => {
      setReindexing((s) => {
        const next = new Set(s);
        next.delete(id);
        return next;
      });
      setDocs((prev) =>
        prev.map((d) => (d.id === id ? { ...d, status: "indexed", lastIndexed: new Date().toISOString() } : d)),
      );
      toast.success("Re-indexed");
    }, 1400);
  };

  const reindexAll = () => {
    toast.info("Full re-index started for all enabled documents…");
    const ids = docs.filter((d) => d.enabled).map((d) => d.id);
    setReindexing((s) => new Set([...s, ...ids]));
    setTimeout(() => {
      setReindexing(new Set());
      setDocs((prev) =>
        prev.map((d) =>
          d.enabled ? { ...d, status: "indexed", lastIndexed: new Date().toISOString() } : d,
        ),
      );
      toast.success("Full re-index complete");
    }, 2000);
  };

  const addDoc = (doc: KbDocument, indexNow: boolean) => {
    setDocs((prev) => [doc, ...prev]);
    setSelectedDocId(doc.id);
    if (indexNow) {
      setReindexing((s) => new Set(s).add(doc.id));
      setTimeout(() => {
        setReindexing((s) => {
          const next = new Set(s);
          next.delete(doc.id);
          return next;
        });
        setDocs((prev) => prev.map((d) => (d.id === doc.id ? { ...d, status: "indexed" } : d)));
        toast.success(`Indexed "${doc.title}"`);
      }, 2000);
    } else {
      toast.info(`Saved "${doc.title}" as draft`);
    }
  };

  const saveFaq = (f: FaqPair) => {
    setFaqs((prev) => {
      const exists = prev.some((x) => x.id === f.id);
      return exists ? prev.map((x) => (x.id === f.id ? f : x)) : [f, ...prev];
    });
    setFaqOpen(false);
    setEditingFaq(null);
    toast.success("FAQ saved");
  };

  const toggleFaq = (id: string, enabled: boolean) => {
    setFaqs((prev) => prev.map((f) => (f.id === id ? { ...f, enabled } : f)));
  };

  return (
    <AppShell>
      <div className="flex h-full min-h-0 flex-col overflow-hidden">
        {/* Header */}
        <div className="shrink-0 border-b border-[var(--border-token)] bg-surface-card px-4 py-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h1 className="text-[17px] font-semibold text-brand-navy">Knowledge Base (RAG) Manager</h1>
              <p className="text-[12px] text-text-muted">
                Documents, FAQ pairs and retrieval controls the bot uses at runtime.
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <div className="relative">
                <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-muted" />
                <Input
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Search docs, FAQs, tags…"
                  className="h-9 w-64 pl-8"
                />
              </div>
              <Button variant="outline" size="sm" onClick={reindexAll}>
                <RefreshCw className="mr-1 h-3.5 w-3.5" /> Re-index all
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setEditingFaq(null);
                  setFaqOpen(true);
                }}
              >
                <Plus className="mr-1 h-3.5 w-3.5" /> Add FAQ
              </Button>
              <Button size="sm" onClick={() => setShowUpload(true)}>
                <Upload className="mr-1 h-3.5 w-3.5" /> Upload document
              </Button>
            </div>
          </div>
        </div>

        {/* Scrollable body */}
        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          <KbStatsStrip {...stats} />

          <Tabs value={tab} onValueChange={setTab} className="mt-4">
            <TabsList>
              <TabsTrigger value="documents">Documents ({docs.length})</TabsTrigger>
              <TabsTrigger value="faqs">FAQs ({faqs.length})</TabsTrigger>
              <TabsTrigger value="gaps">Analytics Gaps ({unansweredQuestions.length})</TabsTrigger>
              <TabsTrigger value="test">Test Retrieval</TabsTrigger>
            </TabsList>

            <TabsContent value="documents" className="mt-3">
              <div className="grid grid-cols-1 gap-3 xl:grid-cols-[minmax(0,1fr)_380px]">
                <DocumentsTable
                  docs={filteredDocs}
                  selectedId={selectedDocId}
                  onSelect={setSelectedDocId}
                  onToggle={toggleDoc}
                  onReindex={reindexDoc}
                  reindexing={reindexing}
                />
                {selectedDoc ? (
                  <div className="min-h-[500px]">
                    <DocumentInspector
                      doc={selectedDoc}
                      chunks={selectedChunks}
                      onClose={() => setSelectedDocId(null)}
                      onReindex={() => reindexDoc(selectedDoc.id)}
                      onToggle={() => toggleDoc(selectedDoc.id, !selectedDoc.enabled)}
                      onOpenChunk={setOpenChunk}
                      reindexing={reindexing.has(selectedDoc.id)}
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
                  setEditingFaq(f);
                  setFaqOpen(true);
                }}
                onToggle={toggleFaq}
                selectedId={editingFaq?.id ?? null}
              />
            </TabsContent>

            <TabsContent value="gaps" className="mt-3">
              <AnalyticsGapsTable
                onCreateFaq={(text) => {
                  setEditingFaq({
                    id: `f-${Date.now()}`,
                    question: text,
                    answer: "",
                    intent: "other",
                    enabled: true,
                    updatedAt: new Date().toISOString(),
                  });
                  setFaqOpen(true);
                  setTab("faqs");
                  toast.info("Draft FAQ pre-filled — add an answer to publish.");
                }}
                onAttachDoc={(text) => {
                  toast.success(`Flagged for KB curation: "${text.slice(0, 50)}…"`);
                }}
              />
            </TabsContent>

            <TabsContent value="test" className="mt-3">
              <TestRetrievalPanel />
            </TabsContent>
          </Tabs>
        </div>
      </div>

      <ChunkModal chunk={openChunk} onClose={() => setOpenChunk(null)} />
      <FaqEditorSheet
        open={faqOpen}
        faq={editingFaq}
        onClose={() => {
          setFaqOpen(false);
          setEditingFaq(null);
        }}
        onSave={saveFaq}
      />
      <UploadWizard open={showUpload} onClose={() => setShowUpload(false)} onCreate={addDoc} />
    </AppShell>
  );
}
