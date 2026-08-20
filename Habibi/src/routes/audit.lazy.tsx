import { useEffect, useMemo, useState } from "react";
import { createLazyFileRoute } from "@tanstack/react-router";
import { toast } from "sonner";
import { Lock } from "lucide-react";
import { AppShell } from "@/components/shell/AppShell";
import { AuditFilters } from "@/components/audit/AuditFilters";
import { CallsTable } from "@/components/audit/CallsTable";
import { CallDetailDrawer } from "@/components/audit/CallDetailDrawer";
import { defaultFilters, filterCalls, type AuditFilterState } from "@/data/audit-seed";
import { useCalls } from "@/api/audit";
import { Lozenge } from "@/components/ui/lozenge";
import { LoadingState } from "@/components/ui/loading-state";

export const Route = createLazyFileRoute("/audit")({
  component: AuditPage,
});

function AuditPage() {
  const { id } = Route.useSearch();
  const [filters, setFilters] = useState<AuditFilterState>(defaultFilters);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [openId, setOpenId] = useState<string | null>(id ?? null);

  const { data: calls = [], isLoading, isError, error, refetch } = useCalls();

  useEffect(() => {
    if (id) setOpenId(id);
  }, [id]);

  const rows = useMemo(() => filterCalls(calls, filters), [calls, filters]);
  const openCall = useMemo(() => rows.find((r) => r.id === openId) ?? calls.find((c) => c.id === openId) ?? null, [calls, openId, rows]);

  const handleExport = () => {
    const count = selected.size || rows.length;
    toast.success(`Exporting ${count} call${count === 1 ? "" : "s"}`, {
      description: "PII redaction applied. A watermarked ZIP will be ready in ~30 seconds.",
    });
  };

  return (
    <AppShell>
      <div className="flex h-full min-h-0 flex-col">
        <header className="shrink-0 border-b border-border bg-surface px-250 py-150">
          <div className="flex items-center gap-100">
            <h1 className="text-[1.25rem] font-semibold text-text">Audit trail</h1>
            <Lozenge tone="neutral">
              <Lock className="h-3 w-3" /> Immutable log
            </Lozenge>
          </div>
          <p className="text-body-small text-text-subtle">
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

        {isLoading && calls.length === 0 ? (
          <div className="flex flex-1 items-center justify-center">
            <LoadingState label="Loading calls" />
          </div>
        ) : isError && calls.length === 0 ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-100 text-body text-text-subtle">
            <p>Couldn’t load audit calls.</p>
            <p className="text-body-small text-text-danger">
              {error instanceof Error ? error.message : "Unknown error"}
            </p>
            <button
              type="button"
              className="rounded-medium bg-background-brand-bold px-150 py-075 text-body-small font-medium text-white"
              onClick={() => void refetch()}
            >
              Retry
            </button>
          </div>
        ) : (
          <div className="min-h-0 flex-1 overflow-hidden p-150">
            <CallsTable
              rows={rows}
              selected={selected}
              onSelectedChange={setSelected}
              openId={openId}
              onOpen={setOpenId}
            />
          </div>
        )}
      </div>

      <CallDetailDrawer call={openCall} onClose={() => setOpenId(null)} />
    </AppShell>
  );
}
