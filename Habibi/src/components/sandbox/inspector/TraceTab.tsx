import { Copy } from "lucide-react";
import { toast } from "sonner";
import { INTENT_LABEL, type SandboxTurn } from "@/data/sandbox-seed";

export function TraceTab({ turns }: { turns: SandboxTurn[] }) {
  const events: Array<{ ts: number; text: string }> = [];
  turns.forEach((t, i) => {
    if (t.role === "customer") {
      events.push({ ts: t.ts, text: `t${i} · customer said "${t.text.slice(0, 40)}${t.text.length > 40 ? "…" : ""}"` });
      if (t.intent) events.push({ ts: t.ts + 1, text: `  ↳ intent: ${INTENT_LABEL[t.intent]}` });
      if (typeof t.sentiment === "number") events.push({ ts: t.ts + 2, text: `  ↳ sentiment: ${t.sentiment.toFixed(2)}` });
    }
    if (t.role === "bot") {
      events.push({ ts: t.ts, text: `t${i} · retrieved ${t.chunkIds?.length ?? 0} chunks · ${t.latencyMs}ms · ${t.tokens}t` });
      if (t.guardrailFlags?.length) events.push({ ts: t.ts + 1, text: `  ⚑ guardrail: ${t.guardrailFlags.join(", ")}` });
      events.push({ ts: t.ts + 2, text: `  ↳ bot: "${t.text.slice(0, 60)}${t.text.length > 60 ? "…" : ""}"` });
    }
    if (t.role === "system") events.push({ ts: t.ts, text: `· ${t.text}` });
  });

  const copy = () => {
    navigator.clipboard.writeText(events.map((e) => e.text).join("\n"));
    toast.success("Trace copied");
  };

  if (events.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-[var(--border-token)] p-6 text-center text-[12px] text-text-muted">
        Trace events appear here as the conversation runs.
      </div>
    );
  }

  return (
    <div>
      <button
        onClick={copy}
        className="mb-2 inline-flex items-center gap-1 rounded-md border border-[var(--border-token)] px-2 py-0.5 text-[11px] hover:bg-surface-sunken"
      >
        <Copy className="h-3 w-3" /> Copy
      </button>
      <pre className="whitespace-pre-wrap rounded-md border border-[var(--border-token)] bg-surface-sunken p-2 font-mono text-[10.5px] leading-relaxed text-text-secondary">
        {events.map((e) => e.text).join("\n")}
      </pre>
    </div>
  );
}
