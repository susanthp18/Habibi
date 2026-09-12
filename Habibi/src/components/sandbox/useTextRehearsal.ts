/**
 * The text rehearsal loop: create the run on first use, post a customer line
 * with the history so far, fold the exchange into the session.
 */
import { useCallback, useMemo, useState, type Dispatch } from "react";
import { toast } from "sonner";

import {
  appendSandboxTurn,
  createSandboxRun,
  isIntentKey,
  type SandboxChunkHit,
  type SandboxHistoryItem,
  type SandboxRun,
} from "@/api/sandbox";
import type { PromptVersion } from "@/api/types/prompt-studio";
import type { Scenario, SandboxTurn } from "@/api/types/sandbox";
import type { LiveToolCall } from "@/components/sandbox/voice/liveEvents";
import type { SandboxMode } from "@/components/sandbox/SandboxHeader";
import { mergeSandboxChunkMeta } from "@/lib/sandbox";
import { makeId } from "./sessionOpening";
import type { SandboxSession, SandboxSessionAction } from "./sandboxSession";

export function useTextRehearsal({
  scenario,
  activePrompt,
  kbSnapshotId,
  skillSlug,
  mode,
  session,
  dispatch,
}: {
  scenario: Scenario | undefined;
  activePrompt: PromptVersion | undefined;
  kbSnapshotId: string;
  skillSlug: string;
  mode: SandboxMode;
  session: SandboxSession;
  dispatch: Dispatch<SandboxSessionAction>;
}) {
  const { turns, scriptIndex, run, halted, flowNode } = session;
  const [awaiting, setAwaiting] = useState(false);

  const ensureRun = useCallback(async (): Promise<SandboxRun> => {
    if (run && run.status === "running") return run;
    if (!scenario || !activePrompt) throw new Error("Scenario / prompt not ready");
    const created = await createSandboxRun({
      promptVersionId: activePrompt.id,
      scenarioId: scenario.id,
      scenarioTitle: scenario.title,
      kbSnapshotId: kbSnapshotId === "current" ? null : kbSnapshotId,
      openingTemplate: scenario.openingBot,
      persona: scenario.persona,
    });
    dispatch({ type: "run", run: created });
    if (created.openingMessage) {
      dispatch({
        type: "turns",
        value: (prev) => {
          const withoutOpening = prev.filter((t) => t.role !== "bot");
          const system = withoutOpening.find((t) => t.role === "system");
          return [
            system ?? {
              id: makeId(),
              role: "system" as const,
              text: `New session · ${scenario.title}`,
              ts: Date.now(),
              systemKind: "info" as const,
            },
            {
              id: makeId(),
              role: "bot" as const,
              text: created.openingMessage!,
              ts: Date.now(),
              chunkIds: [],
              latencyMs: 0,
              tokens: 0,
            },
          ];
        },
      });
    }
    return created;
  }, [run, scenario, activePrompt, kbSnapshotId]);

  const handleCustomerText = useCallback(
    async (text: string, fromScript: boolean) => {
      if (!scenario || !activePrompt || halted || mode !== "text") return;
      setAwaiting(true);
      try {
        const activeRun = await ensureRun();
        const history: SandboxHistoryItem[] = turns
          .filter((t) => t.role === "bot" || t.role === "customer")
          .map((t) => ({ role: t.role as "bot" | "customer", text: t.text }));

        const result = await appendSandboxTurn({
          runId: activeRun.id,
          text,
          history,
          skillSlug: skillSlug || undefined,
          nodeKey: flowNode,
          scenario,
          turnIndex: fromScript
            ? scriptIndex
            : Math.min(scriptIndex, Math.max(0, scenario.turns.length - 1)),
          personaState: activePrompt.persona,
          guardrails: activePrompt.guardrails,
        });

        const intentKey = isIntentKey(result.customerTurn.intent)
          ? result.customerTurn.intent
          : undefined;
        const customerTurn: SandboxTurn = {
          id: result.customerTurn.id,
          role: "customer",
          text: result.customerTurn.text,
          ts: Date.now(),
          intent: intentKey,
          intentScores: result.customerTurn.intentScores as SandboxTurn["intentScores"],
          sentiment: result.customerTurn.sentiment,
        };
        const chunks: SandboxChunkHit[] = result.botTurn.chunks ?? [];
        mergeSandboxChunkMeta(chunks);
        const botTurn: SandboxTurn = {
          id: result.botTurn.id,
          role: "bot",
          text: result.botTurn.text,
          ts: Date.now(),
          chunkIds: result.botTurn.chunkIds,
          chunks,
          latencyMs: result.botTurn.latencyMs,
          tokens: result.botTurn.tokens,
          guardrailFlags: result.botTurn.guardrailFlags,
        };

        const added: SandboxTurn[] = [customerTurn, botTurn];
        {
          const next = added;
          if (result.botTurn.guardrailFlags.includes("auto-escalate")) {
            next.push({
              id: makeId(),
              role: "system",
              text: "Auto-escalation triggered · routing to Tier 2",
              ts: Date.now(),
              systemKind: "warn",
            });
          }
          if (result.botTurn.halted) {
            next.push({
              id: makeId(),
              role: "system",
              text: `Run halted · guardrail ${result.botTurn.guardrailFlags.join(", ")}`,
              ts: Date.now(),
              systemKind: "warn",
            });
          }
        }

        const simulatedCalls = (result.botTurn.toolCalls ?? []).map((call, i): LiveToolCall => {
          const at = Date.now();
          return {
            id: `${result.botTurn.id}-${call.name}-${i}`,
            name: call.name,
            status: call.ok ? "done" : "error",
            result: call.result,
            startedAt: at,
            endedAt: at,
          };
        });
        dispatch({
          type: "exchange",
          turns: added,
          toolCalls: simulatedCalls,
          nodeKey: result.nodeKey,
          halted: Boolean(result.botTurn.halted),
          fromScript,
        });
        return !result.botTurn.halted;
      } catch (err) {
        toast.error(err instanceof Error ? err.message : "Sandbox turn failed");
        return false;
      } finally {
        setAwaiting(false);
      }
    },
    [scenario, activePrompt, halted, ensureRun, turns, scriptIndex, mode, skillSlug, flowNode],
  );

  const playNext = useCallback(() => {
    if (!scenario) return;
    const nextTurn = scenario.turns[scriptIndex];
    if (!nextTurn) return;
    void handleCustomerText(nextTurn.customer, true);
  }, [scenario, scriptIndex, handleCustomerText]);

  const skipEnd = useCallback(() => {
    if (!scenario || awaiting || halted) return;
    const remaining = scenario.turns.slice(scriptIndex, scriptIndex + 3).map((t) => t.customer);
    if (remaining.length === 0) return;
    void (async () => {
      for (const text of remaining) {
        const ok = await handleCustomerText(text, true);
        if (!ok) break;
      }
    })();
  }, [scenario, scriptIndex, awaiting, halted, handleCustomerText]);

  const canPlayNext = useMemo(() => {
    if (!scenario || halted || awaiting || mode !== "text") return false;
    return scriptIndex < scenario.turns.length;
  }, [scriptIndex, scenario, halted, awaiting, mode]);

  return { awaiting, handleCustomerText, playNext, skipEnd, canPlayNext };
}
