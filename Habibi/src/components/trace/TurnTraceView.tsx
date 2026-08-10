import { Copy } from "lucide-react";
import { toast } from "sonner";
import { useTurnTrace, type TraceTurn } from "@/api/trace";
import { USE_MOCK } from "@/api/config";

/**
 * The persisted per-turn timeline for one interaction.
 *
 * Tool calls, retrievals and the latency breakdown used to live at three grains
 * that could not be joined — `bot_tool_calls` by job_id (WhatsApp only),
 * `retrieval_logs` by interaction, latency on the transcript row — so "what did
 * the bot do on turn 4" had no answer. Migration 0055 gave the event tables a
 * transcript_turn_id and this renders the result.
 *
 * Shared by the audit call drawer and the Sandbox Inspector so there is one
 * implementation of what a trace looks like.
 */
export function TurnTraceView({ interactionId }: { interactionId: string }) {
  const { data, isLoading, isError, error } = useTurnTrace(interactionId);

  if (USE_MOCK) {
    return (
      <Empty>Traces are served by the API — switch off mock mode to view one.</Empty>
    );
  }
  if (isLoading) return <Empty>Loading trace…</Empty>;
  if (isError) {
    return <Empty>{error instanceof Error ? error.message : "Trace unavailable."}</Empty>;
  }
  if (!data || data.length === 0) {
    return <Empty>No turns recorded for this call.</Empty>;
  }

  const copy = () => {
    navigator.clipboard.writeText(JSON.stringify(data, null, 2));
    toast.success("Trace copied");
  };

  return (
    <div className="space-y-100">
      <button
        onClick={copy}
        className="inline-flex items-center gap-050 rounded-medium border border-border px-100 py-025 text-body-small hover:bg-surface-sunken"
      >
        <Copy className="h-3 w-3" /> Copy JSON
      </button>
      {data.map((t) => (
        <TurnCard key={t.turnId ?? "unattributed"} turn={t} />
      ))}
    </div>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-medium border border-dashed border-border p-300 text-center text-body-small text-text-subtlest">
      {children}
    </div>
  );
}

function ms(v: number | null | undefined) {
  return typeof v === "number" ? `${v}ms` : null;
}

export function TurnCard({ turn: t }: { turn: TraceTurn }) {
  return (
    <div className="rounded-medium border border-border bg-surface-sunken p-100">
      <div className="flex items-baseline justify-between gap-100">
        <span className="font-mono text-body-small text-text-subtle">
          {/* Null index = the synthetic bucket for events recorded before their
              turn existed. Shown rather than dropped. */}
          {t.turnIndex == null ? "unattributed" : `t${t.turnIndex}`} · {t.speaker}
        </span>
        {ms(t.latency?.ttfbMs) && (
          <span className="tabular text-body-small text-text-subtlest">
            ttfb {ms(t.latency.ttfbMs)}
          </span>
        )}
      </div>

      {t.text && (
        <div className="mt-050 text-body-small text-text">
          {t.text.length > 160 ? `${t.text.slice(0, 160)}…` : t.text}
        </div>
      )}

      {(t.intent || typeof t.sentimentDelta === "number") && (
        <div className="mt-050 flex flex-wrap gap-100 text-body-small text-text-subtle">
          {t.intent && (
            <span>
              intent: {t.intent}
              {typeof t.intentScore === "number" && ` (${t.intentScore.toFixed(2)})`}
            </span>
          )}
          {typeof t.sentimentDelta === "number" && (
            <span>sentiment: {t.sentimentDelta.toFixed(2)}</span>
          )}
        </div>
      )}

      {t.toolCalls.map((c, i) => (
        <div
          key={`${c.tool}-${i}`}
          className="mt-050 flex items-baseline gap-100 font-mono text-body-small"
        >
          <span className={c.ok ? "text-text-success" : "text-text-danger"}>
            {c.ok ? "✓" : "✗"}
          </span>
          <span className="text-text">{c.tool}</span>
          {ms(c.latencyMs) && <span className="text-text-subtlest">{ms(c.latencyMs)}</span>}
          {c.error && <span className="text-text-danger">{c.error}</span>}
        </div>
      ))}

      {t.retrievals.map((r, i) => (
        <div
          key={`rag-${i}`}
          className="mt-050 flex items-baseline gap-100 font-mono text-body-small text-text-subtle"
        >
          <span>⌕</span>
          <span>
            {r.hits} chunk{r.hits === 1 ? "" : "s"}
          </span>
          {typeof r.topScore === "number" && <span>top {r.topScore.toFixed(2)}</span>}
          {ms(r.latencyMs) && <span className="text-text-subtlest">{ms(r.latencyMs)}</span>}
        </div>
      ))}

      {(t.latency?.sttTtfbMs != null ||
        t.latency?.llmTtfbMs != null ||
        t.latency?.ttsTtfbMs != null) && (
        <div className="mt-050 flex flex-wrap gap-100 tabular text-body-small text-text-subtlest">
          {t.latency.sttTtfbMs != null && <span>stt {t.latency.sttTtfbMs}ms</span>}
          {t.latency.llmTtfbMs != null && <span>llm {t.latency.llmTtfbMs}ms</span>}
          {t.latency.ttsTtfbMs != null && <span>tts {t.latency.ttsTtfbMs}ms</span>}
          {t.latency.toolMs != null && <span>tools {t.latency.toolMs}ms</span>}
        </div>
      )}
    </div>
  );
}
