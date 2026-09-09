import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Lozenge } from "@/components/ui/lozenge";
import {
  useDeploymentExperiments,
  useEffectiveContract,
  useRollbackExperiment,
  type CompileReport,
  type DeploymentExperiment,
} from "@/api/agent-studio";
import { useRollbackBotDeployment } from "@/api/prompt-studio";
import { shipRollbackTarget } from "@/lib/studio-trust";
import { controlKindLabel, parseEffectiveContract } from "@/lib/studio-contract";
import type { RollbackTrigger } from "@/api/agent-card";

const TRIGGERS: { id: RollbackTrigger; label: string; hint?: string }[] = [
  { id: "slo_miss", label: "Voice SLO miss (p95 > 800ms)" },
  { id: "live_qa_burn", label: "Live-QA burn vs previous window" },
  { id: "eval_fail", label: "Red-team fail in sampling" },
  // The outbound three. None is a ratio against a baseline: an abandoned call
  // is structurally impossible by design, so one means something broke, and
  // there is no acceptable rate of telling a stranger about somebody's debt.
  { id: "abandon_rate", label: "Any abandoned call", hint: "target is zero, not low" },
  { id: "third_party_leak", label: "Debt disclosed to a third party" },
  {
    id: "optout_spike",
    label: "Opt-out spike",
    hint: "three in fifteen minutes - one is a legitimate outcome",
  },
];

export type ShipState = {
  trafficPct: number;
  /**
   * Was `string[]`, which is wider than the card can hold: these land on
   * `card.experiment.auto_rollback`, a Literal on a model with
   * `extra="forbid"`. A value outside the vocabulary does not degrade — it
   * makes the card fail validation, so the first symptom would be a publish
   * rejecting a card this editor was happy to build.
   */
  autoRollback: RollbackTrigger[];
};

type Props = {
  botId: string;
  value: ShipState;
  onChange: (next: ShipState) => void;
  activeDeploymentId?: string | null;
  priorDeploymentId?: string | null;
  rollbackDeploymentId?: string | null;
  /**
   * The latest compile report, from the same state the card tabs already read
   * (prompt-studio.lazy.tsx). Publish readiness was scattered across the Prompt
   * tab's lint findings, the Flow tab's errors and the gate list on the card
   * tabs, so the one screen named "Ship" was the only one that could not tell
   * you whether the card would ship. Passed in rather than re-fetched — this is
   * a summary of a report already on screen, not a second opinion.
   */
  compileReport?: CompileReport | null;
  /**
   * The same compile the Publish button runs, with the same payload. The
   * section told the reader to "run Compile" and offered no control to run it,
   * so the only way to see the gates was to open the publish dialog — which is
   * the last place a reader wants to discover a blocking gate.
   */
  onCompile?: () => void;
  compileBusy?: boolean;
};

