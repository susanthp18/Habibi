/** Strategy: the engine's settings, and changes that take two people to apply. */
import { useMemo, useState } from "react";
import { Bot, Check, SlidersHorizontal, User, X } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Lozenge } from "@/components/ui/lozenge";
import { Textarea } from "@/components/ui/textarea";
import { humanise } from "@/api/treatment";
import {
  useDecideStrategy,
  useProposeStrategy,
  useStrategyProposals,
  useStrategySettings,
  type StrategyProposal,
  type StrategySetting,
} from "@/api/treatment-trace";
import { fmtDateTime } from "@/lib/format";

import { Panel, StateGate } from "./chrome";

const SOURCE_TEXT = { configured: "set here", environment: "server setting", default: "built-in default" } as const;

export function StrategyTab() {
  const settings = useStrategySettings();
  const proposals = useStrategyProposals();
  return (
    <div className="flex flex-col gap-200">
      <StateGate query={proposals} loadingLabel="Loading proposals">
        {(rows) => <Proposals rows={rows} />}
      </StateGate>
      <StateGate query={settings} loadingLabel="Loading settings">
        {(rows) => <SettingsEditor rows={rows} />}
      </StateGate>
    </div>
  );
}

function SettingsEditor({ rows }: { rows: StrategySetting[] }) {
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [reason, setReason] = useState("");
  const propose = useProposeStrategy();
  const groups = useMemo(() => {
    const out = new Map<string, StrategySetting[]>();
    for (const r of rows) out.set(r.group, [...(out.get(r.group) ?? []), r]);
    return [...out.entries()];
  }, [rows]);
  const changed = Object.entries(draft).filter(
    ([k, v]) => v.trim() !== "" && String(rows.find((r) => r.key === k)?.value ?? "") !== v.trim(),
  );

  const submit = () => {
    const changes: Record<string, unknown> = {};
    for (const [k, v] of changed) {
      const spec = rows.find((r) => r.key === k)!;
      changes[k] = spec.type === "float" || spec.type === "int" ? Number(v) : v.trim();
    }
    propose.mutate(
      { changes, reason },
      {
        onSuccess: (p) => {
          toast.success("Change proposed", {
            description: p.impact.estimated
              ? `It would have changed ${p.impact.changed} of ${p.impact.decisions} decisions in the last ${p.impact.days} days. Someone else must approve it.`
              : "Someone else must approve it before it applies.",
          });
          setDraft({});
          setReason("");
        },
        onError: (e) => toast.error(e instanceof Error ? e.message : "Could not propose the change"),
      },
    );
  };

  return (
    <Panel
      title="Settings"
      description="What the engine runs on. Edit any value to propose a change: it applies only after a second person approves it, and every change is kept with its reason."
    >
      <div className="flex flex-col gap-250">
        {groups.map(([group, items]) => (
          <section key={group} className="flex flex-col gap-100">
            <h3 className="text-body-small font-semibold text-text-subtle">{group}</h3>
            <ul className="grid gap-100 md:grid-cols-2">
              {items.map((s) => (
                <li key={s.key} className="flex flex-col gap-050 rounded-medium border border-border p-150">
                  <div className="flex items-center justify-between gap-100">
                    <label htmlFor={`setting-${s.key}`} className="text-body-small font-medium text-text">
                      {s.label}
                    </label>
                    <span className="text-body-tiny text-text-subtlest">{SOURCE_TEXT[s.source]}</span>
                  </div>
                  {s.help ? <p className="text-body-tiny text-text-subtle">{s.help}</p> : null}
                  <Input
                    id={`setting-${s.key}`}
                    className="h-8"
                    placeholder={String(s.value ?? "")}
                    value={draft[s.key] ?? ""}
                    onChange={(e) => setDraft({ ...draft, [s.key]: e.target.value })}
                  />
                  <span className="text-body-tiny text-text-subtlest">
                    Now: {String(s.value ?? "—")}
                    {s.choices ? ` · one of ${s.choices.join(", ")}` : ""}
                    {s.minimum != null || s.maximum != null
                      ? ` · between ${s.minimum ?? "…"} and ${s.maximum ?? "…"}`
                      : ""}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        ))}
        <div className="flex flex-col gap-100 border-t border-border pt-200">
          <label htmlFor="strategy-reason" className="text-body-small font-medium text-text">
            Why change it? {changed.length ? `(${changed.length} setting${changed.length > 1 ? "s" : ""})` : ""}
          </label>
          <Textarea
            id="strategy-reason"
            rows={2}
            value={reason}
            placeholder="e.g. WhatsApp now costs ₹0.60 per message on the new contract."
            onChange={(e) => setReason(e.target.value)}
          />
          <div>
            <Button
              size="sm"
              disabled={!changed.length || !reason.trim() || propose.isPending}
              onClick={submit}
            >
              <SlidersHorizontal className="mr-075 h-3.5 w-3.5" /> Propose change
            </Button>
          </div>
        </div>
      </div>
    </Panel>
  );
}

function Proposals({ rows }: { rows: StrategyProposal[] }) {
  const decide = useDecideStrategy();
  const pending = rows.filter((r) => r.status === "pending");
  const decided = rows.filter((r) => r.status !== "pending").slice(0, 10);
  return (
    <Panel
      title="Proposed changes"
      description="Changes waiting for a second person, including ones the weekly advisor suggests from the results. Approving applies them immediately."
    >
      {pending.length === 0 ? (
        <p className="text-body-small text-text-subtle">Nothing is waiting for approval.</p>
      ) : (
        <ul className="flex flex-col gap-100">
          {pending.map((p) => (
            <li key={p.id} className="flex flex-col gap-075 rounded-medium border border-border p-150">
              <ProposalSummary p={p} />
              <div className="flex gap-100">
                <Button
                  size="sm"
                  disabled={decide.isPending}
                  onClick={() =>
                    decide.mutate(
                      { id: p.id, approve: true },
                      {
                        onSuccess: () => toast.success("Applied"),
                        onError: (e) => toast.error(e instanceof Error ? e.message : "Could not approve"),
                      },
                    )
                  }
                >
                  <Check className="mr-075 h-3.5 w-3.5" /> Approve and apply
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={decide.isPending}
                  onClick={() => decide.mutate({ id: p.id, approve: false })}
                >
                  <X className="mr-075 h-3.5 w-3.5" /> Reject
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
      {decided.length > 0 && (
        <details className="mt-100">
          <summary className="cursor-pointer text-body-small text-text-subtle">Recent decisions</summary>
          <ul className="mt-100 flex flex-col gap-075">
            {decided.map((p) => (
              <li key={p.id} className="rounded-medium border border-border p-150">
                <ProposalSummary p={p} />
                <p className="text-body-tiny text-text-subtle">
                  {humanise(p.status)} by {p.decided_by} {fmtDateTime(p.decided_at)}
                  {p.decision_note ? `: ${p.decision_note}` : ""}
                </p>
              </li>
            ))}
          </ul>
        </details>
      )}
    </Panel>
  );
}

function ProposalSummary({ p }: { p: StrategyProposal }) {
  return (
    <div className="flex flex-col gap-050">
      <div className="flex flex-wrap items-center gap-075 text-body-small">
        {p.proposed_via === "advisor" ? (
          <Lozenge tone="discovery">
            <Bot aria-hidden /> Advisor
          </Lozenge>
        ) : (
          <Lozenge>
            <User aria-hidden /> {p.proposed_by}
          </Lozenge>
        )}
        <span className="text-text-subtle">{fmtDateTime(p.created_at)}</span>
      </div>
      <ul className="text-body-small text-text">
        {Object.entries(p.changes).map(([k, v]) => (
          <li key={k}>
            {humanise(k.replace(/^TREATMENT_/, ""))} → <span className="font-medium">{String(v)}</span>
          </li>
        ))}
      </ul>
      <p className="text-body-small text-text-subtle">{p.reason}</p>
      <p className="text-body-tiny text-text-subtlest">
        {p.impact.estimated
          ? `Would have changed ${p.impact.changed} of ${p.impact.decisions} decisions in the last ${p.impact.days} days${
              p.impact.moves?.length
                ? ` (${p.impact.moves.slice(0, 3).map((m) => `${m.move.replace("→", " to ")} ×${m.count}`).join(", ")})`
                : ""
            }.`
          : (p.impact.note ?? "")}
      </p>
    </div>
  );
}
