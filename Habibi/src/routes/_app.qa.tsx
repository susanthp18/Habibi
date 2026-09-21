import { useEffect, useMemo, useRef, useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { toast } from "sonner";
import { ClipboardCheck, Scale, SlidersHorizontal } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { QaStatsStrip } from "@/components/qa/QaStatsStrip";
import { ScoringQueue } from "@/components/qa/ScoringQueue";
import { ScoringCanvas } from "@/components/qa/ScoringCanvas";
import { AgentTrendsTable } from "@/components/qa/AgentTrendsTable";
import { AgentTrendCard } from "@/components/qa/AgentTrendCard";
import { CalibrationView } from "@/components/qa/CalibrationView";
import { DisagreementsView } from "@/components/qa/DisagreementsView";
import { CoachingBoard } from "@/components/qa/CoachingBoard";
import { NewCoachingSheet } from "@/components/qa/NewCoachingSheet";
import { RubricBuilderSheet } from "@/components/qa/RubricBuilderSheet";
import {
  useCalibrationSessions,
  useCoachingActions,
  useQaCoverage,
  useRubric,
  useScorecards,
  useSaveScorecard,
  useFinalizeScorecard,
  useMoveCoachingAction,
  useCreateCoachingAction,
  useCloseCalibrationSession,
} from "@/api/qa";
import { useQaDisagreements } from "@/api/agent-studio";
import { Lozenge } from "@/components/ui/lozenge";
import type {
  Scorecard,
  ScorecardEntry,
  CoachingAction,
  CoachingStatus,
  Rubric,
} from "@/api/types/qa";
import { agentStats, matchQaAgent } from "@/lib/qa";
import { QueryState } from "@/components/ui/query-state";

type Tab = "queue" | "trends" | "calibration" | "disagreements" | "coaching";

export const Route = createFileRoute("/_app/qa")({
  validateSearch: (search: Record<string, unknown>): { callId?: string; agent?: string } => ({
    callId: typeof search.callId === "string" ? search.callId : undefined,
    agent: typeof search.agent === "string" && search.agent.length > 0 ? search.agent : undefined,
  }),
  head: () => ({
    meta: [
      { title: "QA Scorecards & Coaching — PayInt" },
      {
        name: "description",
        content:
          "Score bot and agent interactions against a weighted rubric, run calibration sessions, and assign coaching actions.",
      },
      { property: "og:title", content: "QA Scorecards & Coaching" },
      {
        property: "og:description",
        content:
          "Rubric-driven quality scoring with AI-assisted suggestions, agent trends, calibration, and coaching workflow.",
      },
    ],
  }),
  component: QaPage,
});

function QaPage() {
  const rubricQuery = useRubric();
  return (
    <QueryState query={rubricQuery} label="the rubric">
      {rubricQuery.data && <QaWorkspace remoteRubric={rubricQuery.data} />}
    </QueryState>
  );
}

function QaWorkspace({ remoteRubric }: { remoteRubric: Rubric }) {
  const { callId, agent } = Route.useSearch();
  const {
    data: remoteScorecards,
    isPending: scorecardsPending,
    isError: scorecardsError,
    error: scorecardsErr,
  } = useScorecards();
  const { data: remoteCoaching } = useCoachingActions();
  const { data: remoteCalibrations } = useCalibrationSessions();
  const { data: coverage } = useQaCoverage();
  // Fetched at the route so the tab can carry a count without mounting the
  // panel — a disagreement the lead cannot see is one nobody acts on.
  const disagreements = useQaDisagreements();
  const [activeScoreId, setActiveScoreId] = useState<string | null>(null);
  const activeRubricId = (remoteScorecards ?? []).find((s) => s.id === activeScoreId)?.rubricId;
  const { data: channelRubric } = useRubric(activeRubricId);

  // Local rubric edits (builder sheet) — live GET /rubric is the base.
  const [rubricOverride, setRubricOverride] = useState<Rubric | null>(null);
  const rubric = rubricOverride ?? remoteRubric;
  const canvasRubric = rubricOverride ?? channelRubric ?? rubric;

  // In-progress criterion edits until Save draft / Publish.
  const [draftEntries, setDraftEntries] = useState<Record<string, ScorecardEntry[]>>({});

  const coaching = remoteCoaching ?? [];
  const calibrations = remoteCalibrations ?? [];

  const scorecards = useMemo(() => {
    const base = remoteScorecards ?? [];
    return base.map((s) => (draftEntries[s.id] ? { ...s, entries: draftEntries[s.id]! } : s));
  }, [remoteScorecards, draftEntries]);

  const [tab, setTab] = useState<Tab>("queue");
  const [activeAgent, setActiveAgent] = useState<string | null>(null);
  const [rubricOpen, setRubricOpen] = useState(false);
  const [coachOpen, setCoachOpen] = useState(false);
  const [coachPreset, setCoachPreset] = useState<{
    agent?: string;
    scorecardId?: string;
    callId?: string;
  }>({});

  useEffect(() => {
    if (activeScoreId) return;
    if (callId) {
      const match = scorecards.find((s) => s.callId === callId);
      if (match) {
        setActiveScoreId(match.id);
        return;
      }
    }
    const first = scorecards.find((s) => s.status !== "final") ?? scorecards[0];
    if (first) setActiveScoreId(first.id);
  }, [scorecards, activeScoreId, callId]);

  const activeScore = useMemo(
    () => scorecards.find((s) => s.id === activeScoreId) ?? null,
    [scorecards, activeScoreId],
  );
  const stats = useMemo(
    () => agentStats(scorecards, rubric, coaching),
    [scorecards, rubric, coaching],
  );
  const activeStat = useMemo(
    () => stats.find((s) => s.agentId === (activeAgent ?? stats[0]?.agentId)) ?? null,
    [stats, activeAgent],
  );

  const appliedAgent = useRef<string | null>(null);
  useEffect(() => {
    if (!agent) return;
    if (appliedAgent.current !== agent) {
      setTab("trends");
      appliedAgent.current = agent;
    }
    const hit = matchQaAgent(stats, agent);
    if (hit) setActiveAgent(hit.agentId);
  }, [agent, stats]);

  const updateEntries = (id: string, entries: ScorecardEntry[]) => {
    setDraftEntries((prev) => ({ ...prev, [id]: entries }));
  };
  const saveDraft = (id: string) => {
    const sc = scorecards.find((s) => s.id === id);
    if (!sc) return;
    saveMutation.mutate(
      { sc, entries: draftEntries[id] ?? sc.entries },
      { onSuccess: () => dropDraft(id) },
    );
  };
  const publishScore = (id: string) => {
    const sc = scorecards.find((s) => s.id === id);
    if (!sc) return;
    publishMutation.mutate(
      { sc, entries: draftEntries[id] ?? sc.entries },
      { onSuccess: () => dropDraft(id) },
    );
  };

  const openCoachFromScorecard = (s: Scorecard) => {
    setCoachPreset({ agent: s.agentId, scorecardId: s.id, callId: s.callId });
    setCoachOpen(true);
  };

  const saveMutation = useSaveScorecard();
  const publishMutation = useFinalizeScorecard();
  const moveCoachMutation = useMoveCoachingAction();
  const createCoachMutation = useCreateCoachingAction();
  const closeCalMutation = useCloseCalibrationSession();
  // The draft overlay for a scorecard clears once the row is written.
  const dropDraft = (id: string) =>
    setDraftEntries((prev) => {
      const next = { ...prev };
      delete next[id];
      return next;
    });

  const moveCoaching = (id: string, status: CoachingStatus) => {
    moveCoachMutation.mutate({ id, status });
  };
  const openCoachDetail = (id: string) => {
    const a = coaching.find((c) => c.id === id);
    if (a) toast(a.title, { description: `${a.agentId} · ${a.category}` });
  };
  const addCoaching = (data: Omit<CoachingAction, "id" | "createdAt" | "notes" | "status">) => {
    createCoachMutation.mutate(data, { onSuccess: () => setCoachOpen(false) });
  };

  const closeCalibration = (id: string) => {
    closeCalMutation.mutate(id);
  };

  const TABS: Array<{ key: Tab; label: string; icon: LucideIcon; count?: number }> = [
    {
      key: "queue",
      label: "Scoring Queue",
      icon: ClipboardCheck,
      count: scorecards.filter((s) => s.status !== "final").length,
    },
    { key: "trends", label: "Agent Trends", icon: SlidersHorizontal, count: stats.length },
    {
      key: "calibration",
      label: "Calibration",
      icon: Scale,
      count: calibrations.filter((c) => c.status === "active").length,
    },
    // Beside Calibration: both are about the rubric rather than about one
    // agent, and a disagreement is the strongest evidence a calibration
    // session has to work with.
    {
      key: "disagreements",
      label: "Disagreements",
      icon: Scale,
      count: disagreements.data?.count,
    },
    {
      key: "coaching",
      label: "Coaching",
      icon: ClipboardCheck,
      count: coaching.filter((c) => c.status !== "done").length,
    },
  ];

  return (
    <>
      <div className="flex h-full min-h-0 flex-col">
        <header className="shrink-0 border-b border-border bg-surface px-250 py-150">
          <div className="flex flex-wrap items-center gap-100">
            <h1 className="heading-medium font-semibold text-text">QA scorecards & coaching</h1>
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
            Weighted rubric scoring (empathy, resolution, compliance, script, upsell) — AI-assisted
            drafts, human sign-off, then drives coaching.
          </p>
        </header>

        <QaStatsStrip
          scorecards={scorecards}
          coaching={coaching}
          calibrations={calibrations}
          rubric={rubric}
          coverage={coverage}
        />

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
                    <span
                      className={cn(
                        "rounded-full px-075 py-025 text-body-small",
                        tab === t.key
                          ? "bg-background-brand-subtlest text-text-brand"
                          : "bg-surface-sunken text-text-subtlest",
                      )}
                    >
                      {t.count}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-hidden bg-surface">
          {tab === "queue" && (
            <div className="grid h-full min-h-0 grid-cols-[320px_minmax(0,1fr)]">
              <ScoringQueue
                scorecards={scorecards}
                activeId={activeScoreId}
                onSelect={setActiveScoreId}
                rubric={rubric}
              />
              <ScoringCanvas
                scorecard={activeScore}
                rubric={canvasRubric}
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
                <AgentTrendsTable
                  stats={stats}
                  activeAgent={activeAgent ?? stats[0]?.agentId ?? null}
                  onSelect={setActiveAgent}
                  isLoading={scorecardsPending}
                  isError={scorecardsError}
                  error={scorecardsErr}
                />
                <AgentTrendCard stat={activeStat} />
              </div>
            </div>
          )}

          {tab === "calibration" && (
            <div className="h-full min-h-0 overflow-y-auto p-250">
              <CalibrationView sessions={calibrations} rubric={rubric} onClose={closeCalibration} />
            </div>
          )}

          {tab === "disagreements" && (
            <div className="h-full min-h-0 overflow-y-auto p-250">
              <DisagreementsView />
            </div>
          )}

          {tab === "coaching" && (
            <div className="h-full min-h-0 overflow-y-auto p-250">
              <CoachingBoard
                actions={coaching}
                onMove={moveCoaching}
                onNew={() => {
                  setCoachPreset({});
                  setCoachOpen(true);
                }}
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
        agents={stats.map((s) => s.agentId)}
        presetAgent={coachPreset.agent}
        presetScorecardId={coachPreset.scorecardId}
        presetCallId={coachPreset.callId}
      />
    </>
  );
}
