import { Copy } from "lucide-react";
import { toast } from "sonner";
import { INTENT_LABEL, type SandboxTurn } from "@/data/sandbox-seed";
import { TurnTraceView } from "@/components/trace/TurnTraceView";

/**
 * Server-backed when an interaction id is available, client-derived otherwise.
 *
 * The derived view is not a fallback for a failed fetch — it is the correct
 * view for a text sandbox run, which has no interaction and therefore no
 * persisted trace, and for a live call before its rows are written. Keeping
 * both means the tab never regresses for the case it already handled.
 */
export function TraceTab({
  turns,
  interactionId,
}: {
  turns: SandboxTurn[];
  interactionId?: string | null;
}) {
  if (interactionId) return <TurnTraceView interactionId={interactionId} />;
  return <DerivedTrace turns={turns} />;
}

function DerivedTrace({ turns }: { turns: SandboxTurn[] }) {
  const events: Array<{ ts: number; text: string }> = [];
  turns.forEach((t, i) => {
    if (t.role === "customer") {
      events.push({
        ts: t.ts,
        text: `t${i} · customer said "${t.text.slice(0, 40)}${t.text.length > 40 ? "…" : ""}"`,
      });
      if (t.intent) events.push({ ts: t.ts + 1, text: `  ↳ intent: ${INTENT_LABEL[t.intent]}` });
      if (typeof t.sentiment === "number")
        events.push({ ts: t.ts + 2, text: `  ↳ sentiment: ${t.sentiment.toFixed(2)}` });
    }
    if (t.role === "bot") {
      events.push({
        ts: t.ts,
        text: `t${i} · retrieved ${t.chunkIds?.length ?? 0} chunks · ${t.latencyMs}ms · ${t.tokens}t`,
      });
      if (t.guardrailFlags?.length)
        events.push({ ts: t.ts + 1, text: `  ⚑ guardrail: ${t.guardrailFlags.join(", ")}` });
      events.push({
        ts: t.ts + 2,
        text: `  ↳ bot: "${t.text.slice(0, 60)}${t.text.length > 60 ? "…" : ""}"`,
      });
    }
    if (t.role === "system") events.push({ ts: t.ts, text: `· ${t.text}` });
  });

  const copy = () => {
    navigator.clipboard.writeText(events.map((e) => e.text).join("\n"));
    toast.success("Trace copied");
  };

  if (events.length === 0) {
    return (
      <div className="rounded-medium border border-dashed border-border p-300 text-center text-body-small text-text-subtlest">
        Trace events appear here as the conversation runs.
      </div>
    );
  }

  return (
    <div>
      <button
        onClick={copy}
        className="mb-100 inline-flex items-center gap-050 rounded-medium border border-border px-100 py-025 text-body-small hover:bg-surface-sunken"
      >
        <Copy className="h-3 w-3" /> Copy
      </button>
      <pre className="whitespace-pre-wrap rounded-medium border border-border bg-surface-sunken p-100 font-mono text-body-small leading-relaxed text-text-subtle">
        {events.map((e) => e.text).join("\n")}
      </pre>
    </div>
  );
}
