import { useMemo } from "react";
import { ClipboardCheck, Clock, TrendingUp, Users, Scale } from "lucide-react";
import { computeTotal, defaultRubric, type Scorecard, type CoachingAction, type CalibrationSession } from "@/data/qa-seed";

function Tile({ icon: Icon, label, value, hint, tone }: { icon: any; label: string; value: string; hint?: string; tone?: string }) {
  return (
    <div className="flex-1 min-w-[160px] rounded-lg border border-[var(--border-token)] bg-surface-card px-3 py-2.5">
      <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-text-muted">
        <Icon className="h-3.5 w-3.5" /> {label}
      </div>
      <div className={`mt-0.5 text-[20px] font-semibold ${tone ?? "text-brand-navy"}`}>{value}</div>
      {hint && <div className="text-[11px] text-text-muted">{hint}</div>}
    </div>
  );
}

export function QaStatsStrip({
  scorecards,
  coaching,
  calibrations,
}: {
  scorecards: Scorecard[];
  coaching: CoachingAction[];
  calibrations: CalibrationSession[];
}) {
  const stats = useMemo(() => {
    const finals = scorecards.filter((s) => s.status === "final");
    const avg = finals.length
      ? finals.reduce((a, s) => a + computeTotal(s, defaultRubric), 0) / finals.length
      : 0;
    const pending = scorecards.filter((s) => s.status !== "final").length;
    const open = coaching.filter((c) => c.status !== "done").length;
    // calibration variance = avg max deviation across sessions
    const variances = calibrations
      .filter((c) => c.status === "active")
      .map((s) => {
        const targetTotal = computeTotal({ entries: s.target } as any, defaultRubric);
        const devs = s.reviewers.map((r) => Math.abs(computeTotal({ entries: r.entries } as any, defaultRubric) - targetTotal));
        return Math.max(0, ...devs);
      });
    const variance = variances.length ? variances.reduce((a, b) => a + b, 0) / variances.length : 0;
    return { avg, scored: finals.length, pending, open, variance };
  }, [scorecards, coaching, calibrations]);

  return (
    <div className="shrink-0 border-b border-[var(--border-token)] bg-surface-app px-5 py-3">
      <div className="flex flex-wrap gap-2">
        <Tile icon={TrendingUp} label="Avg score" value={`${stats.avg.toFixed(1)}`} hint="Weighted, last 30 days" tone="text-brand-primary-dark" />
        <Tile icon={ClipboardCheck} label="Scored (7d)" value={String(stats.scored)} hint="Human-finalised" />
        <Tile icon={Clock} label="Pending review" value={String(stats.pending)} hint="AI draft + unscored" tone={stats.pending > 10 ? "text-amber-600" : undefined} />
        <Tile icon={Users} label="Coaching open" value={String(stats.open)} hint="Assigned + in progress" />
        <Tile icon={Scale} label="Calibration variance" value={`±${stats.variance.toFixed(1)}`} hint="Reviewer vs target" tone={stats.variance > 8 ? "text-red-600" : "text-emerald-700"} />
      </div>
    </div>
  );
}
