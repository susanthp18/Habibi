import { useEffect, useMemo, useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
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
  createCoachingAction,
  finalizeScorecard,
  patchCalibrationSession,
  patchCoachingAction,
  saveScorecard,
  useCalibrationSessions,
  useCoachingActions,
  useRubric,
  useScorecards,
} from "@/api/qa";
import { Lozenge } from "@/components/ui/lozenge";
import {
  defaultRubric,
  agentStats,
  type Scorecard,
  type ScorecardEntry,
  type CoachingAction,
  type CoachingStatus,
  type Rubric,
} from "@/data/qa-seed";

type Tab = "queue" | "trends" | "calibration" | "coaching";

export const Route = createFileRoute("/qa")({
  head: () => ({
    meta: [
      { title: "QA Scorecards & Coaching — BigBound AI" },
      { name: "description", content: "Score bot and agent interactions against a weighted rubric, run calibration sessions, and assign coaching actions." },
      { property: "og:title", content: "QA Scorecards & Coaching" },
      { property: "og:description", content: "Rubric-driven quality scoring with AI-assisted suggestions, agent trends, calibration, and coaching workflow." },
    ],
  }),
  component: QaPage,
});

function QaPage() {
  const queryClient = useQueryClient();
  const { data: remoteRubric } = useRubric();
  const { data: remoteScorecards } = useScorecards();
  const { data: remoteCoaching } = useCoachingActions();
  const { data: remoteCalibrations } = useCalibrationSessions();

  // Local rubric edits (builder sheet) — live GET /rubric is the base.
  const [rubricOverride, setRubricOverride] = useState<Rubric | null>(null);
  const rubric = rubricOverride ?? remoteRubric ?? defaultRubric;

  // In-progress criterion edits until Save draft / Publish.
  const [draftEntries, setDraftEntries] = useState<Record<string, ScorecardEntry[]>>({});

  const coaching = remoteCoaching ?? [];
  const calibrations = remoteCalibrations ?? [];

  const scorecards = useMemo(() => {
    const base = remoteScorecards ?? [];
    return base.map((s) => (draftEntries[s.id] ? { ...s, entries: draftEntries[s.id]! } : s));
  }, [remoteScorecards, draftEntries]);

  const [tab, setTab] = useState<Tab>("queue");
  const [activeScoreId, setActiveScoreId] = useState<string | null>(null);
  const [activeAgent, setActiveAgent] = useState<string | null>(null);
  const [rubricOpen, setRubricOpen] = useState(false);
  const [coachOpen, setCoachOpen] = useState(false);
  const [coachPreset, setCoachPreset] = useState<{ agent?: string; scorecardId?: string; callId?: string }>({});

  useEffect(() => {
    if (activeScoreId) return;
    const first = scorecards.find((s) => s.status !== "final") ?? scorecards[0];
    if (first) setActiveScoreId(first.id);
  }, [scorecards, activeScoreId]);

  const activeScore = useMemo(
    () => scorecards.find((s) => s.id === activeScoreId) ?? null,
    [scorecards, activeScoreId],
  );
  const stats = useMemo(() => agentStats(scorecards, rubric, coaching), [scorecards, rubric, coaching]);
  const activeStat = useMemo(
    () => stats.find((s) => s.agentId === (activeAgent ?? stats[0]?.agentId)) ?? null,
    [stats, activeAgent],
  );

  const invalidateScorecards = () => queryClient.invalidateQueries({ queryKey: ["scorecards"] });
  const invalidateCoaching = () => queryClient.invalidateQueries({ queryKey: ["coaching-actions"] });
  const invalidateCalibrations = () =>
    queryClient.invalidateQueries({ queryKey: ["calibration-sessions"] });

  const saveMutation = useMutation({
    mutationFn: async ({ sc, entries }: { sc: Scorecard; entries: ScorecardEntry[] }) => {
      await saveScorecard(sc, entries);
    },
    onSuccess: (_data, vars) => {
      setDraftEntries((prev) => {
        const next = { ...prev };
        delete next[vars.sc.id];
        return next;
      });
      invalidateScorecards();
      toast.success("Draft saved");
    },
    onError: (err: Error) => toast.error("Could not save draft", { description: err.message }),
  });

  const publishMutation = useMutation({
    mutationFn: async ({ sc, entries }: { sc: Scorecard; entries: ScorecardEntry[] }) => {
      await finalizeScorecard(sc, entries);
    },
    onSuccess: (_data, vars) => {
      setDraftEntries((prev) => {
        const next = { ...prev };
        delete next[vars.sc.id];
        return next;
      });
      invalidateScorecards();
      toast.success("Scorecard published", { description: "Sent to agent + logged to audit trail." });
    },
    onError: (err: Error) => toast.error("Could not publish", { description: err.message }),
  });

  const updateEntries = (id: string, entries: ScorecardEntry[]) => {
    setDraftEntries((prev) => ({ ...prev, [id]: entries }));
  };
  const saveDraft = (id: string) => {
    const sc = scorecards.find((s) => s.id === id);
    if (!sc) return;
    saveMutation.mutate({ sc, entries: draftEntries[id] ?? sc.entries });
  };
  const publishScore = (id: string) => {
    const sc = scorecards.find((s) => s.id === id);
    if (!sc) return;
    publishMutation.mutate({ sc, entries: draftEntries[id] ?? sc.entries });
  };

  const openCoachFromScorecard = (s: Scorecard) => {
    setCoachPreset({ agent: s.agentId, scorecardId: s.id, callId: s.callId });
    setCoachOpen(true);
  };

  const moveCoachMutation = useMutation({
    mutationFn: ({ id, status }: { id: string; status: CoachingStatus }) =>
      patchCoachingAction(id, { status }),
    onSuccess: () => invalidateCoaching(),
    onError: (err: Error) => toast.error("Could not update coaching", { description: err.message }),
  });

  const createCoachMutation = useMutation({
    mutationFn: createCoachingAction,
    onSuccess: (item) => {
      invalidateCoaching();
      setCoachOpen(false);
      toast.success("Coaching action created", { description: `${item.agentId} · ${item.title}` });
    },
    onError: (err: Error) => toast.error("Could not create coaching", { description: err.message }),
  });

  const closeCalMutation = useMutation({
    mutationFn: (id: string) => patchCalibrationSession(id, { status: "closed" }),
    onSuccess: () => {
      invalidateCalibrations();
      toast.success("Calibration closed");
    },
    onError: (err: Error) => toast.error("Could not close calibration", { description: err.message }),
  });

  const moveCoaching = (id: string, status: CoachingStatus) => {
    moveCoachMutation.mutate({ id, status });
  };
  const openCoachDetail = (id: string) => {
    const a = coaching.find((c) => c.id === id);
    if (a) toast(a.title, { description: `${a.agentId} · ${a.category}` });
  };
  const addCoaching = (data: Omit<CoachingAction, "id" | "createdAt" | "notes" | "status">) => {
    createCoachMutation.mutate(data);
  };

  const closeCalibration = (id: string) => {
    closeCalMutation.mutate(id);
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
        <header className="shrink-0 border-b border-border bg-surface px-250 py-150">
          <div className="flex flex-wrap items-center gap-100">
            <h1 className="text-[1.25rem] font-semibold text-text">QA scorecards & coaching</h1>
            <Lozenge tone="neutral">QA Lead workspace</Lozenge>
            <div className="ml-auto flex items-center gap-100">
              <button
                onClick={() => setRubricOpen(true)}
                className="inline-flex items-center gap-050 rounded-medium border border-border px-150 py-075 text-body-small text-text hover:bg-surface-sunken"
              >
                <SlidersHorizontal className="h-3.5 w-3.5" /> Edit rubric
              </button>
              <button
                onClick={() => setTab("calibration")}
                className="inline-flex items-center gap-050 rounded-medium border border-border px-150 py-075 text-body-small text-text hover:bg-surface-sunken"
              >
                <Scale className="h-3.5 w-3.5" /> Calibrate
              </button>
            </div>
          </div>
          <p className="text-body-small text-text-subtle">
            Weighted rubric scoring (empathy, resolution, compliance, script, upsell) — AI-assisted drafts, human sign-off, then drives coaching.
          </p>
        </header>

        <QaStatsStrip scorecards={scorecards} coaching={coaching} calibrations={calibrations} rubric={rubric} />

        <div className="shrink-0 border-b border-border bg-surface px-250">
          <div className="flex gap-050">
            {TABS.map((t) => {
              const Icon = t.icon;
              return (
                <button
                  key={t.key}
                  onClick={() => setTab(t.key)}
                  className={cn(
                    "inline-flex items-center gap-075 border-b-2 px-150 py-100 text-body-small",
                    tab === t.key
                      ? "border-border-brand text-text-brand font-semibold"
                      : "border-transparent text-text-subtle hover:text-text",
                  )}
                >
                  <Icon className="h-3.5 w-3.5" />
                  {t.label}
                  {t.count !== undefined && (
                    <span className={cn(
                      "rounded-full px-075 py-025 text-body-small",
                      tab === t.key ? "bg-background-brand-subtlest text-text-brand" : "bg-surface-sunken text-text-subtlest",
                    )}>{t.count}</span>
                  )}
                </button>
              );
            })}
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-hidden bg-surface">
          {tab === "queue" && (
            <div className="grid h-full min-h-0 grid-cols-[320px_minmax(0,1fr)]">
              <ScoringQueue scorecards={scorecards} activeId={activeScoreId} onSelect={setActiveScoreId} rubric={rubric} />
              <ScoringCanvas
                scorecard={activeScore}
                rubric={rubric}
                onChangeEntries={updateEntries}
                onPublish={publishScore}
                onSaveDraft={saveDraft}
                onAssignCoaching={openCoachFromScorecard}
              />
            </div>
          )}

          {tab === "trends" && (
            <div className="h-full min-h-0 overflow-y-auto p-250">
              <div className="grid gap-200 xl:grid-cols-[minmax(0,1fr)_360px]">
                <AgentTrendsTable stats={stats} activeAgent={activeAgent ?? stats[0]?.agentId ?? null} onSelect={setActiveAgent} />
                <AgentTrendCard stat={activeStat} />
              </div>
            </div>
          )}

          {tab === "calibration" && (
            <div className="h-full min-h-0 overflow-y-auto p-250">
              <CalibrationView sessions={calibrations} onClose={closeCalibration} />
            </div>
          )}

          {tab === "coaching" && (
            <div className="h-full min-h-0 overflow-y-auto p-250">
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

      <RubricBuilderSheet
        open={rubricOpen}
        onClose={() => setRubricOpen(false)}
        rubric={rubric}
        onSave={(next) => setRubricOverride(next)}
      />
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
