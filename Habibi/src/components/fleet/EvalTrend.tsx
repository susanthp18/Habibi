import { type EvalReport } from "@/api/agent-studio";
import { Lozenge } from "@/components/ui/lozenge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * The last few eval runs for one card, newest on the right.
 *
 * "evals: pass" is one bit about one run and says nothing about whether the
 * card has been getting better or worse. The reports are fetched once for the
 * whole fleet and grouped here rather than queried per card — seven cards would
 * otherwise mean seven requests for data one call already returns.
 */
export function EvalTrend({ reports, failed }: { reports: EvalReport[]; failed?: boolean }) {
  // A failed read is not "no runs". Say so where the dots would have been.
  if (failed) {
    return (
      <Lozenge
        tone="warning"
        title="The eval history could not be loaded. This is a failed read, not a card with no runs."
      >
        evals unavailable
      </Lozenge>
    );
  }
  if (reports.length === 0) return null;
  // Newest last, so the row reads left-to-right like a timeline.
  const recent = reports.slice(0, 3).reverse();
  return (
    <span className="inline-flex items-center gap-050" aria-label="Recent eval runs">
      {recent.map((r) => (
        <span
          key={r.id}
          title={`${r.suiteName ?? r.suiteId} — ${r.status}${
            r.createdAt ? ` · ${new Date(r.createdAt).toLocaleDateString()}` : ""
          }`}
          className={cn(
            "h-2 w-2 rounded-full",
            r.status === "pass"
              ? "bg-background-success-bold"
              : r.status === "fail"
                ? "bg-background-danger-bold"
                : "bg-border",
          )}
        />
      ))}
    </span>
  );
}
