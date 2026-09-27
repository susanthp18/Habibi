import { useMemo } from "react";
import { ClipboardCheck, Clock, TrendingUp, Users, Scale, ShieldAlert } from "lucide-react";
import type { Rubric, Scorecard, CoachingAction, CalibrationSession } from "@/api/types/qa";
import type { QaCoverage } from "@/api/qa";
import { computeTotal } from "@/lib/qa";
import { MetricsStrip } from "@/components/records/MetricsStrip";

export function QaStatsStrip({
  scorecards,
  coaching,
  calibrations,
  rubricFor,
  coverage,
}: {
  scorecards: Scorecard[];
  coaching: CoachingAction[];
  calibrations: CalibrationSession[];
  /** The rubric version a card or session was scored on. */
  rubricFor: (rubricId?: string | null) => Rubric;
  coverage?: QaCoverage | null;
}) {
  const stats = useMemo(() => {
    const finals = scorecards.filter((s) => s.status === "final");
    const avg = finals.length
      ? finals.reduce((a, s) => a + computeTotal(s, rubricFor(s.rubricId)), 0) / finals.length
      : 0;
    const pending =
      coverage?.pendingReview ?? scorecards.filter((s) => s.status !== "final").length;
    const open = coaching.filter((c) => c.status !== "done").length;
    // calibration variance = avg max deviation across sessions
    const variances = calibrations
      .filter((c) => c.status === "active")
      .map((s) => {
        const rubric = rubricFor(s.rubricId);
        const targetTotal = computeTotal({ entries: s.target }, rubric);
        // A reviewer who has not scored yet has no variance to measure.
        const devs = s.reviewers
          .filter((r) => r.submitted !== false)
          .map((r) => Math.abs(computeTotal({ entries: r.entries }, rubric) - targetTotal));
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
      criticalFails: coverage?.criticalFails,
      windowDays: coverage?.windowDays ?? 7,
    };
  }, [scorecards, coaching, calibrations, rubricFor, coverage]);

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
          sub: "Published scorecards in the queue",
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
          icon: ShieldAlert,
          label: `Critical fails (${stats.windowDays}d)`,
          value: stats.criticalFails ?? "—",
          sub: "Critical criteria scored 0",
          tone: stats.criticalFails ? "danger" : "neutral",
        },
        {
          variant: "card",
          icon: Users,
          label: "Coaching open",
          value: stats.open,
          sub: "Assigned + in progress",
        },
        {
          variant: "card",
          icon: Scale,
          label: "Calibration variance",
          value: `±${stats.variance.toFixed(1)}`,
          sub: "Reviewer vs target",
          tone: stats.variance > 8 ? "danger" : "success",
        },
      ]}
    />
  );
}
