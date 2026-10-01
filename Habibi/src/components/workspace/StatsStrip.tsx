import { ArrowDownRight, ArrowUpRight, Clock, HandCoins, PhoneCall } from "lucide-react";
import { useWorkspaceSummary } from "@/api/workspace";
import { MetricsStrip } from "@/components/records/MetricsStrip";
import { fmtDate, inr } from "@/lib/format";

function duration(sec: number) {
  const s = Math.max(0, Math.round(sec));
  return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`;
}

/** A comparison, not a verdict: more calls or a longer handle time is not
 *  good or bad on its own, so the chip is neutral and only the arrow moves. */
function comparison(diff: number, text: string) {
  const Arrow = diff > 0 ? ArrowUpRight : diff < 0 ? ArrowDownRight : null;
  return (
    <span className="inline-flex items-center gap-050 text-body-small text-text-subtle">
      {Arrow ? <Arrow className="h-3.5 w-3.5" aria-hidden /> : null}
      {text}
    </span>
  );
}

/** The operator's own completed voice calls over the last seven days, ending
 *  now. Personal whatever the queue scope; team analytics live on Dashboard. */
export function StatsStrip() {
  const { data, isPending, isError, refetch } = useWorkspaceSummary("me");
  const stats = data?.stats;

  if (isError && !stats) {
    return (
      <div className="rounded-large border border-border bg-surface px-200 py-150 text-body-small text-text-danger">
        Couldn’t load your stats.{" "}
        <button type="button" onClick={() => void refetch()} className="font-medium underline">
          Retry
        </button>
      </div>
    );
  }

  const callsDiff = stats ? stats.callsHandled - stats.callsHandledPrior : 0;
  const ahtDiff = stats ? stats.ahtSec - stats.teamAhtSec : 0;
  const rate = stats?.callsHandled
    ? `${Math.round((100 * stats.resolutions) / stats.callsHandled)}% resolved`
    : "No calls to resolve";

  return (
    <div>
      <div className="mb-100 text-body-small text-text-subtlest">
        {stats
          ? `Your calls · ${fmtDate(stats.windowStart, { day: "numeric", month: "short" })} – ${fmtDate(stats.windowEnd, { day: "numeric", month: "short" })}`
          : isPending
            ? "Loading your stats…"
            : null}
      </div>
      <MetricsStrip
        className="gap-150 md:grid-cols-3 xl:grid-cols-3"
        tiles={[
          {
            variant: "card",
            label: "Calls you handled",
            value: stats ? stats.callsHandled : "—",
            icon: PhoneCall,
            sub: stats ? rate : undefined,
            footer: stats
              ? comparison(
                  callsDiff,
                  callsDiff === 0
                    ? "Same as the week before"
                    : `${Math.abs(callsDiff)} ${callsDiff > 0 ? "more" : "fewer"} than the week before`,
                )
              : undefined,
          },
          {
            variant: "card",
            label: "Avg handle time",
            value: stats?.callsHandled ? duration(stats.ahtSec) : "—",
            icon: Clock,
            footer:
              stats?.callsHandled && stats.teamAhtSec
                ? comparison(
                    ahtDiff,
                    ahtDiff === 0
                      ? `Same as the team (${duration(stats.teamAhtSec)})`
                      : `${Math.abs(ahtDiff)}s ${ahtDiff > 0 ? "longer" : "shorter"} than the team (${duration(stats.teamAhtSec)})`,
                  )
                : undefined,
          },
          {
            variant: "card",
            label: "Promises you captured",
            value: stats ? stats.promisesCount : "—",
            icon: HandCoins,
            sub: stats?.promisesCount ? `${inr(stats.promisesAmount)} promised` : undefined,
          },
        ]}
      />
    </div>
  );
}
