/** The LLM gateway: its status, the canary and its promotion. */
import { useState } from "react";
import {
  useGatewayStatus,
  useGatewayCanary,
  useProposeGatewayCanary,
  usePromoteGatewayCanary,
} from "@/api/integrations";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Lozenge } from "@/components/ui/lozenge";

export function GatewayPanel() {
  const { data } = useGatewayStatus();
  const canaryQuery = useGatewayCanary();
  const propose = useProposeGatewayCanary();
  const promote = usePromoteGatewayCanary();
  const [candidate, setCandidate] = useState("");
  const profiles = data?.profiles ?? {};
  const canary = canaryQuery.data?.current ?? data?.canary ?? null;
  const copy = canary?.copyToEnv ?? [];
  return (
    <div className="space-y-150">
      <p className="text-body-small text-text-subtle">
        All four profiles go through the gateway client when the flag is on.{" "}
        <span className="font-mono">azure_openai</span> is the kill-switch. Canary a new Azure
        deployment to <span className="font-mono">analysis</span> first, then text, then voice.
        Red-team is never skipped. Copy-to-env is a human step.
      </p>
      <div className="rounded-medium border border-border p-150 text-body-small">
        <div>Enabled: {data?.enabled ? "yes" : "no"}</div>
        <div>Base URL: {data?.baseUrl || "unset"}</div>
        <div>Kill-switch: {data?.killSwitch || "gateway"}</div>
        <div>Voice SLO: {data?.voiceSloMs ?? 800} ms</div>
      </div>
      <ul className="divide-y divide-border rounded-medium border border-border">
        {Object.entries(profiles).map(([name, row]) => (
          <li key={name} className="flex items-center justify-between px-150 py-100">
            <div>
              <div className="font-medium">{name}</div>
              <div className="font-mono text-body-tiny text-text-subtle">
                {row.model || "default model"}
              </div>
              {row.canaryModel ? (
                <div className="text-body-tiny text-text-subtle">canary {row.canaryModel}</div>
              ) : null}
            </div>
            <div className="text-body-tiny text-text-subtle">cap ₹{row.capInr || 0}</div>
          </li>
        ))}
      </ul>
      <div className="rounded-medium border border-border p-150">
        <div className="mb-100 text-body-small font-semibold text-text">Model canary</div>
        {canary ? (
          <div className="mb-100 space-y-050 text-body-small">
            <div className="flex flex-wrap items-center gap-075">
              <span className="font-mono">{canary.candidateModel}</span>
              <Lozenge
                tone={
                  canary.status === "promoted"
                    ? "success"
                    : canary.status === "fail"
                      ? "danger"
                      : "neutral"
                }
              >
                {canary.stage} · {canary.status}
              </Lozenge>
              {canary.injectionClosed ? <Lozenge tone="success">injection closed</Lozenge> : null}
            </div>
            {canary.status === "pass" && canary.stage !== "voice" ? (
              <Button
                size="sm"
                disabled={promote.isPending}
                onClick={() => void promote.mutateAsync(canary.id)}
              >
                {promote.isPending
                  ? "Promoting…"
                  : `Promote to ${canary.stage === "analysis" ? "text" : "voice"}`}
              </Button>
            ) : null}
            {copy.length > 0 ? (
              <ul className="font-mono text-body-tiny text-text-subtle">
                {copy.map((c) => (
                  <li key={c.name}>
                    {c.name}={c.value}
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : (
          <p className="mb-100 text-body-tiny text-text-subtlest">No open canary.</p>
        )}
        <div className="flex flex-wrap items-end gap-100">
          <Input
            value={candidate}
            onChange={(e) => setCandidate(e.target.value)}
            placeholder="azure/gpt-deployment"
          />
          <Button
            size="sm"
            disabled={!candidate || propose.isPending}
            onClick={() => void propose.mutateAsync(candidate)}
          >
            {propose.isPending ? "Starting…" : "Start at analysis"}
          </Button>
        </div>
      </div>
    </div>
  );
}
