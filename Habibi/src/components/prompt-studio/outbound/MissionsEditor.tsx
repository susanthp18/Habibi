import { Plus, ShieldAlert, Trash2 } from "lucide-react";
import type { CardObjective, Objective, VoicemailMode } from "@/api/agent-card";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Lozenge } from "@/components/ui/lozenge";
import { SelectField } from "@/components/ui/select";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useProducts } from "@/api/products";
import {
  CodeGrid,
  NumberField,
  patchOutbound,
  resolvedOutbound,
  toggleIn,
  type OutboundEditorProps,
} from "./shared";

function MissionEditor({
  objective,
  index,
  card,
  onChange,
  vocab,
  graphEntries,
  editable,
}: OutboundEditorProps & { objective: CardObjective; index: number }) {
  const ob = resolvedOutbound(card);
  const productsQuery = useProducts();
  const key = objective.key ?? "";
  const graphNode = graphEntries[key];
  const entry = objective.entry_node ?? "";
  const agrees = Boolean(entry) && graphNode === entry;
  const vm = objective.voicemail ?? {};
  const cadenceNames = ob.cadences.map((c) => c.name ?? "").filter(Boolean);

  const setObjective = (next: Partial<CardObjective>) => {
    const objectives = ob.objectives.map((o, i) => (i === index ? { ...o, ...next } : o));
    patchOutbound(card, onChange, { objectives });
  };
  const remove = () =>
    patchOutbound(card, onChange, { objectives: ob.objectives.filter((_, i) => i !== index) });

  // G-OB4: no product may be mentioned from a 1600-series service pool.
  const offersBlocked = ob.pool_kind === "service_1600";

  return (
    <li className="space-y-150 px-150 py-150">
      <div className="flex flex-wrap items-center gap-100">
        <span className="font-mono text-body-small font-semibold">{key || "unnamed mission"}</span>
        {entry ? (
          agrees ? (
            <Lozenge tone="success">starts at {entry}</Lozenge>
          ) : (
            <Lozenge tone="danger">
              card says {entry} · flow says {graphNode || "nothing"}
            </Lozenge>
          )
        ) : (
          <Lozenge tone="warning">no entry step</Lozenge>
        )}
        <span className="ml-auto">
          <Button size="sm" variant="outline" disabled={!editable} onClick={remove}>
            <Trash2 aria-hidden className="size-100" />
            <span className="sr-only">Remove {key}</span>
          </Button>
        </span>
      </div>

      {vocab.objectiveBriefs[key] ? (
        <p className="max-w-prose text-body-small text-text-subtle">{vocab.objectiveBriefs[key]}</p>
      ) : null}

      <div className="grid gap-100 sm:grid-cols-2 lg:grid-cols-4">
        <div className="space-y-050">
          <Label htmlFor={`m-entry-${index}`}>Entry step</Label>
          {Object.keys(graphEntries).length > 0 ? (
            <SelectField
              id={`m-entry-${index}`}
              size="compact"
              disabled={!editable}
              placeholder="— choose a step —"
              value={entry}
              onChange={(v) => setObjective({ entry_node: v })}
              options={[
                // The graph's own claims first: picking one of these is the only
                // way to satisfy G-OB2 without editing the flow.
                ...Object.entries(graphEntries).map(([obj, node]) => ({
                  value: node,
                  label: `${node} (claims ${obj})`,
                })),
                ...(entry && !Object.values(graphEntries).includes(entry)
                  ? [{ value: entry, label: `${entry} — not in the published flow` }]
                  : []),
              ]}
            />
          ) : (
            <Input
              id={`m-entry-${index}`}
              disabled={!editable}
              defaultValue={entry}
              placeholder="node key in the flow"
              onBlur={(e) => setObjective({ entry_node: e.target.value.trim() })}
            />
          )}
        </div>

        <NumberField
          id={`m-dur-${index}`}
          label="Talk budget"
          value={objective.max_duration_sec ?? 240}
          min={30}
          max={1800}
          suffix="sec"
          disabled={!editable}
          onCommit={(n) => setObjective({ max_duration_sec: n })}
        />

        <div className="space-y-050">
          <Label htmlFor={`m-cadence-${index}`}>Cadence</Label>
          <SelectField
            id={`m-cadence-${index}`}
            size="compact"
            disabled={!editable}
            value={objective.cadence ?? "default"}
            onChange={(v) => setObjective({ cadence: v })}
            options={[
              // Only ladders the card defines. Offering "default" unconditionally
              // swapped the authored ladder for the built-in one with no warning.
              ...cadenceNames.map((n) => ({ value: n, label: n })),
              ...(!cadenceNames.includes(objective.cadence ?? "default")
                ? [
                    {
                      value: objective.cadence ?? "default",
                      label: `${objective.cadence ?? "default"} — not defined, falls back to the built-in ladder`,
                    },
                  ]
                : []),
            ]}
          />
        </div>

        <div className="space-y-050">
          <Label htmlFor={`m-authority-${index}`}>Authority profile</Label>
          <SelectField
            id={`m-authority-${index}`}
            size="compact"
            disabled={!editable}
            value={objective.authority_profile ?? ""}
            onChange={(v) => setObjective({ authority_profile: v || null })}
            options={[
              { value: "", label: "— no extra ceiling —" },
              ...vocab.authorityProfiles.map((p) => ({
                value: p.name,
                label: p.ceilingInr === null ? p.name : `${p.name} (₹${p.ceilingInr})`,
              })),
            ]}
          />
          <p className="text-body-tiny text-text-subtlest">
            A profile can only lower what the matrix already permits.
          </p>
        </div>
      </div>

      <div className="grid gap-150 lg:grid-cols-2">
        <CodeGrid
          legend="Closes the case"
          hint="Outcomes that mean this mission succeeded."
          options={vocab.outcomeCodes}
          selected={objective.success ?? []}
          disabled={!editable}
          onToggle={(c) => setObjective({ success: toggleIn(objective.success ?? [], c) })}
        />
        <CodeGrid
          legend="Partly worked"
          hint="Progress that does not close it — kept apart so a partial is not scored as a win."
          options={vocab.outcomeCodes}
          selected={objective.partial ?? []}
          disabled={!editable}
          onToggle={(c) => setObjective({ partial: toggleIn(objective.partial ?? [], c) })}
        />
      </div>

      <fieldset className="space-y-075">
        <legend className="text-body-small font-medium text-text">
          Offers this mission may make
        </legend>
        <p className="text-body-tiny text-text-subtlest">
          Empty means no product may be mentioned at all. That is the safe default rather than an
          omission: a servicing call is not a sales call and the borrower did not ask to be sold to.
        </p>
        {offersBlocked ? (
          <p className="flex items-start gap-075 text-body-tiny text-text-danger">
            <ShieldAlert aria-hidden className="mt-025 size-100 shrink-0" />
            This card dials from a 1600-series service pool. TRAI permits service and transactional
            calls on that series and not promotional ones, so publish is blocked (G-OB4) while any
            offer is attached.
          </p>
        ) : null}
        <div className="grid gap-050 sm:grid-cols-2 lg:grid-cols-3">
          {(productsQuery.data ?? []).map((p) => (
            <label key={p.id} className="flex items-center gap-075 text-body-small">
              <Checkbox
                checked={(objective.allowed_offers ?? []).includes(p.id)}
                disabled={!editable}
                onCheckedChange={() =>
                  setObjective({ allowed_offers: toggleIn(objective.allowed_offers ?? [], p.id) })
                }
              />
              <span className="truncate" title={p.name}>
                {p.name}
              </span>
            </label>
          ))}
        </div>
        {productsQuery.isError ? (
          <p className="text-body-tiny text-text-danger">
            The product catalog could not be read; offers cannot be chosen until it answers.
          </p>
        ) : (productsQuery.data ?? []).length === 0 ? (
          <p className="text-body-tiny text-text-subtle">No products in the catalog.</p>
        ) : null}
      </fieldset>

      <fieldset className="space-y-075 rounded-medium border border-border bg-surface-sunken/40 p-100">
        <legend className="px-050 text-body-small font-medium text-text">
          When a machine answers
        </legend>
        <div className="grid gap-100 sm:grid-cols-3">
          <div className="space-y-050">
            <Label htmlFor={`m-vm-${index}`}>Leave a message</Label>
            <SelectField
              id={`m-vm-${index}`}
              size="compact"
              disabled={!editable}
              value={vm.leave ?? "first_attempt_only"}
              onChange={(v) => setObjective({ voicemail: { ...vm, leave: v as VoicemailMode } })}
              options={vocab.voicemailModes.map((m) => ({ value: m, label: m }))}
            />
          </div>
          <NumberField
            id={`m-vm-sec-${index}`}
            label="Message length"
            value={vm.max_sec ?? 25}
            min={5}
            max={60}
            suffix="sec"
            disabled={!editable || (vm.leave ?? "first_attempt_only") === "never"}
            onCommit={(n) => setObjective({ voicemail: { ...vm, max_sec: n } })}
          />
          <label className="flex items-start gap-075 pt-250 text-body-small">
            <Checkbox
              checked={vm.include_grievance_contact ?? true}
              disabled={!editable}
              onCheckedChange={(v) =>
                setObjective({ voicemail: { ...vm, include_grievance_contact: v === true } })
              }
            />
            <span>
              Include the grievance officer
              <span className="block text-body-tiny text-text-subtlest">
                Required by RBI para 100AA in every recovery communication — G-OB5.
              </span>
            </span>
          </label>
        </div>
      </fieldset>
    </li>
  );
}

