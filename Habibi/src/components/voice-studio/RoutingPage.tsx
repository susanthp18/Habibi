import { AlertTriangle, CircleCheck, CircleX } from "lucide-react";
import { useMemo, useState } from "react";

import { apiErrorMessage } from "@/api/config";
import { can, useMe } from "@/api/me";
import {
  useAssignRouting,
  useCheckRouting,
  useStudioRouting,
  type RoutingChoice,
  type StudioChannel,
} from "@/api/voice-studio";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { QueryState } from "@/components/ui/query-state";
import { SectionMessage } from "@/components/ui/section-message";
import { SelectField } from "@/components/ui/select";

const CHANNELS: { value: StudioChannel; label: string }[] = [
  { value: "inbound", label: "Inbound phone number" },
  { value: "outbound", label: "Outbound objective" },
  { value: "whatsapp", label: "WhatsApp" },
];

/**
 * Which published agent answers each real channel. A selection is validated
 * against the agent's published definition (voice_studio_routing) before it
 * can be activated; activation is audited, and an inbound change rolls back if
 * the telephony provider rejects it.
 */
export default function RoutingPage() {
  const routing = useStudioRouting();
  const me = useMe();
  const check = useCheckRouting();
  const assign = useAssignRouting();
  const [channel, setChannel] = useState<StudioChannel>("inbound");
  const [workflowId, setWorkflowId] = useState(0);
  const [objective, setObjective] = useState("*");
  const [phone, setPhone] = useState("");
  const [checked, setChecked] = useState<{
    key: string;
    result: Awaited<ReturnType<typeof check.mutateAsync>>;
  } | null>(null);
  const numbers = routing.data?.numbers ?? [];
  const agents = routing.data?.agents ?? [];
  const choice = useMemo<RoutingChoice>(() => {
    const [configId, phoneId] = phone.split(":").map(Number);
    return {
      channel,
      workflowId,
      ...(channel === "outbound" ? { objective: objective.trim() } : {}),
      ...(channel === "inbound" && phone ? { configId, phoneId } : {}),
    };
  }, [channel, workflowId, objective, phone]);
  const key = JSON.stringify(choice);
  const isChecked = checked?.key === key && checked.result.ok;
  const mayActivate = can(me.data, "perm-agent-publish") && can(me.data, "perm-voice-operate");
  const ready =
    Boolean(workflowId) &&
    !(channel === "inbound" && !phone) &&
    !(channel === "outbound" && !objective.trim());
  const reset = () => setChecked(null);

  async function validate() {
    reset();
    const result = await check.mutateAsync(choice);
    setChecked({ key, result });
  }

  async function activate() {
    if (!isChecked) return;
    await assign.mutateAsync(choice);
    reset();
  }

  return (
    <div className="mx-auto max-w-[64rem] space-y-300 p-300">
      <header className="space-y-050">
        <h1 className="heading-medium font-semibold">Agent routing</h1>
        <p className="text-body-small text-text-subtle">
          Assign published Voice Studio agents to each real channel. Validate a selection before
          activating it.
        </p>
      </header>
      <QueryState query={routing} label="routing">
        <section className="space-y-100 rounded-medium border border-border p-200">
          <h2 className="text-body font-semibold text-text">Current assignments</h2>
          <ul className="space-y-050 text-body-small">
            {numbers.map((n) => (
              <li key={`${n.configId}:${n.id}`}>
                Inbound {n.addressMasked} ({n.label}):{" "}
                {agents.find((a) => a.id === n.workflowId)?.name ?? "Unassigned"}
              </li>
            ))}
            {(routing.data?.bindings ?? []).map((b) => (
              <li key={b.objective}>
                {b.objective === "whatsapp" ? "WhatsApp" : `Outbound ${b.objective}`}:{" "}
                {agents.find((a) => a.id === b.engine_workflow_id)?.name ??
                  b.label ??
                  "Unknown agent"}
              </li>
            ))}
          </ul>
        </section>
        <section className="space-y-200 rounded-medium border border-border p-200">
          <h2 className="text-body font-semibold text-text">Change an assignment</h2>
          <div className="space-y-100">
            <Label htmlFor="vs-routing-channel">Channel</Label>
            <SelectField
              id="vs-routing-channel"
              value={channel}
              onChange={(v) => {
                setChannel(v as StudioChannel);
                reset();
              }}
              options={CHANNELS}
            />
          </div>
          {channel === "inbound" && (
            <div className="space-y-100">
              <Label htmlFor="vs-routing-phone">Phone number</Label>
              <SelectField
                id="vs-routing-phone"
                value={phone}
                placeholder="Select a number"
                onChange={(v) => {
                  setPhone(v);
                  reset();
                }}
                options={numbers
                  .filter((n) => n.active)
                  .map((n) => ({
                    value: `${n.configId}:${n.id}`,
                    label: `${n.addressMasked} · ${n.label}`,
                  }))}
              />
            </div>
          )}
          {channel === "outbound" && (
            <div className="space-y-100">
              <Label htmlFor="vs-routing-objective">Objective</Label>
              <Input
                id="vs-routing-objective"
                value={objective}
                onChange={(e) => {
                  setObjective(e.target.value);
                  reset();
                }}
              />
              <p className="text-body-small text-text-subtle">
                Use * for the default outbound agent.
              </p>
            </div>
          )}
          <div className="space-y-100">
            <Label htmlFor="vs-routing-agent">Published agent</Label>
            <SelectField
              id="vs-routing-agent"
              value={workflowId ? String(workflowId) : ""}
              placeholder="Select an agent"
              onChange={(v) => {
                setWorkflowId(Number(v));
                reset();
              }}
              options={agents.map((a) => ({ value: String(a.id), label: a.name }))}
            />
          </div>
          <div className="flex gap-100">
            <Button
              variant="subtle"
              disabled={!ready}
              loading={check.isPending}
              onClick={() => void validate()}
            >
              Validate selection
            </Button>
            <Button
              variant="primary"
              disabled={!isChecked || !mayActivate}
              loading={assign.isPending}
              onClick={() => void activate()}
            >
              Activate routing
            </Button>
          </div>
          {checked?.key === key &&
            (checked.result.ok ? (
              <SectionMessage
                variant="success"
                icon={CircleCheck}
                title="Ready to activate"
                role="status"
              >
                {checked.result.name}, published version {checked.result.version} (definition{" "}
                {checked.result.definitionId}).
              </SectionMessage>
            ) : (
              <SectionMessage variant="error" icon={CircleX} title="Not ready" role="status">
                {checked.result.errors.join(" · ")}
              </SectionMessage>
            ))}
          {checked?.key === key && checked.result.warnings?.length ? (
            <SectionMessage variant="warning" icon={AlertTriangle} title="Review before activation">
              {checked.result.warnings.join(" · ")}
            </SectionMessage>
          ) : null}
          {check.isError && (
            <SectionMessage variant="error" icon={CircleX} title="Validation failed" role="alert">
              {apiErrorMessage(check.error)}
            </SectionMessage>
          )}
          {assign.isError && (
            <SectionMessage variant="error" icon={CircleX} title="Routing failed" role="alert">
              {apiErrorMessage(assign.error)}
            </SectionMessage>
          )}
          {assign.isSuccess && (
            <SectionMessage
              variant="success"
              icon={CircleCheck}
              title="Assignment saved and audited"
              role="status"
            />
          )}
          {!mayActivate && (
            <p className="text-body-small text-text-subtle">
              Activation requires agent publishing and voice operation permissions.
            </p>
          )}
        </section>
      </QueryState>
    </div>
  );
}
