/**
 * Every write the knowledge-base screen makes, over the reducer's state.
 *
 * Each action talks to api/kb, toasts the outcome, flips the busy flag it owns
 * and invalidates the KB queries. Index jobs are watched to completion so the
 * row's spinner reflects the worker, not the request.
 */
import type { Dispatch } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

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
  type FaqPair,
  type KbDocument,
  type KbGap,
  type KbUploadInput,
} from "@/api/kb";
import type { KbDocumentMetaPatch } from "./DocumentInspector";
import type { KbAction, KbState } from "./kbState";
import type { KbTab } from "./KbStatsStrip";

const message = (err: unknown) => (err instanceof Error ? err.message : String(err));

export function useKbActions({
  state,
  dispatch,
  docs,
  setTab,
}: {
  state: KbState;
  dispatch: Dispatch<KbAction>;
  docs: KbDocument[];
  setTab: (tab: KbTab) => void;
}) {
  const qc = useQueryClient();
  const globalBusy = state.busy.reindexAll || state.busy.sync || state.busy.purge;

  const invalidateKb = async () => {
    await Promise.all(
      ["documents", "stats", "chunks", "faqs", "gaps", "snapshots"].map((k) =>
        qc.invalidateQueries({ queryKey: ["kb", k] }),
      ),
    );
  };

  const watchJob = async (jobId: string | null | undefined, docId: string, label: string) => {
    if (!jobId) {
      await invalidateKb();
      return;
    }
    dispatch({ type: "reindexing", id: docId, on: true });
    try {
      const job = await pollKbIndexJob(jobId);
      if (job.status === "succeeded") toast.success(label);
      else toast.error(job.error || `${label} failed`);
    } catch (err) {
      toast.error(message(err));
    } finally {
      dispatch({ type: "reindexing", id: docId, on: false });
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
      if (enabled && result.jobId) void watchJob(result.jobId, id, "Re-indexed after enable");
    } catch (err) {
      toast.error(message(err));
    }
  };

  const saveDocMeta = async (id: string, patch: KbDocumentMetaPatch) => {
    const doc = docs.find((d) => d.id === id);
    if (!doc) return;
    const chunkChanged = patch.chunkSize !== doc.chunkSize || patch.overlap !== doc.overlap;
    dispatch({ type: "busy", patch: { savingMeta: true } });
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
      toast.error(message(err));
      throw err;
    } finally {
      dispatch({ type: "busy", patch: { savingMeta: false } });
    }
  };

  const reindexDoc = async (id: string) => {
    try {
      const result = await reindexKbDocument(id);
      toast.info("Re-index queued…");
      void watchJob(result.jobId, id, "Re-indexed");
    } catch (err) {
      toast.error(message(err));
    }
  };

  const removeDoc = async (id: string) => {
    dispatch({ type: "busy", patch: { deletingId: id } });
    try {
      const result = await deleteKbDocument(id);
      toast.success(
        `Deleted document${result.faqsDeleted ? ` (+${result.faqsDeleted} FAQs)` : ""}`,
      );
      if (state.selectedDocId === id) dispatch({ type: "select", id: null });
      await invalidateKb();
    } catch (err) {
      toast.error(message(err));
      throw err;
    } finally {
      dispatch({ type: "busy", patch: { deletingId: null } });
      dispatch({ type: "confirm", confirm: null });
    }
  };

  const reindexAll = async () => {
    if (globalBusy) return;
    dispatch({ type: "busy", patch: { reindexAll: true } });
    try {
      const result = await reindexAllKbDocuments();
      toast.info(`Full re-index queued for ${result.count} enabled document(s)…`);
      dispatch({ type: "reindexingAll", ids: docs.filter((d) => d.enabled).map((d) => d.id) });
      const settled = result.jobIds.length
        ? await pollKbIndexJobs(result.jobIds, { timeoutMs: 300_000 })
        : { succeeded: 0, failed: 0, timedOut: 0, jobs: [] };
      dispatch({ type: "reindexingAll", ids: [] });
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
        toast.success(
          `Full re-index complete — ${settled.succeeded}/${result.jobIds.length} succeeded`,
        );
      } else {
        toast.error(
          `Re-index finished with issues — ${settled.succeeded} ok, ${settled.failed} failed, ${settled.timedOut} timed out`,
        );
      }
    } catch (err) {
      dispatch({ type: "reindexingAll", ids: [] });
      toast.error(message(err));
    } finally {
      dispatch({ type: "busy", patch: { reindexAll: false } });
    }
  };

  const runSyncFromSourceDb = async () => {
    dispatch({ type: "busy", patch: { sync: true } });
    dispatch({ type: "confirm", confirm: null });
    const toastId = toast.loading(
      "Syncing HDFC corpus from source_db… this may take a few minutes",
    );
    try {
      const result = await ingestSourceDb();
      toast.success(
        `Synced ${result.products.length} products — ${result.docs} docs, ${result.chunks} chunks, ${result.faqs} FAQs`,
        { id: toastId },
      );
      await invalidateKb();
    } catch (err) {
      toast.error(message(err), { id: toastId });
    } finally {
      dispatch({ type: "busy", patch: { sync: false } });
    }
  };

  const runPurge = async () => {
    const confirm = state.confirm;
    // The deliberateness gate is the slider in KbConfirmDialogs, which cannot
    // be crossed by a stray click or keypress (ui/slide-to-confirm.test.tsx).
    // This used to re-check a typed "DELETE" carried in the state; there is
    // nothing to re-read now, and a second copy of the gate was never what
    // made the first one hard to trip by accident.
    if (confirm?.kind !== "purge") return;
    dispatch({ type: "busy", patch: { purge: true } });
    dispatch({ type: "confirm", confirm: null });
    try {
      const result = await purgeKbDocuments(confirm.scope);
      toast.success(
        `Purged ${result.documentsDeleted} document(s)` +
          (result.faqsDeleted ? `, ${result.faqsDeleted} FAQ(s)` : ""),
      );
      dispatch({ type: "select", id: null });
      await invalidateKb();
    } catch (err) {
      toast.error(message(err));
    } finally {
      dispatch({ type: "busy", patch: { purge: false } });
    }
  };

  const addDoc = async (input: KbUploadInput) => {
    const gapId = state.upload.gapId;
    try {
      const result = await uploadKbDocument(input);
      dispatch({ type: "select", id: result.document.id });
      setTab("documents");
      toast.success(
        input.indexNow
          ? `Upload queued for indexing: "${result.document.title}"`
          : `Saved draft "${result.document.title}"`,
      );
      if (gapId) {
        try {
          await linkKbGap(gapId, { kbDocumentId: result.document.id });
          toast.success("Gap linked to uploaded document");
        } catch (err) {
          toast.error(message(err));
        }
      }
      await invalidateKb();
      if (result.jobId)
        void watchJob(result.jobId, result.document.id, `Indexed "${result.document.title}"`);
    } catch (err) {
      toast.error(message(err));
      throw err;
    }
  };

  const onVersionFile = async (file: File | null) => {
    const docId = state.selectedDocId;
    if (!file || !docId) return;
    try {
      const result = await uploadKbDocumentVersion(docId, file);
      toast.info(`New version ${result.document.version} queued…`);
      void watchJob(result.jobId, docId, `Indexed ${result.document.version}`);
    } catch (err) {
      toast.error(message(err));
    }
  };

  const saveFaq = async (draft: Omit<FaqPair, "id" | "updatedAt"> & { id?: string }) => {
    const gapId = state.faq.gapId;
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
          gapId: gapId ?? undefined,
        });
        toast.success(gapId ? "FAQ created and gap linked" : "FAQ created");
      }
      dispatch({ type: "faq", open: false });
      await invalidateKb();
    } catch (err) {
      toast.error(message(err));
      throw err;
    }
  };

  const removeFaq = async (id: string) => {
    try {
      await deleteKbFaq(id);
      toast.success("FAQ deleted");
      dispatch({ type: "faq", open: false });
      dispatch({ type: "confirm", confirm: null });
      await invalidateKb();
    } catch (err) {
      toast.error(message(err));
      throw err;
    }
  };

  const toggleFaq = async (id: string, enabled: boolean) => {
    try {
      await patchKbFaq(id, { enabled });
      await invalidateKb();
    } catch (err) {
      toast.error(message(err));
    }
  };

  const openCreateFaqFromGap = (gap: KbGap) => {
    dispatch({
      type: "faq",
      open: true,
      gapId: gap.id,
      editing: {
        id: "",
        question: gap.text,
        answer: "",
        intent: gap.topIntent || "other",
        enabled: true,
        updatedAt: new Date().toISOString(),
      },
    });
    setTab("faqs");
  };

  const attachDocToGap = async (gapId: string, documentId: string) => {
    try {
      await linkKbGap(gapId, { kbDocumentId: documentId });
      toast.success("Document linked to gap");
      await invalidateKb();
    } catch (err) {
      toast.error(message(err));
    }
  };

  return {
    globalBusy,
    toggleDoc,
    saveDocMeta,
    reindexDoc,
    removeDoc,
    reindexAll,
    runSyncFromSourceDb,
    runPurge,
    addDoc,
    onVersionFile,
    saveFaq,
    removeFaq,
    toggleFaq,
    openCreateFaqFromGap,
    attachDocToGap,
  };
}
