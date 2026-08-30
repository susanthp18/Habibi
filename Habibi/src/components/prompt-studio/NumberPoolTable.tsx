// -----------------------------------------------------------------------------
// Caller-ID pool health — GET /outbound/number-pools.
//
// bot_worker runs outbound.sweep_pool_health every settle cycle, and it moves
// numbers between active and cooling on their own seven-day answer rate. That
// loop has been running with nothing rendering it, so when answer rates fell
// there was no way to see that half the pool had been quietly benched — the
// exact gap section 8.2 of the outbound design doc describes as "no way to
// observe that, let alone rotate".
//
// Two values are deliberately not coerced. answer_rate_7d is null until the
// number has enough volume to judge (a rate over four dials is noise), and null
// is not 0% — rendering it as 0% would show a healthy new number as the worst
// in the pool. `retired` is a human decision the sweep never undoes, so it is
// toned differently from `cooling`, which comes back on its own.
// -----------------------------------------------------------------------------

import { AlertCircle, PhoneCall } from "lucide-react";

import { useNumberPools, type NumberPool, type PoolNumber } from "@/api/outbound";
import { LoadingState } from "@/components/ui/loading-state";
import { Lozenge, type LozengeTone } from "@/components/ui/lozenge";

const STATE_TONE: Record<PoolNumber["state"], LozengeTone> = {
  active: "success",
  cooling: "warning",
  retired: "neutral",
};

const KIND_LABEL: Record<NumberPool["kind"], string> = {
  service_1600: "1600 series · service only",
  promotional: "Promotional",
  general: "General",
};

function rate(value: number | null): string {
  // Null means the sweep declined to score it, which is a different fact from
  // "nobody answers this number".
  if (value === null || value === undefined) return "—";
  return `${(value * 100).toFixed(1)}%`;
}

function when(iso: string | null): string {
  if (!iso) return "—";
  const ms = Date.parse(iso);
  if (Number.isNaN(ms)) return "—";
  const days = Math.floor((Date.now() - ms) / 86_400_000);
  if (days <= 0) return "today";
  if (days === 1) return "1d ago";
  return `${days}d ago`;
}

function PoolBlock({ pool }: { pool: NumberPool }) {
  const cooling = pool.numbers.filter((n) => n.state === "cooling").length;
  return (
    <div className="overflow-hidden rounded-medium border border-border bg-surface">
      <div className="flex flex-wrap items-center gap-100 border-b border-border px-150 py-100">
        <span className="text-body-small font-semibold text-text">{pool.name}</span>
        <Lozenge tone={pool.kind === "service_1600" ? "information" : "neutral"}>
          {KIND_LABEL[pool.kind]}
        </Lozenge>
        {!pool.enabled && <Lozenge tone="warning">Disabled</Lozenge>}
        {cooling > 0 && <Lozenge tone="warning">{cooling} cooling</Lozenge>}
        <span className="ml-auto text-body-tiny text-text-subtlest">
          {pool.numbers.length} number{pool.numbers.length === 1 ? "" : "s"}
        </span>
      </div>
      {pool.numbers.length === 0 ? (
        <p className="px-150 py-150 text-body-small text-text-subtle">
          No numbers in this pool — nothing to dial from.
        </p>
      ) : (
        <table className="w-full text-body-small">
          <thead>
            <tr className="border-b border-border text-text-subtlest">
              <th className="px-150 py-100 text-left font-semibold">Number</th>
              <th className="px-150 py-100 text-left font-semibold">State</th>
              <th className="px-150 py-100 text-right font-semibold">Dials · 7d</th>
              <th className="px-150 py-100 text-right font-semibold">Answered · 7d</th>
              <th className="px-150 py-100 text-right font-semibold">State changed</th>
              <th className="px-150 py-100 text-right font-semibold">Last used</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {pool.numbers.map((n) => (
              <tr key={n.id}>
                <td className="px-150 py-100 font-mono text-text">{n.e164}</td>
                <td className="px-150 py-100">
                  <Lozenge tone={STATE_TONE[n.state]}>{n.state}</Lozenge>
                  {n.note && <span className="ml-075 text-text-subtlest">{n.note}</span>}
                </td>
                <td className="px-150 py-100 text-right font-mono tabular-nums text-text-subtle">
                  {n.attempts_7d}
                </td>
                <td className="px-150 py-100 text-right font-mono tabular-nums text-text-subtle">
                  {rate(n.answer_rate_7d)}
                </td>
                <td className="px-150 py-100 text-right text-text-subtlest">
                  {when(n.state_changed_at)}
                </td>
                <td className="px-150 py-100 text-right text-text-subtlest">
                  {when(n.last_used_at)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export function NumberPoolTable() {
  const { data, isPending, isError, error } = useNumberPools();

  if (isPending) {
    return <LoadingState label="Loading caller-ID pools" />;
  }

  if (isError) {
    return (
      <div className="flex items-start gap-100 rounded-medium border border-border bg-surface px-150 py-100 text-body-small text-text-danger">
        <AlertCircle className="mt-025 h-4 w-4 shrink-0" />
        <span>
          Caller-ID pool health unavailable — cannot confirm which numbers are still dialling.{" "}
          {(error as Error)?.message ?? ""}
        </span>
      </div>
    );
  }

  const pools = data ?? [];
  return (
    <section className="space-y-100">
      <div className="flex items-center gap-075">
        <PhoneCall className="h-3.5 w-3.5 text-text-subtle" />
        <h3 className="text-body-small font-semibold text-text">Caller-ID pools</h3>
      </div>
      {pools.length === 0 ? (
        <div className="rounded-medium border border-dashed border-border bg-surface-sunken/40 px-200 py-250 text-center">
          <div className="text-body font-medium text-text">No caller-ID pools configured</div>
          <p className="mx-auto mt-050 max-w-prose text-body-small text-text-subtle">
            Outbound dials from whatever number the carrier presents, so spam decay on it cannot be
            observed or rotated around.
          </p>
        </div>
      ) : (
        <>
          <div className="space-y-150">
            {pools.map((pool) => (
              <PoolBlock key={pool.id} pool={pool} />
            ))}
          </div>
          <p className="text-body-tiny leading-relaxed text-text-subtlest">
            The health sweep moves a number to cooling once enough dials sit behind a collapsed
            answer rate, and brings it back on probation after the rest. Retired is a human decision
            about a number being handed back to the carrier — the sweep never undoes it. A blank
            answer rate means too few dials to judge, not a rate of zero.
          </p>
        </>
      )}
    </section>
  );
}
