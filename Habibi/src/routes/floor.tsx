import { useEffect, useMemo, useState } from "react";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { toast } from "sonner";
import { AppShell } from "@/components/shell/AppShell";
import { StatsStrip, type FloorFocus } from "@/components/floor/StatsStrip";
import { WorkforceStrip } from "@/components/floor/WorkforceStrip";
import { FilterBar, type Filters } from "@/components/floor/FilterBar";
import { PriorityLane } from "@/components/floor/PriorityLane";
import { LiveTable } from "@/components/floor/LiveTable";
import { Inspector } from "@/components/floor/Inspector";
import { ApprovalsQueue } from "@/components/floor/ApprovalsQueue";
import { LoadingState } from "@/components/ui/loading-state";
import { useAckFloorAlert, useFloor, useSupervisorAction, type FloorSnapshot } from "@/api/floor";
import { USE_MOCK } from "@/api/config";
import type { ActiveCall, FloorAction, FloorAlert } from "@/data/floor-seed";

export const Route = createFileRoute("/floor")({
  head: () => ({
    meta: [
      { title: "Floor Command — Live Ops" },
      {
        name: "description",
        content:
          "Supervisor console for live exceptions, agent presence, and intervention across bot and human sessions.",
      },
    ],
  }),
  component: FloorPage,
});

function FloorPage() {
  const { data, isLoading, isError, error } = useFloor();
  return (
    <AppShell>
      {isLoading && !data ? (
        <div className="grid h-full place-items-center p-400">
          <LoadingState label="Loading floor" />
        </div>
      ) : isError && !data ? (
        <div className="grid h-full place-items-center text-body text-text-danger">
          {error instanceof Error ? error.message : "Failed to load floor"}
        </div>
      ) : data ? (
        <FloorLive initial={data} />
      ) : null}
    </AppShell>
  );
}

