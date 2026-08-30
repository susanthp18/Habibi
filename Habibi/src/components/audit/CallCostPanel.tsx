import { AlertCircle } from "lucide-react";

import { useCallCost, type CallCostLine } from "@/api/call-cost";
import { USE_MOCK } from "@/api/config";
import { inrCompact } from "@/data/billing-seed";
import { LoadingState } from "@/components/ui/loading-state";
import { cn } from "@/lib/utils";

interface Props {
  interactionId: string;
}

/** Units read very differently per service — tokens are whole, minutes are not. */
function formatUnits(line: CallCostLine): string {
  const n = line.units;
  const value = n >= 100 ? Math.round(n).toLocaleString("en-IN") : n.toFixed(n >= 1 ? 2 : 3);
  return `${value} ${line.unit}`;
}

export function CallCostPanel({ interactionId }: Props) {
  const { data, isLoading, isError, error } = useCallCost(interactionId);

  // Mock mode disables the query (there is no seeded cost to serve), which would
  // otherwise leave this tab silently blank — mock is the dev default.
  if (USE_MOCK) {
    return (
      <div className="rounded-medium border border-border bg-surface px-150 py-100 text-body-small text-text-subtlest">
        Per-call cost reads live usage events. Set{" "}
        <code className="font-mono text-text-subtle">VITE_USE_MOCK=false</code> to load it from the
        API.
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="px-150 py-200">
        <LoadingState label="Loading cost breakdown" />
      </div>
    );
  }

  if (isError) {
    return (
      <div className="flex items-start gap-100 rounded-medium border border-border bg-surface px-150 py-100 text-body-small text-text-danger">
        <AlertCircle className="mt-025 h-4 w-4 shrink-0" />
        <span>Could not load cost for this call. {(error as Error)?.message ?? ""}</span>
      </div>
    );
  }

  if (!data) return null;

  // A call with no attributed usage is not a free call — it is a call that ran
  // before the pipeline was metered. Saying "₹0.00" here would be a false claim
  // about a real number, so the two states are rendered differently.
  if (!data.attributed) {
    return (
      <div className="rounded-medium border border-border bg-surface px-150 py-100">
        <div className="text-body font-medium text-text">Not metered</div>
        <p className="mt-050 text-body-small leading-relaxed text-text-subtlest">
          This call carries no usage events. Calls handled before per-call metering was enabled have
          no recorded cost — this is not a ₹0 call.
        </p>
      </div>
    );
  }

  const costPerMinute = data.durationSec > 0 ? data.totalInr / (data.durationSec / 60) : null;

  return (
    <div className="space-y-150">
      <div className="flex flex-wrap items-end justify-between gap-150 rounded-medium border border-border bg-surface px-150 py-100">
        <div>
          <div className="text-body-small text-text-subtlest">Total call cost</div>
          <div className="font-mono heading-medium text-text">{inrCompact(data.totalInr)}</div>
        </div>
        {costPerMinute !== null && (
          <div className="text-right">
            <div className="text-body-small text-text-subtlest">Per minute</div>
            <div className="font-mono text-body text-text-subtle">{inrCompact(costPerMinute)}</div>
          </div>
        )}
        {data.totalTokens > 0 && (
          <div className="text-right">
            <div className="text-body-small text-text-subtlest">LLM tokens</div>
            <div className="font-mono text-body text-text-subtle">
              {data.totalTokens.toLocaleString("en-IN")}
            </div>
          </div>
        )}
      </div>

      <div className="overflow-hidden rounded-medium border border-border bg-surface">
        <table className="w-full text-body-small">
          <thead>
            <tr className="border-b border-border text-text-subtlest">
              <th className="px-150 py-100 text-left font-semibold">Service</th>
              <th className="px-150 py-100 text-left font-semibold">Model</th>
              <th className="px-150 py-100 text-right font-semibold">Usage</th>
              <th className="px-150 py-100 text-right font-semibold">Cost</th>
              <th className="px-150 py-100 text-right font-semibold">Share</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {data.lines.map((line) => {
              const share = data.totalInr > 0 ? (line.costInr / data.totalInr) * 100 : 0;
              return (
                <tr key={`${line.serviceId}-${line.model ?? "none"}`}>
                  <td className="px-150 py-100">
                    <div className="flex items-center gap-075">
                      <span
                        aria-hidden
                        className="h-2 w-2 shrink-0 rounded-full"
                        style={{ background: line.color }}
                      />
                      <span className="text-text">{line.serviceName}</span>
                    </div>
                  </td>
                  <td className="px-150 py-100 font-mono text-text-subtle">{line.model ?? "—"}</td>
                  <td className="px-150 py-100 text-right font-mono text-text-subtle">
                    {formatUnits(line)}
                  </td>
                  <td className="px-150 py-100 text-right font-mono text-text">
                    {inrCompact(line.costInr)}
                  </td>
                  <td className="px-150 py-100 text-right font-mono text-text-subtlest">
                    {share.toFixed(1)}%
                  </td>
                </tr>
              );
            })}
          </tbody>
          <tfoot>
            <tr className={cn("border-t border-border font-semibold")}>
              <td className="px-150 py-100 text-text" colSpan={3}>
                Total
              </td>
              <td className="px-150 py-100 text-right font-mono text-text">
                {inrCompact(data.totalInr)}
              </td>
              <td className="px-150 py-100" />
            </tr>
          </tfoot>
        </table>
      </div>

      <p className="text-body-small leading-relaxed text-text-subtlest">
        LLM and TTS are measured from the pipeline (tokens and characters). STT is derived from call
        duration — Azure bills continuous recognition for the audio streamed while the recognizer is
        open.
      </p>
    </div>
  );
}
