import { useState } from "react";
import { toast } from "sonner";

import { type CheckRun, useCheckRuns, useCheckScenarios, useRunChecks } from "@/api/voice-studio";
import { apiErrorMessage } from "@/api/config";
import { can, useMe } from "@/api/me";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { QueryState } from "@/components/ui/query-state";

import { AgentPicker } from "./AgentPicker";
import { CheckRunCard as RunCard } from "./CheckRunCard";
import { passRates } from "./check-trend";

/**
 * Scripted rehearsals of a Voice Studio agent. Each scenario's customer lines
 * play into the agent's text chat (tools answer from the scenario, nothing real
 * is recorded) and every agent turn is graded against the agent's guardrails.
 */
export default function ChecksPage() {
  const [agentId, setAgentId] = useState<number | null>(null);
  const scenarios = useCheckScenarios();
  const runs = useCheckRuns(agentId);
  const run = useRunChecks(agentId);
  const { data: me } = useMe();
  const [picked, setPicked] = useState<string[]>([]);
  const running = runs.data?.some((r) => r.status === "running") ?? false;

  const start = () =>
    run.mutate(picked, {
      onSuccess: () => toast.success("Checks started. Results appear here in about a minute."),
      onError: (e) => toast.error(`Could not start: ${apiErrorMessage(e)}`),
    });

  return (
    <div className="mx-auto max-w-[64rem] space-y-300 p-300">
      <header className="space-y-050">
        <h1 className="heading-medium font-semibold">Checks</h1>
        <p className="text-body-small text-text-subtle">
          Play scripted customers through an agent and grade every reply against its guardrails.
          Nothing is recorded against real customers.
        </p>
      </header>
      <AgentPicker value={agentId} onChange={setAgentId} />
      <QueryState query={scenarios} label="scenarios">
        <section className="space-y-100">
          <p className="text-body font-semibold text-text">Scenarios</p>
          <p className="text-body-small text-text-subtle">None ticked runs them all.</p>
          <ul className="grid gap-100 sm:grid-cols-2">
            {(scenarios.data ?? []).map((s) => (
              <li
                key={s.id}
                className="flex items-start gap-100 rounded-medium border border-border p-150"
              >
                <Checkbox
                  id={`vs-scn-${s.id}`}
                  checked={picked.includes(s.id)}
                  onCheckedChange={(v) =>
                    setPicked((p) => (v ? [...p, s.id] : p.filter((x) => x !== s.id)))
                  }
                />
                <label htmlFor={`vs-scn-${s.id}`} className="space-y-050">
                  <span className="block text-body font-semibold text-text">{s.name}</span>
                  <span className="block text-body-small text-text-subtle">{s.turns[0]}</span>
                </label>
              </li>
            ))}
          </ul>
          <div className="flex justify-end">
            <Button
              variant="primary"
              disabled={agentId === null || running || !can(me, "perm-eval-run")}
              loading={run.isPending}
              onClick={start}
            >
              {running ? "Running…" : "Run checks"}
            </Button>
          </div>
        </section>
      </QueryState>
      {agentId !== null && (
        <QueryState
          query={runs}
          label="check runs"
          empty={
            (runs.data ?? []).length === 0 ? (
              <p className="text-body-small text-text-subtle">No runs yet.</p>
            ) : null
          }
        >
          <PassRateTrend runs={runs.data ?? []} />
          <ul className="space-y-150">
            {(runs.data ?? []).map((r) => (
              <RunCard key={r.id} run={r} />
            ))}
          </ul>
        </QueryState>
      )}
    </div>
  );
}

function PassRateTrend({ runs }: { runs: CheckRun[] }) {
  const points = passRates(runs);
  if (points.length < 2) return null;
  const latest = points[points.length - 1]!;
  return (
    <section className="space-y-100 rounded-medium border border-border p-150">
      <p className="text-body-small text-text-subtle">
        Pass rate over the last {points.length} runs: {points[0]!.pct}% → {latest.pct}%
      </p>
      <ol className="flex h-[3rem] items-end gap-050" aria-label="Pass rate by run, oldest first">
        {points.map((p) => (
          <li
            key={p.id}
            title={p.label}
            aria-label={p.label}
            className={
              p.pct === 100
                ? "w-[1rem] rounded-small bg-background-success-bold"
                : "w-[1rem] rounded-small bg-background-danger-bold"
            }
            style={{ height: `${Math.max(p.pct, 4)}%` }}
          />
        ))}
      </ol>
    </section>
  );
}
