import { useState } from "react";
import {
  Activity,
  Beaker,
  FileText,
  FlaskConical,
  Gauge,
  Layers,
  LineChart,
  Radio,
  Wrench,
} from "lucide-react";
import type { SandboxTurn } from "@/data/sandbox-seed";
import { RetrievalTab } from "./inspector/RetrievalTab";
import { IntentTab } from "./inspector/IntentTab";
import { SentimentTab } from "./inspector/SentimentTab";
import { TraceTab } from "./inspector/TraceTab";
import { ToolsTab } from "./inspector/ToolsTab";
import { MetricsTab, type TurnMetric } from "./inspector/MetricsTab";
import { TwinTab } from "./inspector/TwinTab";
import { EvalCockpit } from "./EvalCockpit";
import { EMPTY_INSIGHTS, type LiveCallInsights } from "./voice/liveEvents";
import { cn } from "@/lib/utils";
import { Lozenge } from "@/components/ui/lozenge";

type Tab =
  | "retrieval"
  | "tools"
  | "intent"
  | "sentiment"
  | "trace"
  | "metrics"
  | "twin"
  | "evals"
  | "context";

type Props = {
  turns: SandboxTurn[];
  metrics?: TurnMetric[];
  /** Live-call domain events; empty in text mode. */
  insights?: LiveCallInsights;
  /** Force-show Context tab (PII) outside DEV — off by default. */
  showContextDebug?: boolean;
  /**
   * Interaction backing this session, when there is one. Lets the Trace tab
   * read the persisted per-turn timeline instead of reconstructing one from
   * in-memory state. Absent for a text sandbox run, which has no interaction.
   */
  interactionId?: string | null;
  /** Layout override — SplitPanes supplies the width, so the fixed one goes. */
  className?: string;
};

export function InspectorPanel({
  turns,
  metrics = [],
  insights = EMPTY_INSIGHTS,
  showContextDebug = false,
  interactionId = null,
  className,
}: Props) {
  const [tab, setTab] = useState<Tab>("retrieval");
  const toolCount = insights.toolCalls.length;
  const contextAllowed = Boolean(import.meta.env.DEV) || showContextDebug;
  const TABS: Array<{ key: Tab; label: string; icon: typeof Layers; badge?: number }> = [
    { key: "retrieval", label: "Retrieval", icon: Layers },
    { key: "tools", label: "Tools", icon: Wrench, badge: toolCount || undefined },
    { key: "intent", label: "Intent", icon: Radio },
    { key: "sentiment", label: "Sentiment", icon: LineChart },
    { key: "trace", label: "Trace", icon: Activity },
    { key: "metrics", label: "Metrics", icon: Gauge },
    { key: "twin", label: "Twin", icon: Beaker },
    { key: "evals", label: "Evals", icon: FlaskConical },
    ...(contextAllowed ? [{ key: "context" as const, label: "Context", icon: FileText }] : []),
  ];

  return (
    <aside
      className={cn(
        "hidden h-full min-h-0 w-[21.25rem] shrink-0 flex-col border-l border-border bg-surface xl:flex",
        className,
      )}
    >
      <div className="shrink-0 border-b border-border px-150">
        <div className="flex gap-025 overflow-x-auto">
          {TABS.map((t) => {
            const Icon = t.icon;
            return (
              <button
                key={t.key}
                type="button"
                onClick={() => setTab(t.key)}
                className={cn(
                  "inline-flex shrink-0 flex-1 items-center justify-center gap-050 border-b-2 px-050 py-100 text-body-small",
                  tab === t.key
                    ? "border-border-brand font-semibold text-text-brand"
                    : "border-transparent text-text-subtle hover:text-text",
                )}
              >
                <Icon className="h-3.5 w-3.5" />
                {t.label}
                {t.badge ? (
                  <Lozenge tone="selected" className="leading-4">
                    {t.badge}
                  </Lozenge>
                ) : null}
              </button>
            );
          })}
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-150">
        {tab === "retrieval" && <RetrievalTab turns={turns} ragHits={insights.ragHits} />}
        {tab === "tools" && <ToolsTab calls={insights.toolCalls} />}
        {tab === "intent" && <IntentTab turns={turns} analysis={insights.turnAnalysis} />}
        {tab === "sentiment" && <SentimentTab turns={turns} analysis={insights.turnAnalysis} />}
        {tab === "trace" && <TraceTab turns={turns} interactionId={interactionId} />}
        {tab === "metrics" && (
          <MetricsTab
            metrics={metrics}
            turns={turns}
            turnAudio={insights.turnAudio}
            analysis={insights.turnAnalysis}
          />
        )}
        {tab === "twin" && <TwinTab />}
        {tab === "evals" && <EvalCockpit compact />}
        {tab === "context" && contextAllowed && (
          <div className="space-y-100">
            <p className="text-body-small text-text-warning-bolder">
              Debug only — may contain real customer PII. Visible in dev builds or when context
              debug is enabled.
            </p>
            {insights.contextCard ? (
              <pre className="whitespace-pre-wrap break-words rounded-medium border border-border bg-surface-sunken p-100 font-mono text-body-small leading-relaxed text-text-subtle">
                {insights.contextCard}
              </pre>
            ) : (
              <div className="rounded-medium border border-dashed border-border p-300 text-center text-body-small text-text-subtlest">
                Context card arrives after the voice session binds CRM state.
              </div>
            )}
          </div>
        )}
      </div>
    </aside>
  );
}
