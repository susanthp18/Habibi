import { useMemo, useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { toast } from "sonner";
import { ClipboardCheck, Scale, SlidersHorizontal } from "lucide-react";
import { cn } from "@/lib/utils";
import { AppShell } from "@/components/shell/AppShell";
import { QaStatsStrip } from "@/components/qa/QaStatsStrip";
import { ScoringQueue } from "@/components/qa/ScoringQueue";
import { ScoringCanvas } from "@/components/qa/ScoringCanvas";
import { AgentTrendsTable } from "@/components/qa/AgentTrendsTable";
import { AgentTrendCard } from "@/components/qa/AgentTrendCard";
import { CalibrationView } from "@/components/qa/CalibrationView";
import { CoachingBoard } from "@/components/qa/CoachingBoard";
import { NewCoachingSheet } from "@/components/qa/NewCoachingSheet";
import { RubricBuilderSheet } from "@/components/qa/RubricBuilderSheet";
import {
  scorecards as seedScorecards,
  initialCoaching,
  initialCalibrations,
  defaultRubric,
  agentStats,
  type Scorecard,
  type ScorecardEntry,
  type CoachingAction,
  type CoachingStatus,
  type Rubric,
  type CalibrationSession,
} from "@/data/qa-seed";

type Tab = "queue" | "trends" | "calibration" | "coaching";

export const Route = createFileRoute("/qa")({
  head: () => ({
    meta: [
      { title: "QA Scorecards & Coaching — Collections Agent" },
      { name: "description", content: "Score bot and agent interactions against a weighted rubric, run calibration sessions, and assign coaching actions." },
      { property: "og:title", content: "QA Scorecards & Coaching" },
      { property: "og:description", content: "Rubric-driven quality scoring with AI-assisted suggestions, agent trends, calibration, and coaching workflow." },
    ],
  }),
  component: QaPage,
});

function QaPage() {
  const [rubric, setRubric] = useState<Rubric>(defaultRubric);
  const [scorecards, setScorecards] = useState<Scorecard[]>(seedScorecards);
  const [coaching, setCoaching] = useState<CoachingAction[]>(initialCoaching);
  const [calibrations, setCalibrations] = useState<CalibrationSession[]>(initialCalibrations);

  const [tab, setTab] = useState<Tab>("queue");
  const [activeScoreId, setActiveScoreId] = useState<string | null>(scorecards.find((s) => s.status !== "final")?.id ?? scorecards[0]?.id ?? null);
  const [activeAgent, setActiveAgent] = useState<string | null>(null);
  const [rubricOpen, setRubricOpen] = useState(false);
  const [coachOpen, setCoachOpen] = useState(false);
  const [coachPreset, setCoachPreset] = useState<{ agent?: string; scorecardId?: string; callId?: string }>({});

  const activeScore = useMemo(() => scorecards.find((s) => s.id === activeScoreId) ?? null, [scorecards, activeScoreId]);
  const stats = useMemo(() => agentStats(scorecards, rubric, coaching), [scorecards, rubric, coaching]);
  const activeStat = useMemo(() => stats.find((s) => s.agentId === (activeAgent ?? stats[0]?.agentId)) ?? null, [stats, activeAgent]);

  const updateEntries = (id: string, entries: ScorecardEntry[]) => {
    setScorecards((prev) => prev.map((s) => (s.id === id ? { ...s, entries, status: s.status === "unscored" ? "ai_draft" : s.status } : s)));
  };
  const saveDraft = (id: string) => {
    setScorecards((prev) => prev.map((s) => (s.id === id ? { ...s, status: s.status === "final" ? "final" : "ai_draft" } : s)));
  };
  const publishScore = (id: string) => {
    setScorecards((prev) => prev.map((s) => (s.id === id ? { ...s, status: "final", reviewer: "You", scoredAt: new Date().toISOString() } : s)));
    toast.success("Scorecard published", { description: "Sent to agent + logged to audit trail." });
  };

  const openCoachFromScorecard = (s: Scorecard) => {
    setCoachPreset({ agent: s.agentId, scorecardId: s.id, callId: s.callId });
    setCoachOpen(true);
  };

  const moveCoaching = (id: string, status: CoachingStatus) => {
    setCoaching((prev) => prev.map((a) => (a.id === id ? { ...a, status } : a)));
  };
  const openCoachDetail = (id: string) => {
    const a = coaching.find((c) => c.id === id);
    if (a) toast(a.title, { description: `${a.agentId} · ${a.category}` });
  };
  const addCoaching = (data: Omit<CoachingAction, "id" | "createdAt" | "notes" | "status">) => {
    const item: CoachingAction = {
      ...data,
      id: `coach-${Date.now()}`,
      status: "assigned",
      notes: [],
      createdAt: new Date().toISOString(),
    };
    setCoaching((prev) => [item, ...prev]);
    setCoachOpen(false);
    toast.success("Coaching action created", { description: `${data.agentId} · ${data.title}` });
  };

  const closeCalibration = (id: string) => {
    setCalibrations((prev) => prev.map((s) => (s.id === id ? { ...s, status: "closed" } : s)));
  };

  const TABS: Array<{ key: Tab; label: string; icon: any; count?: number }> = [
    { key: "queue", label: "Scoring Queue", icon: ClipboardCheck, count: scorecards.filter((s) => s.status !== "final").length },
    { key: "trends", label: "Agent Trends", icon: SlidersHorizontal, count: stats.length },
    { key: "calibration", label: "Calibration", icon: Scale, count: calibrations.filter((c) => c.status === "active").length },
    { key: "coaching", label: "Coaching", icon: ClipboardCheck, count: coaching.filter((c) => c.status !== "done").length },
  ];

  return (
    <AppShell>
      <div className="flex h-full min-h-0 flex-col">
        <header className="shrink-0 border-b border-[var(--border-token)] bg-surface-card px-5 py-3">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-[18px] font-semibold text-brand-navy">QA Scorecards & Coaching</h1>
            <span className="rounded-full bg-surface-sunken px-2 py-0.5 text-[11px] font-medium text-text-secondary">QA Lead workspace</span>
            <div className="ml-auto flex items-center gap-2">
              <button
                onClick={() => setRubricOpen(true)}
                className="inline-flex items-center gap-1 rounded-md border border-[var(--border-token)] px-3 py-1.5 text-[12px] text-text-primary hover:bg-surface-sunken"
              >
                <SlidersHorizontal className="h-3.5 w-3.5" /> Edit rubric
              </button>
              <button
                onClick={() => setTab("calibration")}
                className="inline-flex items-center gap-1 rounded-md border border-[var(--border-token)] px-3 py-1.5 text-[12px] text-text-primary hover:bg-surface-sunken"
              >
                <Scale className="h-3.5 w-3.5" /> Calibrate
              </button>
            </div>
          </div>
          <p className="text-[12px] text-text-secondary">
            Weighted rubric scoring (empathy, resolution, compliance, script, upsell) — AI-assisted drafts, human sign-off, then drives coaching.
          </p>
        </header>

        <QaStatsStrip scorecards={scorecards} coaching={coaching} calibrations={calibrations} />

        <div className="shrink-0 border-b border-[var(--border-token)] bg-surface-card px-5">
          <div className="flex gap-1">
            {TABS.map((t) => {
              const Icon = t.icon;
              return (
                <button
                  key={t.key}
                  onClick={() => setTab(t.key)}
                  className={cn(
                    "inline-flex items-center gap-1.5 border-b-2 px-3 py-2 text-[12.5px]",
                    tab === t.key
                      ? "border-brand-primary text-brand-primary-dark font-semibold"
                      : "border-transparent text-text-secondary hover:text-text-primary",
                  )}
                >
                  <Icon className="h-3.5 w-3.5" />
                  {t.label}
                  {t.count !== undefined && (
                    <span className={cn(
                      "rounded-full px-1.5 py-0.5 text-[10px]",
                      tab === t.key ? "bg-brand-tint text-brand-primary-dark" : "bg-surface-sunken text-text-muted",
                    )}>{t.count}</span>
                  )}
                </button>
              );
            })}
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-hidden bg-surface-app">
          {tab === "queue" && (
            <div className="grid h-full min-h-0 grid-cols-[320px_minmax(0,1fr)]">
              <ScoringQueue scorecards={scorecards} activeId={activeScoreId} onSelect={setActiveScoreId} />
              <ScoringCanvas
                scorecard={activeScore}
                onChangeEntries={updateEntries}
                onPublish={publishScore}
                onSaveDraft={saveDraft}
                onAssignCoaching={openCoachFromScorecard}
              />
            </div>
          )}

          {tab === "trends" && (
            <div className="h-full min-h-0 overflow-y-auto p-5">
              <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
                <AgentTrendsTable stats={stats} activeAgent={activeAgent ?? stats[0]?.agentId ?? null} onSelect={setActiveAgent} />
                <AgentTrendCard stat={activeStat} />
              </div>
            </div>
          )}

          {tab === "calibration" && (
            <div className="h-full min-h-0 overflow-y-auto p-5">
              <CalibrationView sessions={calibrations} onClose={closeCalibration} />
            </div>
          )}

          {tab === "coaching" && (
            <div className="h-full min-h-0 overflow-y-auto p-5">
              <CoachingBoard
                actions={coaching}
                onMove={moveCoaching}
                onNew={() => { setCoachPreset({}); setCoachOpen(true); }}
                onOpen={openCoachDetail}
              />
            </div>
          )}
        </div>
      </div>

      <RubricBuilderSheet open={rubricOpen} onClose={() => setRubricOpen(false)} rubric={rubric} onSave={setRubric} />
      <NewCoachingSheet
        open={coachOpen}
        onClose={() => setCoachOpen(false)}
        onSubmit={addCoaching}
        presetAgent={coachPreset.agent}
        presetScorecardId={coachPreset.scorecardId}
        presetCallId={coachPreset.callId}
      />
    </AppShell>
  );
}
