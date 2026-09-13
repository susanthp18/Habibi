import { Plus, Trash2 } from "lucide-react";
import type { CardCadence } from "@/api/agent-card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Lozenge } from "@/components/ui/lozenge";
import { SelectField } from "@/components/ui/select";
import {
  CodeGrid,
  NumberField,
  patchOutbound,
  resolvedOutbound,
  toggleIn,
  type OutboundEditorProps,
} from "./shared";

function CadenceEditor({
  cadence,
  index,
  card,
  onChange,
  vocab,
  editable,
  handoffTargets,
}: Omit<OutboundEditorProps, "graphEntries"> & {
  cadence: CardCadence;
  index: number;
  handoffTargets: string[];
}) {
  const ob = resolvedOutbound(card);
  const set = (next: Partial<CardCadence>) =>
    patchOutbound(card, onChange, {
      cadences: ob.cadences.map((c, i) => (i === index ? { ...c, ...next } : c)),
    });
  const remove = () =>
    patchOutbound(card, onChange, { cadences: ob.cadences.filter((_, i) => i !== index) });

  const perDay = cadence.per_day ?? 1;
  // G-OB3 fails a cadence that plans more contacts per day than the borrower's
  // cap allows — arithmetically guaranteed to be vetoed, every day, forever.
  const overCap = perDay > vocab.dailyCap;
  const backoff = cadence.backoff_hours ?? [4, 24, 72];
  const usedBy = ob.objectives.filter((o) => (o.cadence ?? "default") === cadence.name);

  return (
    <li className="space-y-150 px-150 py-150">
      <div className="flex flex-wrap items-center gap-100">
        <Input
          aria-label="Cadence name"
          className="w-500"
          disabled={!editable}
          defaultValue={cadence.name ?? "default"}
          key={`cad-name-${index}-${cadence.name}`}
          onBlur={(e) => {
            let name = e.target.value.trim() || "default";
            if (name === cadence.name) return;
            // A duplicate name collapsed two ladders into one silently; the
            // add handler already suffixes, so the rename does the same.
            const used = new Set(ob.cadences.filter((_, i) => i !== index).map((c) => c.name));
            const base = name;
            let n = 2;
            while (used.has(name)) name = `${base}-${n++}`;
            // Rename the references too. G-OB8 fails a mission naming a cadence
            // the card does not define, and a rename that leaves the missions
            // pointing at the old name is exactly that failure.
            patchOutbound(card, onChange, {
              cadences: ob.cadences.map((c, i) => (i === index ? { ...c, name } : c)),
              objectives: ob.objectives.map((o) =>
                (o.cadence ?? "default") === cadence.name ? { ...o, cadence: name } : o,
              ),
            });
          }}
        />
        {usedBy.length > 0 ? (
          <Lozenge tone="information">
            {usedBy.length} mission{usedBy.length === 1 ? "" : "s"}
          </Lozenge>
        ) : (
          <Lozenge tone="neutral">unused</Lozenge>
        )}
        {overCap ? <Lozenge tone="danger">over the borrower cap</Lozenge> : null}
        <span className="ml-auto">
          <Button size="sm" variant="outline" disabled={!editable} onClick={remove}>
            <Trash2 aria-hidden className="size-100" />
            <span className="sr-only">Remove cadence {cadence.name}</span>
          </Button>
        </span>
      </div>

      <div className="grid gap-100 sm:grid-cols-2 lg:grid-cols-4">
        <NumberField
          id={`c-attempts-${index}`}
          label="Attempts"
          value={cadence.max_attempts ?? 3}
          min={1}
          max={10}
          disabled={!editable}
          onCommit={(n) => set({ max_attempts: n })}
        />
        <NumberField
          id={`c-perday-${index}`}
          label="Per borrower per day"
          value={perDay}
          min={1}
          max={5}
          disabled={!editable}
          hint={
            overCap
              ? `contact_policy allows ${vocab.dailyCap}/day — G-OB3 blocks publish`
              : `borrower cap is ${vocab.dailyCap}/day`
          }
          onCommit={(n) => set({ per_day: n })}
        />
        <div className="space-y-050">
          <Label htmlFor={`c-backoff-${index}`}>Backoff (hours)</Label>
          <Input
            id={`c-backoff-${index}`}
            disabled={!editable}
            defaultValue={backoff.join(", ")}
            key={`c-backoff-${index}-${backoff.join(",")}`}
            onBlur={(e) => {
              const parsed = e.target.value
                .split(",")
                .map((part) => Number(part.trim()))
                .filter((n) => Number.isFinite(n) && n > 0)
                .map((n) => Math.round(n));
              set({ backoff_hours: parsed.length ? parsed : backoff });
              e.target.value = (parsed.length ? parsed : backoff).join(", ");
            }}
          />
          <p className="text-body-tiny text-text-subtlest">
            Before attempt 2, 3, … A shorter list repeats its last value.
          </p>
        </div>
      </div>

      <div className="space-y-050">
        <Label htmlFor={`c-escalate-${index}`}>When the attempts run out</Label>
        <SelectField
          id={`c-escalate-${index}`}
          size="compact"
          className="sm:w-1/2"
          disabled={!editable}
          value={cadence.escalate_to ?? ""}
          onChange={(v) => set({ escalate_to: v || null })}
          options={[
            { value: "", label: "— stop, escalate to nobody —" },
            { value: "human", label: "human" },
            ...handoffTargets.map((t) => ({ value: t, label: t })),
          ]}
        />
        <p className="text-body-tiny text-text-subtlest">
          Only this card&apos;s handoff targets are offered. G-OB7 rejects an agent that is not on
          the allowlist — a ladder with a missing top rung.
        </p>
      </div>

      <div className="grid gap-150 lg:grid-cols-2">
        <CodeGrid
          legend="Try again when"
          hint="Matched against the attempt's connection outcome and its state. A refusal is never here: the borrower answered and said no."
          options={vocab.retryStates}
          selected={cadence.retry_on ?? []}
          disabled={!editable}
          onToggle={(c) => set({ retry_on: toggleIn(cadence.retry_on ?? [], c) })}
        />
        <CodeGrid
          legend="Stop the ladder when"
          hint="Terminal for the case whatever the attempt count says."
          options={vocab.outcomeCodes}
          selected={cadence.stop_on ?? []}
          disabled={!editable}
          onToggle={(c) => set({ stop_on: toggleIn(cadence.stop_on ?? [], c) })}
        />
      </div>
    </li>
  );
}

