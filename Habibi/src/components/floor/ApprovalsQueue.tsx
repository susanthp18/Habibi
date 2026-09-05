import { toast } from "sonner";
import { useQueryClient } from "@tanstack/react-query";
import { signalFloorApproval, useFloorApprovals } from "@/api/floor";
import { QueryErrorBanner } from "@/components/ui/query-state";

export function ApprovalsQueue() {
  const { data, isError, error, isPending } = useFloorApprovals();
  const qc = useQueryClient();
  if (isError) {
    return (
      <div className="border-b border-border bg-background-danger-subtlest px-200 py-100">
        <QueryErrorBanner label="pending approvals" error={error} />
      </div>
    );
  }
  if (isPending && !data) return null;
  const jobs = data ?? [];
  if (jobs.length === 0) return null;

  const signal = async (id: string, name: "approve" | "reject") => {
    try {
      await signalFloorApproval(id, name);
      toast.success(name === "approve" ? "Approved — clerk will resume" : "Rejected");
      void qc.invalidateQueries({ queryKey: ["floor-approvals"] });
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Signal failed");
    }
  };

  return (
    <div className="border-b border-border bg-background-warning-subtlest px-200 py-100">
      <p className="mb-075 text-body-small font-semibold text-text">Pending approvals</p>
      <ul className="space-y-050">
        {jobs.map((job) => (
          <li key={job.id} className="flex items-center justify-between gap-100 text-body-small">
            <span className="min-w-0 truncate text-text">
              {job.workflowType.replace(/_/g, " ")}
              {job.inputRequiredReason ? ` · ${job.inputRequiredReason.replace(/_/g, " ")}` : ""}
            </span>
            <span className="flex shrink-0 gap-050">
              <button
                type="button"
                className="rounded px-075 py-025 font-medium text-text-brand"
                onClick={() => void signal(job.id, "approve")}
              >
                Approve
              </button>
              <button
                type="button"
                className="rounded px-075 py-025 text-text-subtle"
                onClick={() => void signal(job.id, "reject")}
              >
                Reject
              </button>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
