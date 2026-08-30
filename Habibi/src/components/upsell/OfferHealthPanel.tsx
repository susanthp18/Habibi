import { useState, type ReactNode } from "react";
import { AlertTriangle, ChevronDown, ChevronRight } from "lucide-react";
import { Lozenge } from "@/components/ui/lozenge";
import {
  fmtDelta,
  fmtRate,
  useOfferHealth,
  useTunerSuggestions,
  type OfferHealthWindow,
  type TunerSuggestions,
} from "@/api/offer-health";
import { cn } from "@/lib/utils";

function Rate({ value }: { value: number | null }) {
  return <span className="tabular">{fmtRate(value)}</span>;
}

export function OfferHealthPanel({ window = "30d" }: { window?: OfferHealthWindow }) {
  const { data, isError, isLoading } = useOfferHealth(window);
  const tuner = useTunerSuggestions(14);
  // Collapsed by default. This is a diagnostic panel sitting on top of an
  // operational board; expanded it costs ~270px of the pipeline's height and
  // most visits to this page are not about the recommender.
  const [open, setOpen] = useState(false);
  if (isLoading) {
    return (
      <div className="shrink-0 rounded-large border border-border bg-surface px-200 py-150 text-body-small text-text-subtlest">
        Loading offer engine health…
      </div>
    );
  }
  if (isError || !data) {
    return (
      <div className="shrink-0 rounded-large border border-border bg-surface px-200 py-150 text-body-small text-text-subtle">
        Offer-engine health unavailable.
      </div>
    );
  }

  const alerts = data.alerts ?? [];
  const topSuppress = data.suppressionByReason[0];
  // An engine that has logged nothing is not a healthy engine. The latency
  // badge used to read the green "in budget" whenever `withinBudget` was not
  // literally false — and it is null, not false, when there are no samples to
  // measure. A dead recommender wore a green badge.
  const dark = data.volume.decisions === 0;
  const mode = data.engine?.mode ?? "unknown";
  const modeTone = mode === "live" ? "success" : mode === "off" ? "danger" : "warning";

  return (
    <div className="shrink-0 rounded-large border border-border bg-surface">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full flex-wrap items-center justify-between gap-100 px-200 py-100 text-left"
      >
        <div className="flex items-center gap-075 text-body-small font-semibold text-text">
          {open ? (
            <ChevronDown className="h-3.5 w-3.5 text-text-subtlest" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 text-text-subtlest" />
          )}
          Offer engine · {data.window}
          {!open ? (
            <span className="font-normal text-text-subtlest">
              {dark
                ? "no decisions logged"
                : `${data.volume.decisions} decisions · ${data.volume.presented} presented · coverage ${fmtRate(data.funnel.coverage)}`}
            </span>
          ) : null}
        </div>
        <div className="flex items-center gap-075">
          {/* The mode is the first thing to read. "shadow" scores and logs
              every decision and speaks none of them, so a shadow engine and a
              broken one produce the same empty funnel — this is the only
              element on the panel that tells them apart. */}
          <Lozenge tone={modeTone}>mode · {mode}</Lozenge>
          {dark ? (
            <Lozenge tone="warning">no decisions logged</Lozenge>
          ) : data.latency.withinBudget === false ? (
            <Lozenge tone="danger">p99 over {data.latency.budgetMs}ms</Lozenge>
          ) : data.latency.withinBudget === true ? (
            <Lozenge tone="success">p99 in budget</Lozenge>
          ) : (
            <Lozenge tone="neutral">latency unmeasured</Lozenge>
          )}
          {alerts.length > 0 ? (
            <Lozenge tone="warning">
              {alerts.length} alert{alerts.length === 1 ? "" : "s"}
            </Lozenge>
          ) : null}
        </div>
      </button>
      {!open ? null : (
        <>
          <div className="grid grid-cols-2 gap-150 border-t border-border px-200 py-150 md:grid-cols-4 xl:grid-cols-6">
            <Metric
              label="Coverage"
              value={<Rate value={data.funnel.coverage} />}
              hint={fmtDelta(data.funnel.coverageChange)}
            />
            <Metric
              label="Presented"
              value={<Rate value={data.funnel.presentationRate} />}
              hint={`${data.volume.presented} spoken`}
            />
            <Metric
              label="Interest"
              value={<Rate value={data.funnel.interestRate} />}
              hint={`${data.volume.customers} customers`}
            />
            <Metric
              label="Close probe"
              value={<Rate value={data.closeProbe.conversion} />}
              hint={`${data.closeProbe.captured} captured`}
            />
            <Metric
              label="AHT delta"
              value={
                <span
                  className={cn(
                    "tabular",
                    (data.guardrails.ahtDeltaSec ?? 0) > 25 ? "text-text-warning" : "text-text",
                  )}
                >
                  {data.guardrails.ahtDeltaSec == null
                    ? "—"
                    : `${data.guardrails.ahtDeltaSec >= 0 ? "+" : ""}${Math.round(data.guardrails.ahtDeltaSec)}s`}
                </span>
              }
              hint="with vs without offer"
            />
            <Metric
              label="Top suppress"
              value={
                <span className="truncate text-body-small">
                  {topSuppress?.reason?.replaceAll("_", " ") ?? "—"}
                </span>
              }
              hint={topSuppress ? `${topSuppress.n} · ${fmtRate(topSuppress.share)}` : "none"}
            />
          </div>
          {dark ? (
            <p className="border-t border-border px-200 py-100 text-body-small text-text-subtle">
              Nothing in <span className="font-mono">offer_decisions</span> for this window. The
              engine only runs inside a live bot conversation, so an idle bot produces an empty
              panel — this is not a failure of the panel.{" "}
              {data.engine?.lastDecisionAt
                ? `Last decision ${new Date(data.engine.lastDecisionAt).toLocaleString()}.`
                : "No decision has ever been logged."}
            </p>
          ) : null}
          {alerts.length > 0 ? (
            <ul className="space-y-050 border-t border-border px-200 py-100">
              {alerts.map((a) => (
                <li
                  key={a.metric}
                  className="flex items-start gap-075 text-body-small text-text-warning"
                >
                  <AlertTriangle className="mt-025 h-3.5 w-3.5 shrink-0" />
                  <span>{a.message}</span>
                </li>
              ))}
            </ul>
          ) : null}
          <TunerStrip tuner={tuner.data} />
        </>
      )}
    </div>
  );
}