export function ShipTab({
  botId,
  value,
  onChange,
  activeDeploymentId,
  priorDeploymentId,
  rollbackDeploymentId,
  compileReport = null,
  onCompile,
  compileBusy = false,
}: Props) {
  const experiments = useDeploymentExperiments(botId);
  const contractQuery = useEffectiveContract(botId);
  const rollbackExp = useRollbackExperiment();
  const rollbackDep = useRollbackBotDeployment();
  const running = (experiments.data ?? []).find((e) => e.status === "running") as
    DeploymentExperiment | undefined;
  const rollbackTarget = shipRollbackTarget({
    rollbackDeploymentId,
    priorDeploymentId,
  });
  const [busy, setBusy] = useState(false);

  const toggle = (id: RollbackTrigger) => {
    const next = value.autoRollback.includes(id)
      ? value.autoRollback.filter((x) => x !== id)
      : [...value.autoRollback, id];
    onChange({ ...value, autoRollback: next });
  };

  const gates = compileReport?.gates ?? [];
  const failing = gates.filter((g) => g.status === "fail");
  const warning = gates.filter((g) => g.status === "warn");

  return (
    <div className="space-y-200">
      <p className="text-body-small text-text-subtle">
        Canary is a real traffic split. 100% is a full ship. A split without auto-rollback cannot
        compile.
      </p>

      <section className="rounded-medium border border-border p-150">
        <div className="mb-100 flex flex-wrap items-center gap-100">
          <h3 className="text-body-small font-semibold">Ship readiness</h3>
          {gates.length === 0 ? null : failing.length ? (
            <Lozenge tone="danger">
              {failing.length} blocking {failing.length === 1 ? "gate" : "gates"}
            </Lozenge>
          ) : warning.length ? (
            <Lozenge tone="warning">
              {warning.length} warning{warning.length === 1 ? "" : "s"}
            </Lozenge>
          ) : (
            <Lozenge tone="success">all gates pass</Lozenge>
          )}
          {onCompile ? (
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="ml-auto"
              disabled={compileBusy}
              onClick={onCompile}
            >
              {compileBusy ? "Compiling…" : gates.length ? "Recompile" : "Compile"}
            </Button>
          ) : null}
        </div>
        {gates.length === 0 ? (
          <p className="text-body-small text-text-subtle">
            No compile report yet — run Compile to see which gates a publish would clear.
          </p>
        ) : (
          <ul className="space-y-050 text-body-small">
            {gates.map((g) => (
              <li key={g.gate} className="flex items-start justify-between gap-100">
                <span>
                  <span className="font-mono">{g.gate}</span> {g.name}
                  {g.detail ? <span className="ml-075 text-text-subtle">{g.detail}</span> : null}
                </span>
                <Lozenge
                  tone={
                    g.status === "pass"
                      ? "success"
                      : g.status === "fail"
                        ? "danger"
                        : g.status === "warn"
                          ? "warning"
                          : "neutral"
                  }
                >
                  {g.status}
                </Lozenge>
              </li>
            ))}
          </ul>
        )}
      </section>
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
      <div>
        <div className="mb-075 text-body-small font-semibold">Auto-rollback</div>
        <div className="space-y-050">
          {TRIGGERS.map((t) => (
            <label key={t.id} className="flex items-center gap-100 text-body-small">
              <input
                type="checkbox"
                checked={value.autoRollback.includes(t.id)}
                onChange={() => toggle(t.id)}
              />
              {t.label}
            </label>
          ))}
        </div>
        {/* The slider's own minimum is 0, and 0 is not "no canary" to the
            backend — it is `canary_zero`, a G12 failure. The warning only fired
            for `>0 && <100`, so the one value the control actively invites you
            to pick was the one value it stayed silent about. */}
        {value.trafficPct === 0 ? (
          <p className="mt-075 text-body-small text-text-danger">
            G12 will fail — a 0% canary routes no traffic anywhere. Use 100% for a full ship.
          </p>
        ) : value.trafficPct < 100 && value.autoRollback.length === 0 ? (
          <p className="mt-075 text-body-small text-text-danger">
            G12 will fail — pick at least one rollback condition.
          </p>
        ) : null}
      </div>
      {experiments.isError ? (
        <p className="text-body-small text-text-danger">
          Could not load experiments — this is not a statement that none are running.
        </p>
      ) : null}
      {running ? (
        <div className="rounded-medium border border-border p-150">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-body font-medium">Running experiment</div>
              <div className="text-body-tiny text-text-subtle">
                {running.trafficPct}% canary · rollback on{" "}
                {(running.autoRollback ?? []).join(", ") || "none"}
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
                .then((result) => {
                  // The server says which of the two things it did. A rollback
                  // with no baseline deployment to return to does not move
                  // traffic anywhere — it only closes the experiment, and the
                  // canary keeps serving. Reporting that as "rolled back to
                  // baseline" told an operator watching a bad canary that the
                  // traffic was off it when it was not.
                  if (result?.baselineRestored) {
                    toast.success("Canary rolled back — the previous deployment is active again.");
                  } else {
                    toast.warning(
                      "Experiment closed, but there was no baseline deployment to restore — the canary is still serving. Publish or roll back a deployment to replace it.",
                    );
                  }
                })
                .catch((err: Error) => toast.error(err.message))
                .finally(() => setBusy(false));
            }}
          >
            Roll back canary
          </Button>
        </div>
      ) : null}
      {rollbackTarget ? (
        <Button
          variant="outline"
          disabled={busy}
          onClick={() => {
            setBusy(true);
            void rollbackDep
              .mutateAsync(rollbackTarget)
              .then(() => toast.success("Rolled back to the previous deployment"))
              .catch((err: Error) => toast.error(err.message))
              .finally(() => setBusy(false));
          }}
        >
          One-click rollback to previous deployment
        </Button>
      ) : null}

      <EffectiveContractPanel compileReport={compileReport} query={contractQuery} />
    </div>
  );
}

