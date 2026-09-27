import { useEffect, useMemo, useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { Upload, Download, ShieldCheck } from "lucide-react";
import { ConsentStatsStrip } from "@/components/consent/ConsentStatsStrip";
import { ConsentFilters } from "@/components/consent/ConsentFilters";
import { ConsentTable } from "@/components/consent/ConsentTable";
import { ConsentDrawer } from "@/components/consent/ConsentDrawer";
import { ConsentImportDialog } from "@/components/consent/ConsentImportDialog";
import { can, useMe } from "@/api/me";
import type {
  ConsentFilterState,
  ConsentRecord,
  ConsentChannel,
  ConsentPreferencesPatch,
  OptOutSource,
} from "@/api/types/consent";
import { defaultConsentFilters } from "@/lib/consent";
import { Lozenge } from "@/components/ui/lozenge";
import {
  useConsent,
  useConsentStats,
  useSaveConsent,
  useRenewConsent,
  useCaptureOptOut,
  useToggleDnd,
  useExportConsentRegistry,
} from "@/api/consent";

const EMPTY_CONSENT: ConsentRecord[] = [];

export const Route = createFileRoute("/_app/consent")({
  head: () => ({
    meta: [
      { title: "Consent & Communication Preferences — PayInt" },
      {
        name: "description",
        content:
          "BFSI-grade consent registry: per-channel opt-in/opt-out, DND windows, frequency caps, expiry tracking, and an auditable opt-out log.",
      },
      { property: "og:title", content: "Consent & DND Registry" },
      {
        property: "og:description",
        content:
          "Manage per-customer channel consent, contact windows, and opt-outs with a full audit trail.",
      },
    ],
  }),
  component: ConsentPage,
});

function ConsentPage() {
  const [filters, setFilters] = useState<ConsentFilterState>(defaultConsentFilters);
  // The server filters; search waits for the typing to pause.
  const [applied, setApplied] = useState<ConsentFilterState>(defaultConsentFilters);
  useEffect(() => {
    const t = setTimeout(() => setApplied(filters), filters.q === applied.q ? 0 : 300);
    return () => clearTimeout(t);
  }, [filters, applied.q]);
  const { data, isPending, isError, error, hasNextPage, fetchNextPage, isFetchingNextPage } =
    useConsent(applied);
  const items = useMemo(() => data?.pages.flat() ?? EMPTY_CONSENT, [data]);
  const { data: stats } = useConsentStats();
  const [openId, setOpenId] = useState<string | null>(null);

  // Derive the open drawer from fetched data so it stays fresh after invalidation.
  const openRecord = useMemo(() => items.find((r) => r.id === openId) ?? null, [items, openId]);

  const saveMutation = useSaveConsent();
  const renewMutation = useRenewConsent();
  const optOutMutation = useCaptureOptOut();
  const dndMutation = useToggleDnd();

  const onSave = (id: string, p: ConsentPreferencesPatch, note: string) => {
    const rec = items.find((r) => r.id === id);
    if (!rec) return;
    saveMutation.mutate({ rec, patch: p, note });
  };

  const onRenew = (id: string) => {
    const rec = items.find((r) => r.id === id);
    if (!rec) return;
    renewMutation.mutate(rec);
  };

  const onCaptureOptOut = (
    id: string,
    evt: { channel: ConsentChannel | "all"; source: OptOutSource; note: string },
  ) => {
    const rec = items.find((r) => r.id === id);
    if (!rec) return;
    optOutMutation.mutate({ rec, evt });
  };

  const onToggleDnd = (id: string, on: boolean) => {
    const rec = items.find((r) => r.id === id);
    if (!rec) return;
    dndMutation.mutate({ rec, on });
  };

  const [importOpen, setImportOpen] = useState(false);
  const exportMutation = useExportConsentRegistry();
  const { data: me } = useMe();
  // Disabled only once `me` says no: the routes answer 403 either way.
  const canImport = !me || can(me, "perm-consent-write");
  const canExport = !me || can(me, "perm-compliance-read");

  return (
    <>
      <div className="flex h-full min-h-0 flex-col">
        <header className="shrink-0 border-b border-border bg-surface px-250 py-150">
          <div className="flex flex-wrap items-center gap-100">
            <h1 className="heading-medium font-semibold text-text">
              Consent & communication preferences
            </h1>
            <Lozenge tone="neutral">
              <ShieldCheck className="h-3 w-3" /> TCPA / RBI aligned
            </Lozenge>
            <div className="ml-auto flex items-center gap-100">
              <button
                onClick={() => setImportOpen(true)}
                disabled={!canImport}
                title={canImport ? undefined : "Needs the consent write permission"}
                className="inline-flex items-center gap-050 rounded-medium border border-border bg-surface px-150 py-075 text-body-small text-text-subtle hover:bg-surface-sunken disabled:cursor-not-allowed disabled:opacity-50"
              >
                <Upload className="h-3.5 w-3.5" /> Import CSV
              </button>
              <button
                onClick={() => exportMutation.mutate()}
                disabled={!canExport || exportMutation.isPending}
                title={
                  canExport
                    ? "Every customer in the registry, not only those loaded here"
                    : "Needs the compliance read permission"
                }
                className="inline-flex items-center gap-050 rounded-medium border border-border bg-surface px-150 py-075 text-body-small text-text-brand hover:bg-background-brand-subtlest disabled:cursor-not-allowed disabled:opacity-50"
              >
                <Download className="h-3.5 w-3.5" />{" "}
                {exportMutation.isPending ? "Exporting…" : "Export registry"}
              </button>
            </div>
          </div>
          <p className="text-body-small text-text-subtle">
            Per-customer channel consent, DND windows, and frequency caps. Callback and Inbox
            screens read the same "contactable now?" status.
          </p>
        </header>

        {!isError ? <ConsentStatsStrip stats={stats} /> : null}
        {!isError ? (
          <ConsentFilters
            filters={filters}
            onChange={setFilters}
            resultCount={items.length}
            totalCount={stats?.customers ?? items.length}
            more={!!hasNextPage}
          />
        ) : null}

        <div className="min-h-0 flex-1 overflow-auto bg-surface p-200">
          <ConsentTable
            rows={items}
            onOpen={setOpenId}
            selectedId={openId}
            isLoading={isPending}
            isError={isError}
            error={error}
          />
          {hasNextPage ? (
            <div className="flex justify-center pt-150">
              <button
                onClick={() => void fetchNextPage()}
                disabled={isFetchingNextPage}
                className="rounded-medium border border-border bg-surface px-150 py-075 text-body-small text-text-subtle hover:bg-surface-sunken disabled:opacity-50"
              >
                {isFetchingNextPage ? "Loading…" : "Load more"}
              </button>
            </div>
          ) : null}
        </div>
      </div>

      <ConsentDrawer
        record={openRecord}
        onClose={() => setOpenId(null)}
        onSave={onSave}
        onRenew={onRenew}
        onCaptureOptOut={onCaptureOptOut}
        onToggleDnd={onToggleDnd}
      />
      <ConsentImportDialog open={importOpen} onOpenChange={setImportOpen} />
    </>
  );
}
