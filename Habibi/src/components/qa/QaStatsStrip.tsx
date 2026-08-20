import { useMemo } from "react";
import { ClipboardCheck, Clock, TrendingUp, Users, Scale } from "lucide-react";
import { computeTotal, type Rubric, type Scorecard, type CoachingAction, type CalibrationSession } from "@/data/qa-seed";
import { Lozenge } from "@/components/ui/lozenge";

function Tile({ icon: Icon, label, value, hint, tone, seed }: { icon: any; label: string; value: string; hint?: string; tone?: string; seed?: boolean }) {
  return (
    <div className="flex-1 min-w-[10rem] rounded-large border border-border bg-surface px-150 py-150">
      <div className="flex items-center gap-075 text-body-small font-medium text-text-subtlest">
        <Icon className="h-3.5 w-3.5" /> {label}
        {seed && (
          <Lozenge
            title="Seed data — coaching/calibration not yet wired to the live backend" tone="neutral" className="ml-auto tracking-normal">
            seed
          </Lozenge>
        )}
      </div>
      <div className={`mt-025 text-[1.25rem] font-semibold ${tone ?? "text-text"}`}>{value}</div>
      {hint && <div className="text-body-small text-text-subtlest">{hint}</div>}
    </div>
  );
}

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
  coverage?: { coverage: number | null; scored: number; completed: number; pendingReview: number } | null;
}) {
  const stats = useMemo(() => {
    const finals = scorecards.filter((s) => s.status === "final");
    const avg = finals.length
      ? finals.reduce((a, s) => a + computeTotal(s, rubric), 0) / finals.length
      : 0;
    const pending = coverage?.pendingReview ?? scorecards.filter((s) => s.status !== "final").length;
    const open = coaching.filter((c) => c.status !== "done").length;
    // calibration variance = avg max deviation across sessions
    const variances = calibrations
      .filter((c) => c.status === "active")
      .map((s) => {
        const targetTotal = computeTotal({ entries: s.target } as any, rubric);
        const devs = s.reviewers.map((r) => Math.abs(computeTotal({ entries: r.entries } as any, rubric) - targetTotal));
        return Math.max(0, ...devs);
      });
    const variance = variances.length ? variances.reduce((a, b) => a + b, 0) / variances.length : 0;
    const covPct = coverage?.coverage != null ? `${Math.round(coverage.coverage * 100)}%` : "—";
    return { avg, scored: coverage?.scored ?? finals.length, pending, open, variance, covPct, completed: coverage?.completed };
  }, [scorecards, coaching, calibrations, rubric, coverage]);

  return (
    <div className="shrink-0 border-b border-border bg-surface px-250 py-150">
      <div className="flex flex-wrap gap-100">
        <Tile icon={ClipboardCheck} label="Coverage (7d)" value={stats.covPct} hint={stats.completed != null ? `${stats.scored}/${stats.completed} scored` : "Scorecards / completed"} tone="text-text-brand" />
        <Tile icon={TrendingUp} label="Avg score" value={`${stats.avg.toFixed(1)}`} hint="Weighted, last 30 days" />
        <Tile icon={Clock} label="Pending review" value={String(stats.pending)} hint="AI draft needing a human" tone={stats.pending > 10 ? "text-text-warning" : undefined} />
        <Tile icon={Users} label="Coaching open" value={String(stats.open)} hint="Assigned + in progress" seed />
        <Tile icon={Scale} label="Calibration variance" value={`±${stats.variance.toFixed(1)}`} hint="Reviewer vs target" tone={stats.variance > 8 ? "text-text-danger" : "text-text-success-bolder"} seed />
      </div>
    </div>
  );
}
