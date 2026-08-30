import { Lozenge } from "@/components/ui/lozenge";
import { Button } from "@/components/ui/button";
import { USE_MOCK } from "@/api/config";
import { useEvalReports, useRunEvalSchedule, type EvalReport } from "@/api/agent-studio";

export function EvalCockpit({ compact = false }: { compact?: boolean }) {
  const reports = useEvalReports();
  const schedule = useRunEvalSchedule();
  const rows = reports.data ?? [];

  return (
    <div className="space-y-150">
      <div className="flex items-start justify-between gap-100">
        <p className="text-body-small text-text-subtle">
          History of regression, red-team, capability and twin runs. Red-team is never skipped.
        </p>
        {!compact && !USE_MOCK ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={schedule.isPending}
            onClick={() => void schedule.mutateAsync()}
          >
            {schedule.isPending ? "Running…" : "Run continuous suite"}
          </Button>
        ) : null}
      </div>
      {schedule.data ? (
        <div className="text-body-small text-text-subtle">
          Last schedule: {schedule.data.status} · {schedule.data.ran - schedule.data.failed}/
          {schedule.data.ran} suites
        </div>
      ) : null}
      <ul className="divide-y divide-border rounded-medium border border-border">
        {rows.length === 0 ? (
          <li className="px-150 py-100 text-body-small text-text-subtlest">No eval reports yet.</li>
        ) : (
          rows.map((r) => <ReportRow key={r.id} report={r} />)
        )}
      </ul>
    </div>
  );
}

function ReportRow({ report }: { report: EvalReport }) {
  const failed = report.summary?.failed ?? 0;
  const total = report.summary?.total ?? 0;
  return (
    <li className="flex items-center justify-between gap-100 px-150 py-100">
      <div className="min-w-0">
        <div className="truncate text-body-small font-medium text-text">
          {report.suiteName || report.suiteId}
        </div>
        <div className="text-body-tiny text-text-subtle">
          {report.kind} · {report.origin || "manual"}
          {report.createdAt ? ` · ${report.createdAt.slice(0, 16).replace("T", " ")}` : ""}
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-075">
        <span className="tabular text-body-tiny text-text-subtle">
          {total - failed}/{total}
        </span>
        <Lozenge tone={report.status === "pass" ? "success" : "danger"}>{report.status}</Lozenge>
      </div>
    </li>
  );
}
