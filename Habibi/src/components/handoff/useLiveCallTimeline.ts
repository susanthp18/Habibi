import { useEffect, useMemo, useRef, useState } from "react";
import { acceptHandoffSuggestion, postHandoffDisclosure, type HandoffSession } from "@/api/handoff";
import type { Suggestion, TranscriptTurn } from "@/api/types/handoff";

const TICK_MS = 500;

/**
 * What the live call looks like as time passes: the transcript as it is
 * revealed, the sentiment trace, the compliance items that auto-tick, and the
 * suggestions that become relevant. A scripted replay (`mock`) advances these
 * on a timer from the session's script; a real call takes them from the
 * session as the server updates it.
 */
export function useLiveCallTimeline({
  session,
  mock,
  ended,
}: {
  session: HandoffSession;
  mock: boolean;
  ended: boolean;
}) {
  const { activeCall, transcriptScript, suggestions, complianceItems, sentimentSeries } = session;
  const [elapsed, setElapsed] = useState(0);
  const [visibleTurns, setVisibleTurns] = useState<TranscriptTurn[]>(mock ? [] : transcriptScript);
  const [insertedTurns, setInsertedTurns] = useState<TranscriptTurn[]>([]);
  const [insertedIds, setInsertedIds] = useState<Set<string>>(new Set());
  const [sentiment, setSentiment] = useState<number[]>(() =>
    sentimentSeries.length
      ? sentimentSeries
      : Array.from({ length: 40 }, (_, i) => -0.05 + Math.sin(i / 6) * 0.05),
  );
  const [compliance, setCompliance] = useState<Record<string, boolean>>(() => {
    const init: Record<string, boolean> = {};
    for (const item of complianceItems) {
      if (item.checked) init[item.id] = true;
    }
    return init;
  });
  const startedAtRef = useRef<number>(activeCall.startedAt || Date.now());

  useEffect(() => {
    if (mock) return;
    setVisibleTurns(transcriptScript);
    if (sentimentSeries.length) setSentiment(sentimentSeries);
    setCompliance((prev) => {
      const next = { ...prev };
      for (const item of complianceItems) {
        if (item.checked) next[item.id] = true;
      }
      return next;
    });
  }, [mock, transcriptScript, sentimentSeries, complianceItems]);

  useEffect(() => {
    if (ended) return;
    if (!mock) {
      const tick = () => {
        const start = activeCall.startedAt || Date.now();
        setElapsed(Math.max(0, Math.floor((Date.now() - start) / 1000)));
      };
      tick();
      const iv = window.setInterval(tick, 1000);
      return () => window.clearInterval(iv);
    }
    const iv = window.setInterval(() => {
      const secs = Math.floor((Date.now() - startedAtRef.current) / 1000);
      setElapsed(secs);
      setVisibleTurns((prev) => {
        const revealed = transcriptScript.filter((t) => t.at <= secs);
        if (revealed.length === prev.length) return prev;
        return revealed;
      });
      setSentiment((prev) => {
        const scriptBeat = [...transcriptScript]
          .reverse()
          .find((t) => t.at <= secs && t.sentimentDelta !== undefined);
        const anchor = scriptBeat?.sentimentDelta ?? 0;
        const last = prev[prev.length - 1] ?? 0;
        const target = Math.max(
          -1,
          Math.min(1, last + anchor * 0.08 + (Math.random() - 0.5) * 0.04),
        );
        return [...prev.slice(-59), target];
      });
    }, TICK_MS);
    return () => window.clearInterval(iv);
  }, [ended, mock, transcriptScript, activeCall.startedAt]);

  const allTurns = useMemo(() => {
    const byId = new Map<string, TranscriptTurn>();
    for (const t of [...visibleTurns, ...insertedTurns]) byId.set(t.id, t);
    return [...byId.values()].sort((a, b) => a.at - b.at);
  }, [visibleTurns, insertedTurns]);

  const latestSpeaker = allTurns[allTurns.length - 1]?.speaker;
  const nextScripted = mock ? transcriptScript.find((t) => t.at > elapsed) : undefined;
  const streaming = !ended && (mock ? !!nextScripted : session.status === "active");

  useEffect(() => {
    if (!mock) return;
    setCompliance((prev) => {
      let changed = false;
      const next = { ...prev };
      for (const item of complianceItems) {
        if (item.autoAt !== undefined && elapsed >= item.autoAt && !next[item.id]) {
          next[item.id] = true;
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [elapsed, complianceItems, mock]);

  const activeSuggestions: Suggestion[] = useMemo(() => {
    return suggestions.filter((s) => {
      if (insertedIds.has(s.id)) return false;
      if ("accepted" in s && (s as Suggestion & { accepted?: boolean }).accepted) return false;
      if (mock) return elapsed >= s.showAfter;
      return true;
    });
  }, [suggestions, elapsed, insertedIds, mock]);

  const handleInsertSuggestion = (s: Suggestion) => {
    setInsertedIds((prev) => new Set(prev).add(s.id));
    setInsertedTurns((prev) => [
      ...prev,
      { id: `ins-${s.id}`, speaker: "agent", text: s.body, at: elapsed },
    ]);
    if (!mock && !s.id.startsWith("canned-")) {
      void acceptHandoffSuggestion(session.interactionId, s.id).catch(() => undefined);
    }
  };

  const handleToggleCompliance = (id: string) => {
    const item = complianceItems.find((c) => c.id === id);
    if (item?.locked) return;
    const next = !compliance[id];
    setCompliance((prev) => ({ ...prev, [id]: next }));
    if (!mock) {
      void postHandoffDisclosure(session.interactionId, {
        itemId: id,
        ruleId: item?.ruleId,
        label: item?.label,
        read: next,
      });
    }
  };

  return {
    elapsed,
    allTurns,
    latestSpeaker,
    streaming,
    sentiment,
    compliance,
    activeSuggestions,
    handleInsertSuggestion,
    handleToggleCompliance,
  };
}
