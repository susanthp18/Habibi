import type { SandboxTurn } from "@/data/sandbox-seed";

export type TurnMetric = {
  id: string;
  label: string;
  ttfbMs?: number | null;
  ttfaMs?: number | null;
  tokens?: number | null;
  chars?: number | null;
};

export function MetricsTab({
  metrics,
  turns,
}: {
  metrics: TurnMetric[];
  turns: SandboxTurn[];
}) {
  if (metrics.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-[var(--border-token)] p-6 text-center text-[12px] text-text-muted">
        Metrics appear during Live voice (TTFB / TTFA / tokens). Text mode shows latency on bot
        bubbles.
      </div>
    );
  }

  // Only text-path turns carry a real latency; live bot outputs are recorded
  // with latencyMs: 0, so exclude them or the average reads "0ms" during a call.
  const botLatencies = turns
    .filter((t) => t.role === "bot" && typeof t.latencyMs === "number" && t.latencyMs > 0)
    .map((t) => t.latencyMs as number);

  return (
    <div className="space-y-3">
      {botLatencies.length > 0 && (
        <div className="rounded-md border border-[var(--border-token)] bg-surface-sunken p-2.5 text-[11px] text-text-secondary">
          Text path avg latency:{" "}
          <span className="font-mono font-medium text-text-primary">
            {Math.round(botLatencies.reduce((a, b) => a + b, 0) / botLatencies.length)}ms
          </span>
        </div>
      )}
      {metrics.map((m) => (
        <div
          key={m.id}
          className="rounded-md border border-[var(--border-token)] bg-surface-sunken p-2.5 text-[11.5px]"
        >
          <div className="font-medium text-text-primary">{m.label}</div>
          <div className="mt-1 grid grid-cols-2 gap-1 font-mono text-[10.5px] text-text-muted">
            {m.ttfbMs != null && <span>TTFB {Math.round(m.ttfbMs)}ms</span>}
            {m.ttfaMs != null && <span>TTFA {Math.round(m.ttfaMs)}ms</span>}
            {m.tokens != null && <span>{m.tokens} tok</span>}
            {m.chars != null && <span>{m.chars} chars</span>}
          </div>
        </div>
      ))}
    </div>
  );
}
