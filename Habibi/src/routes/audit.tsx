import { useMemo, useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { toast } from "sonner";
import { Lock } from "lucide-react";
import { AppShell } from "@/components/shell/AppShell";
import { AuditFilters } from "@/components/audit/AuditFilters";
import { CallsTable } from "@/components/audit/CallsTable";
import { CallDetailDrawer } from "@/components/audit/CallDetailDrawer";
import { defaultFilters, filterCalls, type AuditFilterState } from "@/data/audit-seed";
import { useCalls } from "@/api/audit";

export const Route = createFileRoute("/audit")({
  head: () => ({
    meta: [
      { title: "Audit Trail — BigBound AI" },
      {
        name: "description",
        content: "Searchable, immutable log of every historical customer interaction with synced audio, transcript, sentiment timeline, and disclosure checklist.",
      },
      { property: "og:title", content: "Audit Trail (Call History)" },
      {
        property: "og:description",
        content: "Filter, review, and export any past call — audio synced to transcript, sentiment charted, compliance disclosures verified.",
      },
    ],
  }),
  component: AuditPage,
});

function AuditPage() {
  const [filters, setFilters] = useState<AuditFilterState>(defaultFilters);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [openId, setOpenId] = useState<string | null>(null);

  const { data: calls = [] } = useCalls();

  const rows = useMemo(() => filterCalls(calls, filters), [calls, filters]);
  const openCall = useMemo(() => rows.find((r) => r.id === openId) ?? calls.find((c) => c.id === openId) ?? null, [calls, openId, rows]);

  const toggle = (id: string) =>
    setSelected((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const toggleAll = (all: boolean) => {
    if (all) setSelected(new Set(rows.map((r) => r.id)));
    else setSelected(new Set());
  };

  const handleExport = () => {
    const count = selected.size || rows.length;
    toast.success(`Exporting ${count} call${count === 1 ? "" : "s"}`, {
      description: "PII redaction applied. A watermarked ZIP will be ready in ~30 seconds.",
    });
  };

  return (
    <AppShell>
      <div className="flex h-full min-h-0 flex-col">
        <header className="shrink-0 border-b border-[var(--border-token)] bg-surface-card px-5 py-3">
          <div className="flex items-center gap-2">
            <h1 className="text-[18px] font-semibold text-brand-navy">Audit Trail</h1>
            <span className="inline-flex items-center gap-1 rounded-full bg-surface-sunken px-2 py-0.5 text-[11px] font-medium text-text-secondary">
              <Lock className="h-3 w-3" /> Immutable log
            </span>
          </div>
          <p className="text-[12px] text-text-secondary">
            Every historical interaction — bot and human — searchable with audio, transcript, and compliance evidence.
          </p>
        </header>

        <AuditFilters
          filters={filters}
          onChange={setFilters}
          resultCount={rows.length}
          selectedCount={selected.size}
          onExport={handleExport}
        />

        <CallsTable
          rows={rows}
          selected={selected}
          onToggle={toggle}
          onToggleAll={toggleAll}
          openId={openId}
          onOpen={setOpenId}
        />
      </div>

      <CallDetailDrawer call={openCall} onClose={() => setOpenId(null)} />
    </AppShell>
  );
}
