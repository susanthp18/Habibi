import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Lozenge } from "@/components/ui/lozenge";
import {
  useDeploymentExperiments,
  useRollbackExperiment,
  type DeploymentExperiment,
} from "@/api/agent-studio";
import { useRollbackBotDeployment } from "@/api/prompt-studio";

const TRIGGERS = [
  { id: "slo_miss", label: "Voice SLO miss (p95 > 800ms)" },
  { id: "live_qa_burn", label: "Live-QA burn vs previous window" },
  { id: "eval_fail", label: "Red-team fail in sampling" },
] as const;

export type ShipState = {
  trafficPct: number;
  shadow: boolean;
  autoRollback: string[];
};

type Props = {
  botId: string;
  value: ShipState;
  onChange: (next: ShipState) => void;
  activeDeploymentId?: string | null;
};

export function ShipTab({ botId, value, onChange, activeDeploymentId }: Props) {
  const experiments = useDeploymentExperiments(botId);
  const rollbackExp = useRollbackExperiment();
  const rollbackDep = useRollbackBotDeployment();
  const running = (experiments.data ?? []).find((e) => e.status === "running") as DeploymentExperiment | undefined;
  const [busy, setBusy] = useState(false);

  const toggle = (id: string) => {
    const next = value.autoRollback.includes(id)
      ? value.autoRollback.filter((x) => x !== id)
      : [...value.autoRollback, id];
    onChange({ ...value, autoRollback: next });
  };

  return (
    <div className="space-y-200">
      <p className="text-body-small text-text-subtle">
        Canary is a real traffic split. 100% is a full ship. A split without auto-rollback cannot compile.
      </p>
      <label className="block space-y-050">
        <span className="text-body-small font-semibold">Canary traffic {value.trafficPct}%</span>
        <input
          type="range"
          min={0}
          max={100}
          value={value.trafficPct}
          onChange={(e) => onChange({ ...value, trafficPct: Number(e.target.value) })}
          className="w-full"
        />
      </label>
      <label className="flex items-center gap-100 text-body-small">
        <input
          type="checkbox"
          checked={value.shadow}
          onChange={(e) => onChange({ ...value, shadow: e.target.checked })}
        />
        Shadow (log split, do not change customer treatment)
      </label>
      <div>
        <div className="mb-075 text-body-small font-semibold">Auto-rollback</div>
        <div className="space-y-050">
          {TRIGGERS.map((t) => (
            <label key={t.id} className="flex items-center gap-100 text-body-small">
              <input type="checkbox" checked={value.autoRollback.includes(t.id)} onChange={() => toggle(t.id)} />
              {t.label}
            </label>
          ))}
        </div>
        {value.trafficPct > 0 && value.trafficPct < 100 && value.autoRollback.length === 0 ? (
          <p className="mt-075 text-body-small text-text-danger">G12 will fail — pick at least one rollback condition.</p>
        ) : null}
      </div>
      {running ? (
        <div className="rounded-medium border border-border p-150">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-body font-medium">Running experiment</div>
              <div className="text-caption text-text-subtle">
                {running.trafficPct}% canary · rollback on {(running.autoRollback ?? []).join(", ") || "none"}
              </div>
            </div>
            <Lozenge tone="warning">{running.status}</Lozenge>
          </div>
          <Button
            className="mt-100"
            variant="outline"
            disabled={busy}
            onClick={() => {
              setBusy(true);
              void rollbackExp
                .mutateAsync(running.id)
                .then(() => toast.success("Canary rolled back to baseline"))
                .catch((err: Error) => toast.error(err.message))
                .finally(() => setBusy(false));
            }}
          >
            Roll back canary
          </Button>
        </div>
      ) : null}
      {activeDeploymentId ? (
        <Button
          variant="outline"
          disabled={busy}
          onClick={() => {
            setBusy(true);
            void rollbackDep
              .mutateAsync(activeDeploymentId)
              .then(() => toast.success("Active deployment rolled back"))
              .catch((err: Error) => toast.error(err.message))
              .finally(() => setBusy(false));
          }}
        >
          One-click rollback of active deployment
        </Button>
      ) : null}
    </div>
  );
}
