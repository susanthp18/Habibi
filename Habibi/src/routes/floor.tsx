import { useEffect, useMemo, useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { toast } from "sonner";
import { AppShell } from "@/components/shell/AppShell";
import { StatsStrip } from "@/components/floor/StatsStrip";
import { FilterBar, type Filters } from "@/components/floor/FilterBar";
import { CallTile } from "@/components/floor/CallTile";
import { AlertLane } from "@/components/floor/AlertLane";
import { Skeleton } from "@/components/ui/skeleton";
import { useFloor, useSupervisorAction, type FloorSnapshot } from "@/api/floor";
import { USE_MOCK } from "@/api/config";
import type { ActiveCall } from "@/data/floor-seed";

export const Route = createFileRoute("/floor")({
  head: () => ({
    meta: [
      { title: "Floor Command Center — Live Ops" },
      {
        name: "description",
        content:
          "Supervisor cockpit for monitoring every active bot and human call in real time — listen in, whisper to agents, or barge in with force-handoff.",
      },
      { property: "og:title", content: "Floor Command Center — Live Ops" },
      {
        property: "og:description",
        content:
          "Live grid of active calls with sentiment, topics, and supervisor actions across bot + human handled sessions.",
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
        <div className="grid h-full place-items-center p-8">
          <Skeleton className="h-40 w-full max-w-3xl" />
        </div>
      ) : isError ? (
        <div className="grid h-full place-items-center text-[13px] text-rose-600">
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

  const [calls, setCalls] = useState<ActiveCall[]>(snapshot.calls);
  const [listeningId, setListeningId] = useState<string | null>(null);
  const [whisperId, setWhisperId] = useState<string | null>(null);
  const [flashId, setFlashId] = useState<string | null>(null);

  // Sync from server polls (live) — mock keeps local drift below.
  useEffect(() => {
    if (!USE_MOCK) setCalls(snapshot.calls);
  }, [snapshot.calls]);

  const [filters, setFilters] = useState<Filters>({
    q: "",
    channels: [],
    handler: "all",
    sentiment: "all",
    topic: "all",
    sort: "risk",
  });

  // Mock-only: local duration/sentiment tick for demo liveliness.
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

  const alerts = snapshot.alerts;

  const liveStats = useMemo(() => {
    const avg = calls.reduce((s, c) => s + c.sentiment, 0) / Math.max(calls.length, 1);
    const escalations = calls.filter((c) => c.handler.kind === "human").length;
    return {
      ...snapshot.stats,
      callsInProgress: calls.length,
      avgSentiment: Number(avg.toFixed(2)),
      escalationRate: Number((escalations / Math.max(calls.length, 1)).toFixed(2)),
      longestWaitSec: calls.length ? Math.max(...calls.map((c) => c.durationSec)) : 0,
    };
  }, [calls, snapshot.stats]);

  const filtered = useMemo(() => {
    const q = filters.q.trim().toLowerCase();
    let list = calls.filter((c) => {
      if (q) {
        const hay = `${c.customer} ${c.accountTail} ${c.handler.name} ${c.topic}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      if (filters.channels.length && !filters.channels.includes(c.channel)) return false;
      if (filters.handler !== "all" && c.handler.kind !== filters.handler) return false;
      if (filters.topic !== "all" && c.topic !== filters.topic) return false;
      if (filters.sentiment !== "all") {
        if (filters.sentiment === "positive" && !(c.sentiment > 0.25)) return false;
        if (filters.sentiment === "negative" && !(c.sentiment < -0.2)) return false;
        if (filters.sentiment === "neutral" && (c.sentiment > 0.25 || c.sentiment < -0.2)) return false;
      }
      return true;
    });

    list = [...list].sort((a, b) => {
      if (filters.sort === "duration") return b.durationSec - a.durationSec;
      if (filters.sort === "sentiment") return a.sentiment - b.sentiment;
      const rank = { high: 3, medium: 2, low: 1 } as const;
      return rank[b.risk] - rank[a.risk];
    });
    return list;
  }, [calls, filters]);

  const handleListenToggle = (id: string) => {
    setListeningId((prev) => {
      const next = prev === id ? null : id;
      if (next) {
        actionMut.mutate(
          { interactionId: id, action: "listen_in" },
          { onError: (e) => toast.error(e instanceof Error ? e.message : "Listen failed") },
        );
      }
      return next;
    });
  };

  const handleWhisperSubmit = (id: string, text: string) => {
    if (USE_MOCK) {
      setCalls((prev) =>
        prev.map((c) => (c.id === id ? { ...c, lastLine: `[whisper to agent] ${text}` } : c)),
      );
    }
    actionMut.mutate(
      { interactionId: id, action: "whisper", note: text },
      {
        onSuccess: () => toast.success("Whisper logged"),
        onError: (e) => toast.error(e instanceof Error ? e.message : "Whisper failed"),
      },
    );
    setWhisperId(null);
  };

  const handleBarge = (id: string) => {
    if (USE_MOCK) {
      setCalls((prev) =>
        prev.map((c) =>
          c.id === id
            ? {
                ...c,
                handler: { kind: "human", name: "You (supervisor)", initials: "SU" },
                lastLine: "[system] Supervisor took over the call.",
              }
            : c,
        ),
      );
    }
    actionMut.mutate(
      { interactionId: id, action: "barge" },
      {
        onSuccess: () => toast.success("Barge recorded"),
        onError: (e) => toast.error(e instanceof Error ? e.message : "Barge failed"),
      },
    );
  };

  const handleFocusAlert = (id: string) => {
    setFlashId(id);
    window.setTimeout(() => setFlashId(null), 1500);
  };

  return (
    <div className="flex h-full min-h-0 w-full flex-col overflow-hidden bg-surface-app">
      {!USE_MOCK && (
        <div className="shrink-0 border-b border-[var(--border-token)] bg-brand-tint/40 px-4 py-1.5 text-[11px] text-brand-primary-dark">
          Live floor · listen / whisper / barge write supervisor audit only (no media plane yet)
        </div>
      )}
      <StatsStrip stats={liveStats} />
      <FilterBar
        value={filters}
        onChange={setFilters}
        visibleCount={filtered.length}
        totalCount={calls.length}
      />

      <div className="xl:hidden">
        <AlertLane
          alerts={alerts}
          calls={calls}
          onFocus={handleFocusAlert}
          onListen={handleListenToggle}
          onBarge={handleBarge}
          compact
        />
      </div>

      <div className="flex min-h-0 flex-1 overflow-hidden">
        <div className="min-h-0 min-w-0 flex-1 overflow-y-auto px-4 py-4">
          {filtered.length === 0 ? (
            <div className="grid h-full place-items-center text-[13px] text-text-muted">
              {calls.length === 0 ? "No active calls right now." : "No calls match these filters."}
            </div>
          ) : (
            <div
              className="grid gap-3"
              style={{ gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))" }}
            >
              {filtered.map((call) => (
                <CallTile
                  key={call.id}
                  call={call}
                  listening={listeningId === call.id}
                  whisperOpen={whisperId === call.id}
                  onListenToggle={() => handleListenToggle(call.id)}
                  onWhisperOpen={() => setWhisperId(call.id)}
                  onWhisperClose={() => setWhisperId(null)}
                  onWhisperSubmit={(text) => handleWhisperSubmit(call.id, text)}
                  onBarge={() => handleBarge(call.id)}
                  flash={flashId === call.id}
                />
              ))}
            </div>
          )}
        </div>

        <AlertLane
          alerts={alerts}
          calls={calls}
          onFocus={handleFocusAlert}
          onListen={handleListenToggle}
          onBarge={handleBarge}
        />
      </div>
    </div>
  );
}