export function CadencesEditor({
  handoffTargets,
  ...props
}: Omit<OutboundEditorProps, "graphEntries"> & { handoffTargets: string[] }) {
  const { card, onChange, editable } = props;
  const ob = resolvedOutbound(card);

  const add = () => {
    const base = "ladder";
    let name = ob.cadences.length === 0 ? "default" : base;
    let n = 2;
    const used = new Set(ob.cadences.map((c) => c.name));
    while (used.has(name)) name = `${base}-${n++}`;
    patchOutbound(card, onChange, {
      cadences: [
        ...ob.cadences,
        {
          name,
          max_attempts: 3,
          per_day: 1,
          backoff_hours: [4, 24, 72],
          retry_on: ["no_answer", "busy", "voicemail_left", "voicemail_skipped"],
          stop_on: [
            "ptp_captured",
            "ptp_recommitted",
            "paid_in_call",
            "dispute_raised",
            "opt_out_requested",
            "wrong_number",
            "deceased",
          ],
          escalate_to: null,
        },
      ],
    });
  };

  return (
    <div className="rounded-medium border border-border bg-surface">
      <div className="flex flex-wrap items-center gap-100 border-b border-border px-150 py-100">
        <span className="text-body-small font-semibold">Retry ladders on this card</span>
        <span className="text-body-tiny text-text-subtlest">
          cadence retries the same mission — only the treatment engine may change the action
        </span>
        <span className="ml-auto">
          <Button size="sm" variant="secondary" disabled={!editable} onClick={add}>
            <Plus aria-hidden className="size-100" /> Add ladder
          </Button>
        </span>
      </div>
      {ob.cadences.length === 0 ? (
        <p className="max-w-prose px-150 py-150 text-body-small text-text-subtle">
          No ladder defined. Missions fall back to a conservative built-in — three attempts, one a
          day, 4/24/72 hours apart — which is deliberately never &ldquo;retry forever&rdquo;, but it
          is also not something anyone chose.
        </p>
      ) : (
        <ul className="divide-y divide-border">
          {ob.cadences.map((cadence, index) => (
            <CadenceEditor
              key={`${cadence.name}-${index}`}
              {...props}
              handoffTargets={handoffTargets}
              cadence={cadence}
              index={index}
            />
          ))}
        </ul>
      )}
    </div>
  );
}