export function MissionsEditor(props: OutboundEditorProps) {
  const { card, onChange, vocab, editable } = props;
  const ob = resolvedOutbound(card);
  const taken = new Set(ob.objectives.map((o) => o.key));
  // `inbound` is a graph entry, not a mission you send an agent on.
  const available = vocab.objectives.filter((o) => o !== "inbound" && !taken.has(o as Objective));

  const add = (key: string) => {
    patchOutbound(card, onChange, {
      objectives: [
        ...ob.objectives,
        {
          key: key as Objective,
          entry_node: props.graphEntries[key] ?? "",
          success: [],
          partial: [],
          max_duration_sec: 240,
          allowed_offers: [],
          authority_profile: null,
          // Written out rather than left to the backend default so the panel
          // shows the same policy the card will carry — an empty object here
          // renders as "never leave a message", which is not what it means.
          voicemail: { leave: "first_attempt_only", max_sec: 25, include_grievance_contact: true },
          cadence: "default",
        },
      ],
    });
  };

  return (
    <div className="space-y-100 rounded-medium border border-border bg-surface">
      <div className="flex flex-wrap items-center gap-100 border-b border-border px-150 py-100">
        <span className="text-body-small font-semibold">Missions</span>
        <span className="text-body-tiny text-text-subtlest">
          why the agent is calling — published with this card
        </span>
        <span className="ml-auto flex items-center gap-075">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-400"
                disabled={!editable || available.length === 0}
              >
                <Plus aria-hidden className="size-100" />
                {available.length ? "Add a mission" : "All missions added"}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {available.map((o) => (
                <DropdownMenuItem key={o} onSelect={() => add(o)}>
                  {o}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        </span>
      </div>
      {ob.objectives.length === 0 ? (
        <p className="max-w-prose px-150 py-150 text-body-small text-text-subtle">
          No missions yet. A mission is why the agent is calling — a bounce cure, a broken-promise
          chase, a pre-due nudge. Each names the step in the flow where that conversation begins, so
          one graph serves every reason without the negotiation and wrap-up being duplicated per
          direction.
        </p>
      ) : (
        <ul className="divide-y divide-border">
          {ob.objectives.map((objective, index) => (
            <MissionEditor
              key={`${objective.key}-${index}`}
              {...props}
              objective={objective}
              index={index}
            />
          ))}
        </ul>
      )}
    </div>
  );
}
