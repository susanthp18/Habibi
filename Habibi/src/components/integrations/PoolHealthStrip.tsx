// -----------------------------------------------------------------------------
// Key-pool health — GET /providers/pools.
//
// The backend comment on that endpoint says what this is for: "free-tier
// exhaustion is visible before a demo hits it". The pool retires a key on a 402
// and rotates to the next one silently, so the first symptom an operator sees
// today is a call that will not start, minutes after the pool actually ran dry.
//
// Two states must never look alike here. A pool with total=0 is a provider with
// no key configured — a real, actionable fact, and the endpoint deliberately
// touches every seeded provider so such a pool reports rather than vanishing. A
// failed request is not that: it is no information at all, and rendering zeros
// for it would invent the very reassurance this strip exists to withhold.
// -----------------------------------------------------------------------------

import { AlertCircle, KeyRound } from "lucide-react";

import { providerDot, useProviderPools, type ProviderPool } from "@/api/providers";
import { LoadingState } from "@/components/ui/loading-state";
import { Lozenge } from "@/components/ui/lozenge";
import { cn } from "@/lib/utils";

function poolTone(pool: ProviderPool): {
  tone: "success" | "warning" | "danger" | "neutral";
  label: string;
} {
  if (pool.total === 0) return { tone: "neutral", label: "No key configured" };
  if (pool.available === 0) return { tone: "danger", label: "Exhausted" };
  if (pool.retired > 0) return { tone: "warning", label: `${pool.retired} cooling` };
  return { tone: "success", label: "Healthy" };
}

function PoolCard({ pool }: { pool: ProviderPool }) {
  const { tone, label } = poolTone(pool);
  const exhausted = pool.total > 0 && pool.available === 0;
  return (
    <div
      className={cn(
        "rounded-medium border bg-surface px-150 py-100",
        exhausted ? "border-border-danger" : "border-border",
      )}
    >
      <div className="flex items-center gap-075">
        <span
          aria-hidden
          className="h-2 w-2 shrink-0 rounded-full"
          style={{ background: providerDot(pool.provider) }}
        />
        <span className="truncate text-body font-medium text-text">{pool.provider}</span>
        <Lozenge tone={tone} className="ml-auto shrink-0">
          {label}
        </Lozenge>
      </div>
      <div className="mt-100 flex items-baseline gap-100">
        <span className="font-mono heading-small tabular-nums text-text">{pool.available}</span>
        <span className="text-body-small text-text-subtlest">
          of {pool.total} {pool.total === 1 ? "key" : "keys"} available
        </span>
      </div>
      <div className="mt-050 text-body-tiny text-text-subtle">
        {pool.sessionsBound} session{pool.sessionsBound === 1 ? "" : "s"} bound
      </div>
      {pool.keys.length > 0 && (
        <ul className="mt-100 space-y-025 border-t border-border pt-100">
          {pool.keys.map((key) => (
            <li key={key.tail} className="flex items-center gap-075 text-body-tiny">
              {/* Last four characters only — enough to identify a key in a log
                  without putting one on a screen someone can photograph. */}
              <code className="font-mono text-text-subtle">···{key.tail}</code>
              <span className="tabular-nums text-text-subtlest">{key.uses} uses</span>
              {key.retired && (
                <span className="ml-auto truncate text-text-danger" title={key.lastError}>
                  {key.lastError || "retired"}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function PoolHealthStrip() {
  const { data, isPending, isError, error } = useProviderPools();

  if (isPending) {
    return (
      <div className="px-150 py-200">
        <LoadingState label="Loading key-pool health" />
      </div>
    );
  }

  if (isError) {
    return (
      <div className="flex items-start gap-100 rounded-medium border border-border-warning bg-background-warning-subtler px-150 py-100 text-body-small text-text-warning-bolder">
        <AlertCircle className="mt-025 h-4 w-4 shrink-0" />
        <span>
          Pool telemetry unavailable — key health cannot be confirmed.{" "}
          {(error as Error)?.message ?? ""}
        </span>
      </div>
    );
  }

  const pools = data ?? [];
  if (pools.length === 0) {
    return (
      <div className="rounded-medium border border-dashed border-border bg-surface-sunken/40 px-200 py-150 text-center">
        <div className="text-body font-medium text-text">No key pools built yet</div>
        <p className="mx-auto mt-050 max-w-prose text-body-small text-text-subtle">
          A pool appears once a provider has been asked for a key at least once this process.
        </p>
      </div>
    );
  }

  const dry = pools.filter((p) => p.total > 0 && p.available === 0);
  return (
    <section className="space-y-100">
      <div className="flex items-center gap-075">
        <KeyRound className="h-3.5 w-3.5 text-text-subtle" />
        <h2 className="text-body font-semibold text-text">Key-pool health</h2>
        {dry.length > 0 && (
          <Lozenge tone="danger">
            {dry.length} pool{dry.length === 1 ? "" : "s"} exhausted
          </Lozenge>
        )}
        <span className="ml-auto text-body-tiny text-text-subtlest">Refreshes every 30s</span>
      </div>
      <div className="grid grid-cols-1 gap-150 md:grid-cols-2 xl:grid-cols-3">
        {pools.map((pool) => (
          <PoolCard key={pool.provider} pool={pool} />
        ))}
      </div>
    </section>
  );
}
