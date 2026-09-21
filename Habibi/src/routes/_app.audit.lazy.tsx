import { useEffect, useMemo, useState } from "react";
import { createLazyFileRoute } from "@tanstack/react-router";
import { toast } from "sonner";
import { Lock } from "lucide-react";
import { AuditFilters } from "@/components/audit/AuditFilters";
import { CallsTable } from "@/components/audit/CallsTable";
import { CallDetailDrawer } from "@/components/audit/CallDetailDrawer";
import type { AuditFilterState } from "@/api/types/audit";
import { defaultFilters, filterCalls } from "@/lib/audit";
import { useCalls } from "@/api/audit";
import { createExportJob, fetchRedactionRecords } from "@/api/redaction";
import { planAuditExport } from "@/lib/audit-export";
import { mutationErrorMessage } from "@/lib/mutation-errors";
import { Lozenge } from "@/components/ui/lozenge";
import { LoadingState } from "@/components/ui/loading-state";
import { QueryErrorBanner } from "@/components/ui/query-state";

export const Route = createLazyFileRoute("/_app/audit")({
  component: AuditPage,
});

function AuditPage() {
  const { id } = Route.useSearch();
  const [filters, setFilters] = useState<AuditFilterState>(defaultFilters);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [openId, setOpenId] = useState<string | null>(id ?? null);

  const { data: calls = [], isLoading, isError, error } = useCalls();

  useEffect(() => {
    if (id) setOpenId(id);
  }, [id]);

  const rows = useMemo(() => filterCalls(calls, filters), [calls, filters]);
  const openCall = useMemo(
    () => rows.find((r) => r.id === openId) ?? calls.find((c) => c.id === openId) ?? null,
    [calls, openId, rows],
  );

  const handleExport = () => {
    const ids = selected.size > 0 ? Array.from(selected) : rows.map((r) => r.id);
    if (ids.length === 0) {
      toast.error("Nothing to export");
      return;
    }
    void fetchRedactionRecords()
      .then((records) => {
        const plan = planAuditExport(ids, records);
        if (!plan.ok) {
          toast.error("No redaction record for some calls", {
            description: `${plan.missingCallIds.join(", ")} — open Redaction to create them.`,
            action: {
              label: "Redaction",
              onClick: () => {
                window.location.assign("/redaction");
              },
            },
          });
          return;
        }
        return createExportJob({
          recordIds: plan.recordIds,
          format: "pdf",
          scope: ["transcript", "audio", "metadata"],
          watermark: "AUDIT TRAIL",
          actorRole: "Compliance Officer",
        }).then((job) => {
          toast.success(`${job.id} queued`, {
            description: `${plan.recordIds.length} redacted record(s)`,
          });
        });
      })
      .catch((err: unknown) => toast.error(mutationErrorMessage(err)));
  };

  return (
    <>
      <div className="flex h-full min-h-0 flex-col">
        <header className="shrink-0 border-b border-border bg-surface px-250 py-150">
          <div className="flex items-center gap-100">
            <h1 className="heading-medium font-semibold text-text">Audit trail</h1>
            <Lozenge tone="neutral">
              <Lock className="h-3 w-3" /> Immutable log
            </Lozenge>
          </div>
          <p className="text-body-small text-text-subtle">
            Every historical interaction — bot and human — searchable with audio, transcript, and
            compliance evidence.
          </p>
        </header>

        <AuditFilters
          calls={calls}
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
          <div className="flex flex-1 items-center justify-center p-400">
            <QueryErrorBanner label="audit calls" error={error} />
          </div>
        ) : (
          <div className="min-h-0 flex-1 overflow-hidden p-150">
            <CallsTable
              rows={rows}
              selected={selected}
              onSelectedChange={setSelected}
              openId={openId}
              onOpen={setOpenId}
              isLoading={isLoading}
              isError={isError}
              error={error}
            />
          </div>
        )}
      </div>

      <CallDetailDrawer call={openCall} onClose={() => setOpenId(null)} />
    </>
  );
}
