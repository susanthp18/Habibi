/**
 * Test call: ring a test handset with a chosen Voice Studio agent, through the
 * same gates as every call. Before the click it says who will speak, what the
 * agent will be told, and anything that would stop the call.
 */
import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, PhoneCall } from "lucide-react";
import { Link } from "@tanstack/react-router";
import { toast } from "sonner";

import {
  friendlyOutboundError,
  usePlaceTestCall,
  useTestCallOptions,
  useTestCallPreview,
} from "@/api/platform";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { LoadingState } from "@/components/ui/loading-state";
import { QueryErrorBanner } from "@/components/ui/query-state";
import { SectionMessage } from "@/components/ui/section-message";
import { SelectField } from "@/components/ui/select";
import { useConfirm } from "@/components/ui/use-confirm";
import { humanise } from "@/api/treatment";

export function TestCallSection() {
  const { confirm, confirmDialog } = useConfirm();
  const options = useTestCallOptions();
  const call = usePlaceTestCall();
  const [objective, setObjective] = useState("dpd_reminder");
  const [agent, setAgent] = useState("");
  const [numberId, setNumberId] = useState("");
  const [result, setResult] = useState<string | null>(null);
  const data = options.data;

  // The agent defaults to whichever one the objective is routed to.
  const bound = useMemo(() => {
    const b =
      data?.bindings.find((x) => x.objective === objective) ??
      data?.bindings.find((x) => x.objective === "*");
    return b ? String(b.engine_workflow_id) : "";
  }, [data, objective]);
  useEffect(() => setAgent(bound), [bound]);
  useEffect(() => {
    if (!numberId && data?.numbers[0]) setNumberId(data.numbers[0].id);
  }, [data, numberId]);

  const chosen = agent && numberId ? { workflowId: Number(agent), numberId, objective } : null;
  const preview = useTestCallPreview(chosen);
  const number = data?.numbers.find((n) => n.id === numberId);
  const agentName = data?.agents.find((a) => String(a.id) === agent)?.name ?? "the agent";

  if (options.isPending) return <LoadingState label="Loading test call" />;
  if (options.isError || !data) return <QueryErrorBanner label="test call" error={options.error} />;

  const blockers = [
    ...(data.outboundEnabled ? [] : ["Outbound calling is off (Automation switches)."]),
    ...data.problems,
    ...(number?.blocked
      ? [`The contact policy refuses this number now: ${humanise(number.blocked)}.`]
      : []),
  ];

  const onCall = async () => {
    if (!chosen) return;
    const ok = await confirm({
      title: `Ring ${number?.e164} now?`,
      description: `${agentName} will call ${number?.customer ? number.customer.name : "this handset"} under ${humanise(objective)}. Every tool it uses is written to the CRM${number?.waived ? `; the ${humanise(number.waived)} rule is waived and recorded` : ""}.`,
      confirmLabel: "Place the call",
      cancelLabel: "Not now",
    });
    if (!ok) return;
    setResult(null);
    try {
      const r = await call.mutateAsync(chosen);
      setResult(r.runId ?? "");
      toast.success("Test call placed");
    } catch (err) {
      toast.error(friendlyOutboundError((err as Error).message));
    }
  };

  return (
    <section>
      <h2 className="text-body font-semibold">Test call</h2>
      <p className="mb-200 mt-025 max-w-3xl text-body-small text-text-subtle">
        Rings a test handset with a Voice Studio agent through every real gate: the switch, the
        contact policy and the dialler. It is the product, not a rehearsal harness.
      </p>
      <div className="grid max-w-3xl gap-150 md:grid-cols-3">
        <div className="space-y-075">
          <Label htmlFor="tc-objective">Why we are calling</Label>
          <SelectField
            id="tc-objective"
            value={objective}
            onChange={setObjective}
            options={data.objectives.map((o) => ({ value: o, label: humanise(o) }))}
          />
        </div>
        <div className="space-y-075">
          <Label htmlFor="tc-agent">Agent</Label>
          <SelectField
            id="tc-agent"
            value={agent}
            placeholder="Choose an agent"
            onChange={setAgent}
            options={data.agents.map((a) => ({
              value: String(a.id),
              label: String(a.id) === bound ? `${a.name} (routed here)` : a.name,
            }))}
          />
        </div>
        <div className="space-y-075">
          <Label htmlFor="tc-number">Test number</Label>
          <SelectField
            id="tc-number"
            value={numberId}
            placeholder="Add a test number first"
            onChange={setNumberId}
            options={data.numbers.map((n) => ({
              value: n.id,
              label: `${n.e164}${n.customer ? ` · ${n.customer.name}` : ""}`,
            }))}
          />
        </div>
      </div>

      {blockers.length ? (
        <SectionMessage
          className="mt-150 max-w-3xl"
          variant="warning"
          icon={AlertTriangle}
          title="The call cannot go yet"
        >
          <ul className="list-disc pl-200 text-body-small">
            {blockers.map((b) => (
              <li key={b}>{b}</li>
            ))}
          </ul>
        </SectionMessage>
      ) : null}

      {chosen ? (
        <div className="mt-150 max-w-3xl rounded-medium border border-border bg-surface-sunken p-150">
          <div className="text-body-small font-semibold text-text">
            What {agentName} will start with
          </div>
          {preview.isPending ? (
            <LoadingState label="Building the context" />
          ) : preview.isError ? (
            <p className="text-body-small text-text-danger">{(preview.error as Error).message}</p>
          ) : (
            <dl className="mt-075 grid grid-cols-[max-content_1fr] gap-x-200 gap-y-025 text-body-small">
              {Object.entries(preview.data.context)
                .filter(([k]) => k !== "mission_brief")
                .map(([k, v]) => (
                  <div key={k} className="contents">
                    <dt className="font-mono text-text-subtlest">{k}</dt>
                    <dd className="text-text">{String(v)}</dd>
                  </div>
                ))}
              {typeof preview.data.context.mission_brief === "string" ? (
                <div className="col-span-2 mt-075 whitespace-pre-wrap text-text-subtle">
                  {preview.data.context.mission_brief}
                </div>
              ) : null}
            </dl>
          )}
        </div>
      ) : null}

      <div className="mt-150 flex items-center gap-150">
        <Button
          variant="primary"
          disabled={!chosen || blockers.length > 0 || call.isPending}
          onClick={() => void onCall()}
        >
          <PhoneCall className="h-3.5 w-3.5" />
          {call.isPending ? "Dialling…" : "Place test call"}
        </Button>
        {result !== null ? (
          <span className="text-body-small text-text-success-bolder">
            Dialling. The call appears in{" "}
            <Link to="/studio/usage" className="text-text-link underline">
              Agent runs
            </Link>
            {result ? ` as run ${result}` : ""} and on the customer's timeline once filed.
          </span>
        ) : null}
      </div>
      {confirmDialog}
    </section>
  );
}