function FloorLive({ initial }: { initial: FloorSnapshot }) {
  const { data } = useFloor();
  const snapshot = data ?? initial;
  const actionMut = useSupervisorAction();
  const ackMut = useAckFloorAlert();
  const navigate = useNavigate();

  const [calls, setCalls] = useState<ActiveCall[]>(snapshot.calls);
  const [alerts, setAlerts] = useState<FloorAlert[]>(snapshot.alerts);
  const [listeningId, setListeningId] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [focus, setFocus] = useState<FloorFocus>("all");
  const [filters, setFilters] = useState<Filters>({ q: "", channels: [], handler: "all" });

  useEffect(() => {
    if (!USE_MOCK) {
      setCalls(snapshot.calls);
      setAlerts(snapshot.alerts);
    }
  }, [snapshot.calls, snapshot.alerts]);

  useEffect(() => {
    if (!USE_MOCK) return;
    const iv = window.setInterval(() => {
      setCalls((prev) =>
        prev.map((c) => {
          const baseDrift = c.handler.kind === "bot" ? 0 : c.sentiment < 0 ? -0.01 : 0.005;
          const noise = (Math.random() - 0.5) * 0.03;
          const next = Math.max(-1, Math.min(1, c.sentiment + baseDrift + noise));
          return {
            ...c,
            durationSec: c.durationSec + 1,
            sentiment: next,
            sentimentTrend: next - c.sentiment,
          };
        }),
      );
    }, 1000);
    return () => window.clearInterval(iv);
  }, []);

  const liveStats = useMemo(() => {
    const avg = calls.reduce((s, c) => s + c.sentiment, 0) / Math.max(calls.length, 1);
    return {
      ...snapshot.stats,
      callsInProgress: calls.length,
      avgSentiment: Number(avg.toFixed(2)),
      criticalAlerts: alerts.filter((a) => a.severity >= 3).length,
      botAtRisk: calls.filter((c) => c.handler.kind === "bot" && c.risk !== "low").length,
    };
  }, [calls, alerts, snapshot.stats]);

  const filtered = useMemo(() => {
    const q = filters.q.trim().toLowerCase();
    return calls.filter((c) => {
      if (q) {
        const hay = `${c.customer} ${c.accountTail} ${c.handler.name} ${c.topic}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      if (filters.channels.length && !filters.channels.includes(c.channel)) return false;
      if (filters.handler !== "all" && c.handler.kind !== filters.handler) return false;
      if (focus === "critical") {
        const flagged = alerts.some((a) => a.callId === c.id && a.severity >= 3);
        if (!(c.risk === "high" || flagged)) return false;
      }
      if (focus === "queue" && !c.pendingHandoff) return false;
      if (focus === "bot-risk" && !(c.handler.kind === "bot" && c.risk !== "low")) return false;
      if (focus === "human" && c.handler.kind !== "human") return false;
      return true;
    });
  }, [calls, filters, focus, alerts]);

  const selected = calls.find((c) => c.id === selectedId) ?? null;

  const runAction = (id: string, action: FloorAction, note?: string) => {
    const call = calls.find((c) => c.id === id);
    if (!call) return;

    if (action === "inbox") {
      void navigate({
        to: "/inbox",
        search: { conversationId: call.conversationId ?? undefined },
      });
      return;
    }

    if (action === "listen") {
      const turningOn = listeningId !== id;
      setListeningId(turningOn ? id : null);
      setSelectedId(id);
      if (turningOn) {
        actionMut.mutate(
          { interactionId: id, action: "listen_in" },
          { onError: (e) => toast.error(e instanceof Error ? e.message : "Listen failed") },
        );
        toast.message("Listening logged — transcript is in the inspector. Live audio is not on this plane yet.");
      }
      return;
    }

    if (action === "whisper") {
      setSelectedId(id);
      if (note) {
        actionMut.mutate(
          { interactionId: id, action: "whisper", note },
          {
            onSuccess: () => toast.success("Whisper logged"),
            onError: (e) => toast.error(e instanceof Error ? e.message : "Whisper failed"),
          },
        );
      }
      return;
    }

    if (USE_MOCK) {
      setCalls((prev) =>
        prev.map((c) =>
          c.id === id
            ? {
                ...c,
                handler: { kind: "human", name: "You (supervisor)", initials: "SU" },
                lastLine: "[system] Supervisor took over the call.",
                pendingHandoff: false,
              }
            : c,
        ),
      );
    }
    actionMut.mutate(
      { interactionId: id, action: "barge" },
      {
        onSuccess: (data) => {
          const joined = Boolean(data && typeof data === "object" && "audioJoined" in data && data.audioJoined);
          toast.success(joined ? "Taken over — you are on the live call" : "Handoff taken — CRM takeover (no Twilio leg)");
          void navigate({
            to: "/handoff",
            search: { interactionId: id, customerId: call.customerId },
          });
        },
        onError: (e) => toast.error(e instanceof Error ? e.message : "Barge failed"),
      },
    );
  };

  const handleAck = (alertId: string) => {
    if (USE_MOCK) setAlerts((prev) => prev.filter((a) => a.id !== alertId));
    ackMut.mutate(alertId, {
      onError: (e) => toast.error(e instanceof Error ? e.message : "Ack failed"),
    });
  };

  return (
    <div className="flex h-full min-h-0 w-full flex-col overflow-hidden bg-surface">
      {!USE_MOCK && (
        <div className="shrink-0 border-b border-border bg-background-brand-subtlest/40 px-200 py-075 text-body-small text-text-brand">
          Live floor · Listen is the transcript. Whisper coaches the next bot turn. Barge takes over a live Twilio call.
        </div>
      )}
      <StatsStrip stats={liveStats} focus={focus} onFocus={setFocus} />
      <WorkforceStrip
        agents={snapshot.agents}
        onSelect={(id) => {
          if (id) setSelectedId(id);
        }}
      />
      <ApprovalsQueue />
      <PriorityLane
        alerts={alerts}
        calls={calls}
        onFocus={(id) => setSelectedId(id)}
        onAction={(id, action) => runAction(id, action)}
        onAck={handleAck}
      />
      <FilterBar
        value={filters}
        onChange={setFilters}
        visibleCount={filtered.length}
        totalCount={calls.length}
      />

      <div className="relative flex min-h-0 flex-1 overflow-hidden">
        <LiveTable rows={filtered} activeId={selectedId} onSelect={(c) => setSelectedId(c.id)} />
        {selected && (
          <div className="absolute inset-y-0 right-0 z-20 flex shadow-overlay xl:static xl:z-auto xl:shadow-none">
            <Inspector
              call={selected}
              listening={listeningId === selected.id}
              onClose={() => setSelectedId(null)}
              onAction={(action, call) => runAction(call.id, action)}
              onWhisper={(text) => runAction(selected.id, "whisper", text)}
            />
          </div>
        )}
      </div>
    </div>
  );
}
