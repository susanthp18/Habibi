/**
 * Host slot "@/host/AiSimulator": the agent editor's "AI customer" tab.
 *
 * Describe a customer in plain words; an LLM plays them against the agent's
 * draft through an isolated rehearsal (tools answer from a test persona and
 * write nothing), and every agent turn is graded against the agent's
 * guardrails. The run is saved with the agent's Checks, so it also counts in
 * the pass-rate trend.
 */
import { useState } from "react";
import { toast } from "sonner";

import { apiErrorMessage } from "@/api/config";
import { can, useMe } from "@/api/me";
import { useCheckRuns, useSimulateCustomer } from "@/api/voice-studio";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { CheckRunCard } from "@/components/voice-studio/CheckRunCard";

const SIMULATION_ID = "ai-customer";
const DEFAULT_PERSONA =
  "Lost their job last month and is anxious about the overdue EMI. Wants to pay in two parts, " +
  "gets irritated if asked the same thing twice, and asks what happens to their credit score.";

export default function AiSimulator({
  workflowId,
  disabledReason,
}: {
  workflowId: number;
  disabledReason: string | null;
}) {
  const [persona, setPersona] = useState(DEFAULT_PERSONA);
  const [startedId, setStartedId] = useState<string | null>(null);
  const simulate = useSimulateCustomer(workflowId);
  const runs = useCheckRuns(workflowId);
  const { data: me } = useMe();
  // The run this panel started, else the agent's most recent AI-customer run.
  const latest =
    (runs.data ?? []).find((r) => r.id === startedId) ??
    (runs.data ?? []).find(
      (r) => r.results.length > 0 && r.results.every((res) => res.scenarioId === SIMULATION_ID),
    );
  const running = latest?.status === "running";
  const allowed = can(me, "perm-eval-run");

  const start = () =>
    simulate.mutate(persona.trim(), {
      onSuccess: (started) => {
        setStartedId(started.id);
        toast.success("AI customer started. The conversation appears here in a minute.");
      },
      onError: (e) => toast.error(`Could not start: ${apiErrorMessage(e)}`),
    });

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-150 overflow-y-auto">
      {disabledReason && <p className="text-body-small text-text-warning">{disabledReason}</p>}
      <div className="space-y-100">
        <Label htmlFor="vs-ai-customer">Who is the customer?</Label>
        <Textarea
          id="vs-ai-customer"
          rows={5}
          maxLength={2000}
          value={persona}
          onChange={(e) => setPersona(e.target.value)}
        />
        <p className="text-body-small text-text-subtle">
          Plays against the latest saved version (the draft, if there is one). Tools answer from a
          test account; nothing is recorded.
        </p>
      </div>
      <Button
        variant="primary"
        className="self-start"
        disabled={Boolean(disabledReason) || !allowed || running || persona.trim().length < 10}
        loading={simulate.isPending}
        onClick={start}
      >
        {running ? "Talking…" : "Run AI customer"}
      </Button>
      {!allowed && (
        <p className="text-body-small text-text-subtle">
          Running rehearsals needs the eval permission.
        </p>
      )}
      {latest && latest.status === "done" && (
        <ul>
          <CheckRunCard run={latest} open />
        </ul>
      )}
    </div>
  );
}
