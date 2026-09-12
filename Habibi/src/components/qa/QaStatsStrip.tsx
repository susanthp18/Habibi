import { useMemo } from "react";
import { ClipboardCheck, Clock, TrendingUp, Users, Scale } from "lucide-react";
import type { Rubric, Scorecard, CoachingAction, CalibrationSession } from "@/api/types/qa";
import { computeTotal } from "@/lib/qa";
import { Lozenge } from "@/components/ui/lozenge";
import { MetricsStrip } from "@/components/records/MetricsStrip";

const SEED = (
  <Lozenge
    title="Seed data — coaching/calibration not yet wired to the live backend"
    tone="neutral"
    className="ml-auto tracking-normal"
  >
    seed
  </Lozenge>
);

export function QaStatsStrip({
  scorecards,
  coaching,
  calibrations,
  rubric,
  coverage,
}: {
  scorecards: Scorecard[];
  coaching: CoachingAction[];
  calibrations: CalibrationSession[];
  rubric: Rubric;
  coverage?: {
    coverage: number | null;
    scored: number;
    completed: number;
    pendingReview: number;
  } | null;
}) {
  const stats = useMemo(() => {
    const finals = scorecards.filter((s) => s.status === "final");
    const avg = finals.length
      ? finals.reduce((a, s) => a + computeTotal(s, rubric), 0) / finals.length
      : 0;
    const pending =
      coverage?.pendingReview ?? scorecards.filter((s) => s.status !== "final").length;
    const open = coaching.filter((c) => c.status !== "done").length;
    // calibration variance = avg max deviation across sessions
    const variances = calibrations
      .filter((c) => c.status === "active")
      .map((s) => {
        const targetTotal = computeTotal({ entries: s.target }, rubric);
        const devs = s.reviewers.map((r) =>
          Math.abs(computeTotal({ entries: r.entries }, rubric) - targetTotal),
        );
        return Math.max(0, ...devs);
      });
    const variance = variances.length ? variances.reduce((a, b) => a + b, 0) / variances.length : 0;
    const covPct = coverage?.coverage != null ? `${Math.round(coverage.coverage * 100)}%` : "—";
    return {
      avg,
      scored: coverage?.scored ?? finals.length,
      pending,
      open,
      variance,
      covPct,
      completed: coverage?.completed,
    };
  }, [scorecards, coaching, calibrations, rubric, coverage]);

  return (
    <MetricsStrip
      className="border-b border-border bg-surface px-250 py-150"
      tiles={[
        {
          variant: "card",
          icon: ClipboardCheck,
          label: "Coverage (7d)",
          value: stats.covPct,
          sub:
            stats.completed != null
              ? `${stats.scored}/${stats.completed} scored`
              : "Scorecards / completed",
          tone: "brand",
        },
        {
          variant: "card",
          icon: TrendingUp,
          label: "Avg score",
          value: stats.avg.toFixed(1),
          sub: "Weighted, last 30 days",
        },
        {
          variant: "card",
          icon: Clock,
          label: "Pending review",
          value: stats.pending,
          sub: "AI draft needing a human",
          tone: stats.pending > 10 ? "warning" : "neutral",
        },
        {
          variant: "card",
          icon: Users,
          label: "Coaching open",
          value: stats.open,
          sub: "Assigned + in progress",
          badge: SEED,
        },
        {
          variant: "card",
          icon: Scale,
          label: "Calibration variance",
          value: `±${stats.variance.toFixed(1)}`,
          sub: "Reviewer vs target",
          tone: stats.variance > 8 ? "danger" : "success",
          badge: SEED,
        },
      ]}
    />
  );
}
