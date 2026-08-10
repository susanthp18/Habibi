import { useMemo, useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Upload, Download, ShieldCheck } from "lucide-react";
import { AppShell } from "@/components/shell/AppShell";
import { ConsentStatsStrip } from "@/components/consent/ConsentStatsStrip";
import { ConsentFilters } from "@/components/consent/ConsentFilters";
import { ConsentTable } from "@/components/consent/ConsentTable";
import { ConsentDrawer } from "@/components/consent/ConsentDrawer";
import {
  defaultConsentFilters,
  filterConsents,
  type ConsentFilterState,
  type ConsentRecord,
  type ChannelConsent,
  type AllowedWindow,
  type ConsentChannel,
  type OptOutSource,
} from "@/data/consent-seed";
import { Lozenge } from "@/components/ui/lozenge";
import {
  captureOptOut,
  renewConsent,
  saveConsent,
  toggleDnd,
  useConsent,
} from "@/api/consent";

export const Route = createFileRoute("/consent")({
  head: () => ({
    meta: [
      { title: "Consent & Communication Preferences — BigBound AI" },
      { name: "description", content: "BFSI-grade consent registry: per-channel opt-in/opt-out, DND windows, frequency caps, expiry tracking, and an auditable opt-out log." },
      { property: "og:title", content: "Consent & DND Registry" },
      { property: "og:description", content: "Manage per-customer channel consent, contact windows, and opt-outs with a full audit trail." },
    ],
  }),
  component: ConsentPage,
});

function ConsentPage() {
  const queryClient = useQueryClient();
  const { data: items = [] } = useConsent();
  const [filters, setFilters] = useState<ConsentFilterState>(defaultConsentFilters);
  const [openId, setOpenId] = useState<string | null>(null);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["consent"] });
  };

  const filtered = useMemo(() => filterConsents(items, filters), [items, filters]);
  // Derive the open drawer from fetched data so it stays fresh after invalidation.
  const openRecord = useMemo(() => items.find((r) => r.id === openId) ?? null, [items, openId]);

  const saveMutation = useMutation({
    mutationFn: (v: {
      rec: ConsentRecord;
      patch: { channels: ChannelConsent[]; allowedWindow: AllowedWindow };
      note: string;
    }) => saveConsent(v.rec, v.patch, v.note),
    onSuccess: () => {
      invalidate();
      toast.success("Consent preferences saved", { description: "Change captured in the audit trail." });
    },
    onError: (e: unknown) => toast.error(e instanceof Error ? e.message : "Save failed"),
  });

  const renewMutation = useMutation({
    mutationFn: (rec: ConsentRecord) => renewConsent(rec),
    onSuccess: () => {
      invalidate();
      toast.success("Consent renewed", { description: "New expiry set 12 months out." });
    },
    onError: (e: unknown) => toast.error(e instanceof Error ? e.message : "Renew failed"),
  });

  const optOutMutation = useMutation({
    mutationFn: (v: {
      rec: ConsentRecord;
      evt: { channel: ConsentChannel | "all"; source: OptOutSource; note: string };
    }) => captureOptOut(v.rec, v.evt),
    onSuccess: () => {
      invalidate();
      toast.success("Opt-out logged", { description: "Bot will honor this immediately on next contact attempt." });
    },
    onError: (e: unknown) => toast.error(e instanceof Error ? e.message : "Opt-out failed"),
  });

  const dndMutation = useMutation({
    mutationFn: (v: { rec: ConsentRecord; on: boolean }) => toggleDnd(v.rec, v.on),
    onSuccess: (_r, v) => {
      invalidate();
      toast.success(v.on ? "Marked on DND registry" : "Removed from DND registry");
    },
    onError: (e: unknown) => toast.error(e instanceof Error ? e.message : "DND update failed"),
  });

  const onSave = (id: string, p: { channels: ChannelConsent[]; allowedWindow: AllowedWindow }, note: string) => {
    const rec = items.find((r) => r.id === id);
    if (!rec) return;
    saveMutation.mutate({ rec, patch: p, note });
  };

  const onRenew = (id: string) => {
    const rec = items.find((r) => r.id === id);
    if (!rec) return;
    renewMutation.mutate(rec);
  };

  const onCaptureOptOut = (id: string, evt: { channel: ConsentChannel | "all"; source: OptOutSource; note: string }) => {
    const rec = items.find((r) => r.id === id);
    if (!rec) return;
    optOutMutation.mutate({ rec, evt });
  };

  const onToggleDnd = (id: string, on: boolean) => {
    const rec = items.find((r) => r.id === id);
    if (!rec) return;
    dndMutation.mutate({ rec, on });
  };

  const handleImport = () =>
    toast.success("Bulk import queued", { description: "Upload a CSV of {account_id, channel, status} rows. Preview will run before applying." });
  const handleExport = () =>
    toast.success(`Exporting ${filtered.length} record${filtered.length === 1 ? "" : "s"}`, {
      description: "Consent registry CSV (with opt-out log) will be ready in ~15 seconds.",
    });

  return (
    <AppShell>
      <div className="flex h-full min-h-0 flex-col">
        <header className="shrink-0 border-b border-border bg-surface px-250 py-150">
          <div className="flex flex-wrap items-center gap-100">
            <h1 className="text-[1.25rem] font-semibold text-text">Consent & communication preferences</h1>
            <Lozenge tone="neutral">
              <ShieldCheck className="h-3 w-3" /> TCPA / RBI aligned
            </Lozenge>
            <div className="ml-auto flex items-center gap-100">
              <button onClick={handleImport} className="inline-flex items-center gap-050 rounded-medium border border-border bg-surface px-150 py-075 text-body-small text-text-subtle hover:bg-surface-sunken">
                <Upload className="h-3.5 w-3.5" /> Import CSV
              </button>
              <button onClick={handleExport} className="inline-flex items-center gap-050 rounded-medium border border-border bg-surface px-150 py-075 text-body-small text-text-brand hover:bg-background-brand-subtlest">
                <Download className="h-3.5 w-3.5" /> Export registry
              </button>
            </div>
          </div>
          <p className="text-body-small text-text-subtle">
            Per-customer channel consent, DND windows, and frequency caps. Callback and Inbox screens read the same "contactable now?" status.
          </p>
        </header>

        <ConsentStatsStrip all={items} />
        <ConsentFilters filters={filters} onChange={setFilters} resultCount={filtered.length} totalCount={items.length} />

        <div className="min-h-0 flex-1 overflow-auto bg-surface p-200">
          <ConsentTable rows={filtered} onOpen={setOpenId} selectedId={openId} />
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
    </AppShell>
  );
}
