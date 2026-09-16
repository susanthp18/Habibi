import { Lozenge } from "@/components/ui/lozenge";
import { gateTone } from "@/lib/gate-status";
import { useEvalReports, type EvalReport } from "@/api/agent-studio";

export function EvalCockpit() {
  const reports = useEvalReports();
  const rows = reports.data ?? [];

  return (
    <div className="space-y-150">
      <p className="text-body-small text-text-subtle">
        History of regression, red-team, capability and twin runs. Red-team is never skipped.
      </p>
      <ul className="divide-y divide-border rounded-medium border border-border">
        {reports.isError ? (
          // "No reports" is a fact about the suite; "we could not read the
          // reports" is a fact about the network. Its sibling on the Evals tab
          // has said so for a while — this one still asserted the first when it
          // meant the second, on the panel an operator checks before shipping.
          <li className="px-150 py-100 text-body-small text-text-danger">
            The eval history could not be read. This is not "no runs" — retry before reading
            anything into an empty list.
          </li>
        ) : reports.isPending ? (
          <li className="px-150 py-100 text-body-small text-text-subtlest">Loading…</li>
        ) : rows.length === 0 ? (
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
        <Lozenge tone={gateTone(report.status)}>{report.status}</Lozenge>
      </div>
    </li>
  );
}