function Metric({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="min-w-0">
      <div className="text-body-small font-semibold text-text-subtlest">{label}</div>
      <div className="mt-025 heading-small font-semibold leading-tight text-text">{value}</div>
      {hint ? <div className="truncate text-body-small text-text-subtlest">{hint}</div> : null}
    </div>
  );
}

function TunerStrip({ tuner }: { tuner?: TunerSuggestions }) {
  const reco = tuner?.copyToEnv ?? [];
  const treatment = tuner?.treatment?.copyToEnv ?? [];
  const items = [...reco, ...treatment];
  return (
    <div className="border-t border-border px-200 py-100">
      <div className="flex flex-wrap items-center gap-075">
        <div className="text-body-small font-semibold text-text">Shadow tuner</div>
        <Lozenge tone="neutral">not auto-applied</Lozenge>
        <span className="text-body-tiny text-text-subtle">{tuner?.note ?? "loading"}</span>
      </div>
      {items.length === 0 ? (
        <p className="mt-050 text-body-tiny text-text-subtlest">
          No weight changes suggested. Copy to env is a human step — this never writes live knobs.
        </p>
      ) : (
        <ul className="mt-075 space-y-025 font-mono text-body-tiny text-text">
          {items.map((k) => (
            <li key={k.name}>
              {k.name}={k.value} <span className="text-text-subtle">(now {k.current})</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
