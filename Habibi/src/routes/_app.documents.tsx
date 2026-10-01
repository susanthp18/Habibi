import { useEffect, useMemo, useRef, useState } from "react";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { FileText, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { MetricsStrip } from "@/components/documents/MetricsStrip";
import { PipelineStrip } from "@/components/documents/PipelineStrip";
import { FiltersBar } from "@/components/documents/FiltersBar";
import { BulkActionBar } from "@/components/documents/BulkActionBar";
import { RequestsTable } from "@/components/documents/RequestsTable";
import { RequestSheet } from "@/components/documents/RequestSheet";
import { NewRequestSheet } from "@/components/documents/NewRequestSheet";
import type { DocChannel, DocRequest, DocStatus, DocumentFilters } from "@/api/types/documents";
import {
  CHANNEL_LABELS,
  DOC_TYPE_LABELS,
  computeMetrics,
  defaultFilters,
  filterDocs,
} from "@/lib/documents";
import {
  documentAssigneeOptions,
  recordManualSend,
  fetchDocuments,
  useDocuments,
  useReassignDocumentChannel,
  useRetryDocument,
} from "@/api/documents";
import { apiErrorMessage } from "@/api/config";
import { useConfirm } from "@/components/ui/use-confirm";
import { useStaff } from "@/api/staff";
import { useCustomers } from "@/api/customers";
import { parseDeepLinkSearch } from "@/lib/workspace-nav";
import { useOpenRecord } from "@/lib/use-open-record";

export const Route = createFileRoute("/_app/documents")({
  validateSearch: parseDeepLinkSearch,
  head: () => ({
    meta: [
      { title: "Document Fulfillment Desk — PayInt" },
      {
        name: "description",
        content:
          "Back-office queue for statement, no-dues, foreclosure and other document requests captured by the bot — with templates, channel routing, and an audit of manual sends.",
      },
      { property: "og:title", content: "Document Fulfillment Desk" },
      {
        property: "og:description",
        content:
          "Process bot-captured document requests: send each one yourself, record the send, and audit fulfillment.",
      },
    ],
  }),
  component: DocumentsPage,
});

function DocumentsPage() {
  const queryClient = useQueryClient();
  const navigate = useNavigate({ from: Route.fullPath });
  const search = Route.useSearch();
  const {
    data: items = [],
    isPending: docsPending,
    isError: docsError,
    error: docsErr,
  } = useDocuments();
  const { data: staff = [] } = useStaff();
  const { data: liveCustomers = [] } = useCustomers();
  const [filters, setFilters] = useState<DocumentFilters>(defaultFilters);
  const [openId, setOpenId] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [showNew, setShowNew] = useState(false);
  const deepLinkApplied = useRef(false);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["documents"] });
  };

  const assignees = useMemo(() => documentAssigneeOptions(staff), [staff]);

  const customerOptions = useMemo(
    () =>
      liveCustomers.map((c) => ({
        id: c.id,
        name: c.name,
        accountId: c.accountId,
      })),
    [liveCustomers],
  );

  const filtered = useMemo(() => filterDocs(items, filters), [filters, items]);
  const metrics = useMemo(() => computeMetrics(filtered), [filtered]);
  const openDoc = useOpenRecord({
    queryKey: "documents",
    label: "document request",
    id: openId,
    list: docsPending ? undefined : items,
    fetchOne: fetchDocuments,
    setOpenId,
  });

  const patchFilters = (p: Partial<DocumentFilters>) => setFilters((f) => ({ ...f, ...p }));

  const toggleStatus = (s: DocStatus) => {
    const cur = filters.statuses;
    patchFilters({ statuses: cur.includes(s) ? cur.filter((x) => x !== s) : [...cur, s] });
  };

  const toggleRow = (id: string) => {
    setSelected((prev) => {
      const n = new Set(prev);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  };
  const toggleAll = (ids: string[]) => {
    setSelected((prev) => {
      const allOn = ids.every((i) => prev.has(i));
      const n = new Set(prev);
      if (allOn) ids.forEach((i) => n.delete(i));
      else ids.forEach((i) => n.add(i));
      return n;
    });
  };

  const channelMutation = useReassignDocumentChannel();
  const retryMutation = useRetryDocument();
  const { confirm, confirmDialog } = useConfirm();

  // PayInt cannot generate or send a document yet, so the desk records a
  // person's own send — asked before they send, because that is when the
  // contact policy has to say yes.
  const markSentManually = async (d: DocRequest) => {
    const ok = await confirm({
      title: "Record a manual send?",
      description: `PayInt can't generate or send this ${DOC_TYPE_LABELS[d.docType].toLowerCase()}. Recording checks the contact policy for ${CHANNEL_LABELS[d.deliveryChannel]} to ${d.deliveryTarget || "the customer"} and logs that you are sending it yourself. Send it only once this succeeds.`,
      confirmLabel: "Record manual send",
    });
    if (!ok) return;
    try {
      await recordManualSend(d);
      toast.success(`Recorded as sent by you · ${d.customerName}`);
    } catch (e: unknown) {
      toast.error(`Not recorded — don't send it: ${apiErrorMessage(e)}`);
    } finally {
      invalidate();
    }
  };

  const bulkChannel = async (c: DocChannel) => {
    const targets = Array.from(selected)
      .map((id) => items.find((d) => d.id === id))
      .filter((d): d is DocRequest => !!d);
    try {
      await Promise.all(targets.map((doc) => channelMutation.mutateAsync({ doc, channel: c })));
      invalidate();
      toast.success(`Channel switched · ${targets.length} row${targets.length > 1 ? "s" : ""}`);
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Bulk channel update failed");
    }
  };

  const handleRetry = (d: DocRequest) => {
    retryMutation.mutate(d);
  };

  useEffect(() => {
    if (deepLinkApplied.current) return;
    if (!search.id && !search.new) return;
    deepLinkApplied.current = true;
    if (search.id) setOpenId(search.id);
    if (search.new) setShowNew(true);
    void navigate({ search: {}, replace: true });
  }, [search.id, search.new, navigate]);

  return (
    <>
      <div className="flex h-full min-h-0 flex-col gap-150 p-150">
        <header className="shrink-0 flex items-center justify-between">
          <div className="flex items-center gap-100">
            <FileText className="h-250 w-250 text-text-brand" />
            <div>
              <h1 className="heading-small font-semibold text-text leading-none">
                Document fulfilment desk
              </h1>
              <p className="text-body-small text-text-subtle">
                Bot captures requests, humans fulfil. PayInt doesn't generate or send documents yet
                — send each one yourself and record it here.
              </p>
            </div>
          </div>
          <div className="flex items-center gap-100">
            <div className="text-body-small text-text-subtlest">
              Showing {filtered.length} of {items.length}
            </div>
            <Button size="sm" className="h-400 text-body-small" onClick={() => setShowNew(true)}>
              <Plus className="mr-050 h-3.5 w-3.5" /> New request
            </Button>
          </div>
        </header>

        <MetricsStrip m={metrics} />
        <PipelineStrip counts={metrics.counts} active={filters.statuses} onToggle={toggleStatus} />
        <FiltersBar
          filters={filters}
          onPatch={patchFilters}
          onReset={() => setFilters(defaultFilters)}
          assignees={assignees}
        />

        {selected.size > 0 && (
          <BulkActionBar
            count={selected.size}
            onReassignChannel={(c) => void bulkChannel(c)}
            onClear={() => setSelected(new Set())}
          />
        )}

        <RequestsTable
          rows={filtered}
          selected={selected}
          onToggle={toggleRow}
          onToggleAll={toggleAll}
          onOpen={(d) => setOpenId(d.id)}
          onMarkSent={(d) => void markSentManually(d)}
          onRetry={handleRetry}
          isLoading={docsPending}
          isError={docsError}
          error={docsErr}
        />

        {openDoc && (
          <RequestSheet
            d={openDoc}
            onClose={() => setOpenId(null)}
            onMarkSent={(d) => void markSentManually(d)}
            onMutate={invalidate}
            assignees={assignees}
          />
        )}
        {showNew && (
          <NewRequestSheet
            onClose={() => setShowNew(false)}
            onCreated={invalidate}
            customers={customerOptions}
          />
        )}
      </div>
      {confirmDialog}
    </>
  );
}