function EffectiveContractPanel({
  compileReport,
  query,
}: {
  compileReport?: CompileReport | null;
  query: ReturnType<typeof useEffectiveContract>;
}) {
  const fromCompile = compileReport?.bundle;
  const parsedCompile = fromCompile
    ? parseEffectiveContract({
        source: "preview",
        botId: compileReport?.bot_id || "",
        compiled: fromCompile,
      })
    : null;
  const compiled =
    (parsedCompile?.success ? parsedCompile.data.compiled : null) ||
    (query.data?.compiled as Record<string, unknown> | undefined);
  const source = query.data?.source || (fromCompile ? "preview" : null);
  const hash =
    compiled && typeof compiled === "object" && "bundle_hash" in compiled
      ? String((compiled as { bundle_hash?: string }).bundle_hash || "")
      : "";
  const grants = Array.isArray((compiled as { grants?: unknown })?.grants)
    ? (compiled as { grants: Array<{ channel: string; allowed: string[]; offered: string[] }> })
        .grants
    : [];
  const skills = Array.isArray((compiled as { skills?: unknown })?.skills)
    ? (compiled as { skills: Array<{ skill_id: string; version: string }> }).skills
    : [];
  const gates = Array.isArray((compiled as { human_gates?: unknown })?.human_gates)
    ? (compiled as { human_gates: Array<{ tool_name?: string; require?: string }> }).human_gates
    : [];

  return (
    <section className="rounded-medium border border-border p-150">
      <div className="mb-100 flex flex-wrap items-center gap-100">
        <h3 className="text-body-small font-semibold">Effective contract</h3>
        {query.isError ? (
          <Lozenge tone="danger">could not load</Lozenge>
        ) : query.isPending && !compiled ? (
          <Lozenge tone="neutral">loading…</Lozenge>
        ) : source ? (
          <Lozenge tone="neutral">{source}</Lozenge>
        ) : (
          <Lozenge tone="neutral">compile to inspect</Lozenge>
        )}
      </div>
      <p className="mb-100 text-body-small text-text-subtle">
        What production and rehearsal will actually run. Every control is labelled runtime,
        simulated, compile-only, or unsupported.
      </p>
      {query.isError ? (
        <p className="text-body-small text-text-danger">
          {query.error instanceof Error
            ? query.error.message
            : "Effective contract could not be read."}{" "}
          Retry from Compile.
        </p>
      ) : !compiled ? (
        <p className="text-body-small text-text-subtle">
          No compiled artefact yet — run Compile, or publish to persist one.
        </p>
      ) : (
        <div className="space-y-100 text-body-small">
          <div>
            Hash <span className="font-mono">{hash || "—"}</span>
          </div>
          {grants.map((g) => (
            <div key={g.channel}>
              <span className="font-medium">{g.channel}</span>{" "}
              <Lozenge tone="neutral">{controlKindLabel("runtime")}</Lozenge>
              <div className="mt-025 font-mono text-body-tiny text-text-subtle">
                {(g.offered.length ? g.offered : g.allowed).join(", ") || "none"}
              </div>
            </div>
          ))}
          {skills.length ? (
            <div>
              Skills <Lozenge tone="neutral">{controlKindLabel("compile-only")}</Lozenge>
              <div className="mt-025 font-mono text-body-tiny text-text-subtle">
                {skills.map((s) => `${s.skill_id}@${s.version}`).join(", ")}
              </div>
            </div>
          ) : null}
          {gates.length ? (
            <div>
              Human gates <Lozenge tone="neutral">{controlKindLabel("runtime")}</Lozenge>
              <div className="mt-025 font-mono text-body-tiny text-text-subtle">
                {gates.map((g) => `${g.tool_name}:${g.require}`).join(", ")}
              </div>
            </div>
          ) : null}
          <p className="text-body-tiny text-text-subtlest">
            Text sandbox is simulated, not live. Flow is validated here; WhatsApp does not walk the
            graph in rehearsal.
          </p>
        </div>
      )}
    </section>
  );
}
