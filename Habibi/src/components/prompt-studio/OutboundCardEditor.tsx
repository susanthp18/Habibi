// Authoring `card.outbound` — the block that decides whether this agent dials,
// why, how often, from which number, and what happens after it hangs up.
//
// Until this file existed the block had no editor anywhere. `CardOutbound` has
// been in `agent_core/cards/schema.py` with nine members and three nested
// models, `campaigns.py` reads its number pool, `cadence.py` reads its retry
// ladder, `mission.py` reads its objectives, and eight compile gates check it —
// and the only way to put a value in it was to write JSON into the database by
// hand. The Outbound tab showed the result read-only and said "No missions on
// this card", which was true and unactionable.
//
// Two rules shape everything below.
//
// **Every vocabulary comes from the backend.** Objectives, outcome codes,
// post-call verbs, retryable states, authority profiles, pool kinds — all of it
// arrives from `/outbound/card-vocabulary`, derived there from the definitions
// the compiler and the runtime actually use. Restating any of them here would
// build cards that fail validation at publish, holding a value picked from a
// dropdown this file drew.
//
// **The gates are shown while you type, not at the publish button.** G-OB1..8
// are cheap to evaluate and the compile preview already accepts an unsaved
// card, so a cadence over the borrower's daily cap or a mission whose entry
// node the graph does not claim is visible in the panel that caused it.

import { useMemo } from "react";
import { Plus, ShieldAlert, Trash2 } from "lucide-react";

import type {
  AgentCard,
  CardCadence,
  CardObjective,
  CardOutbound,
  CardPostCall,
  Direction,
  Objective,
  PoolKind,
  PostCallQa,
  PostCallRule,
  TimeOfDay,
  VoicemailMode,
} from "@/api/agent-card";
import type { OutboundVocabulary } from "@/api/outbound";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Lozenge } from "@/components/ui/lozenge";
import { Switch } from "@/components/ui/switch";
import { useProducts } from "@/api/products";
import { cn } from "@/lib/utils";

/** Matches the raw `<select>` already used elsewhere on this tab. */
const SELECT_CLASS =
  "h-200 w-full rounded-small border border-border bg-surface px-100 text-body-small";

export type OutboundEditorProps = {
  card: AgentCard;
  onChange: (next: AgentCard) => void;
  vocab: OutboundVocabulary;
  /** Objective → node key, as the *published* flow graph claims it. G-OB2 fails
   *  when the card and the graph disagree, so both halves are shown. */
  graphEntries: Record<string, string>;
  /** False on an un-authored card: there is nothing to attach an outbound
   *  block to until the card names a bot. */
  editable: boolean;
};

/** The outbound block with its schema defaults applied.
 *
 *  Reading `card.outbound?.direction ?? "inbound"` at every use site is how the
 *  frontend and the Pydantic model drift: the default lives in exactly one
 *  place there, and this is the matching one place here.
 */
export function resolvedOutbound(
  card: AgentCard,
): Required<
  Pick<
    CardOutbound,
    | "direction"
    | "objectives"
    | "cadences"
    | "number_pool"
    | "pool_kind"
    | "concurrency_share"
    | "carrier_amd"
    | "ivr_traversal"
    | "ivr_max_sec"
  >
> & { post_call: Required<CardPostCall> } {
  const ob = card.outbound ?? {};
  const pc = ob.post_call ?? {};
  return {
    direction: ob.direction ?? "inbound",
    objectives: ob.objectives ?? [],
    cadences: ob.cadences ?? [],
    number_pool: ob.number_pool ?? null,
    pool_kind: ob.pool_kind ?? "general",
    concurrency_share: ob.concurrency_share ?? 0,
    carrier_amd: ob.carrier_amd ?? false,
    ivr_traversal: ob.ivr_traversal ?? false,
    ivr_max_sec: ob.ivr_max_sec ?? 90,
    post_call: {
      on_outcome: pc.on_outcome ?? [],
      written_followup: pc.written_followup ?? true,
      obligations: pc.obligations ?? true,
      qa: pc.qa ?? "always",
    },
  };
}

function patchOutbound(
  card: AgentCard,
  onChange: (next: AgentCard) => void,
  next: Partial<CardOutbound>,
) {
  onChange({ ...card, outbound: { ...(card.outbound ?? {}), ...next } });
}

/** A bounded integer input that keeps the field usable while it is empty.
 *
 *  Coercing every keystroke through `Number()` and clamping makes a field you
 *  cannot clear to retype: deleting "90" yields NaN, the clamp turns it into
 *  the minimum, and the caret lands after a value you did not ask for. The
 *  clamp belongs on blur, which is also where the schema would reject it.
 */
function NumberField({
  id,
  label,
  value,
  min,
  max,
  suffix,
  hint,
  disabled,
  onCommit,
}: {
  id: string;
  label: string;
  value: number;
  min: number;
  max: number;
  suffix?: string;
  hint?: string;
  disabled?: boolean;
  onCommit: (next: number) => void;
}) {
  return (
    <div className="space-y-050">
      <Label htmlFor={id}>{label}</Label>
      <div className="flex items-center gap-075">
        <Input
          id={id}
          inputMode="numeric"
          defaultValue={String(value)}
          key={`${id}:${value}`}
          disabled={disabled}
          onBlur={(e) => {
            const parsed = Number(e.target.value);
            const next = Number.isFinite(parsed)
              ? Math.max(min, Math.min(max, Math.round(parsed)))
              : value;
            if (next !== value) onCommit(next);
            e.target.value = String(next);
          }}
        />
        {suffix ? (
          <span className="shrink-0 text-body-small text-text-subtlest">{suffix}</span>
        ) : null}
      </div>
      {hint ? <p className="text-body-tiny text-text-subtlest">{hint}</p> : null}
    </div>
  );
}

/** A checkbox grid over a closed vocabulary. Used for every list-of-codes field
 *  on the card, because free text there is exactly what G-OB6 rejects. */
function CodeGrid({
  legend,
  options,
  selected,
  disabled,
  onToggle,
  hint,
}: {
  legend: string;
  options: string[];
  selected: string[];
  disabled?: boolean;
  onToggle: (code: string) => void;
  hint?: string;
}) {
  const on = new Set(selected);
  return (
    <fieldset className="space-y-075">
      <legend className="text-body-small font-medium text-text">{legend}</legend>
      {hint ? <p className="text-body-tiny text-text-subtlest">{hint}</p> : null}
      {options.length === 0 ? (
        <p className="text-body-tiny text-text-subtle">
          Vocabulary unavailable — check the API. Nothing is offered rather than guessed.
        </p>
      ) : (
        <div className="grid gap-050 sm:grid-cols-2 lg:grid-cols-3">
          {options.map((code) => (
            <label key={code} className="flex items-center gap-075 text-body-small">
              <Checkbox
                checked={on.has(code)}
                disabled={disabled}
                onCheckedChange={() => onToggle(code)}
              />
              <span className="font-mono text-body-tiny">{code}</span>
            </label>
          ))}
        </div>
      )}
    </fieldset>
  );
}

function toggleIn(list: string[], code: string): string[] {
  return list.includes(code) ? list.filter((c) => c !== code) : [...list, code];
}

// ---------------------------------------------------------------------------
// Direction, reach and the number we dial from
// ---------------------------------------------------------------------------

export function DirectionPanel({
  card,
  onChange,
  vocab,
  editable,
}: Omit<OutboundEditorProps, "graphEntries">) {
  const ob = resolvedOutbound(card);
  const set = (next: Partial<CardOutbound>) => patchOutbound(card, onChange, next);
  const dials = ob.direction !== "inbound";
  const poolNames = vocab.numberPools.map((p) => p.name);
  const knownPool = vocab.numberPools.find((p) => p.name === ob.number_pool);
  // The pool row carries its own kind. A card claiming a different one is not a
  // typo to correct silently — G-OB4 keys off the card's value, so a pool the
  // operator believes is service-only would permit offers.
  const kindDisagrees = Boolean(knownPool && knownPool.kind !== ob.pool_kind);

  return (
    <div className="space-y-150 rounded-medium border border-border bg-surface p-150">
      <div className="flex flex-wrap items-center justify-between gap-100">
        <div>
          <h3 className="text-body font-semibold">Direction and reach</h3>
          <p className="mt-025 max-w-prose text-body-small text-text-subtle">
            An inbound-only card skips G-OB1..8 entirely — declaring a direction is what turns the
            outbound gates on.
          </p>
        </div>
        <Lozenge tone={dials ? "success" : "neutral"}>
          {dials ? `dials · ${ob.direction}` : "never dials"}
        </Lozenge>
      </div>

      <div className="grid gap-100 sm:grid-cols-2 lg:grid-cols-3">
        <div className="space-y-050">
          <Label htmlFor="ob-direction">Direction</Label>
          <select
            id="ob-direction"
            className={SELECT_CLASS}
            disabled={!editable}
            value={ob.direction}
            onChange={(e) => set({ direction: e.target.value as Direction })}
          >
            {vocab.directions.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </div>

        <div className="space-y-050">
          <Label htmlFor="ob-pool">Caller-ID pool</Label>
          {poolNames.length > 0 ? (
            <select
              id="ob-pool"
              className={SELECT_CLASS}
              disabled={!editable}
              value={ob.number_pool ?? ""}
              onChange={(e) => {
                const name = e.target.value || null;
                const match = vocab.numberPools.find((p) => p.name === name);
                // Adopt the pool's own kind on selection. Choosing a 1600-series
                // pool and leaving pool_kind on "general" is the combination
                // G-OB4 cannot catch — the gate trusts the card.
                set({
                  number_pool: name,
                  ...(match ? { pool_kind: match.kind as PoolKind } : {}),
                });
              }}
            >
              <option value="">— share the general pool —</option>
              {vocab.numberPools.map((p) => (
                <option key={p.name} value={p.name}>
                  {p.name} ({p.kind})
                </option>
              ))}
            </select>
          ) : (
            <Input
              id="ob-pool"
              disabled={!editable}
              defaultValue={ob.number_pool ?? ""}
              placeholder="no pools configured — name one"
              onBlur={(e) => set({ number_pool: e.target.value.trim() || null })}
            />
          )}
        </div>

        <div className="space-y-050">
          <Label htmlFor="ob-pool-kind">Pool kind</Label>
          <select
            id="ob-pool-kind"
            className={SELECT_CLASS}
            disabled={!editable}
            value={ob.pool_kind}
            onChange={(e) => set({ pool_kind: e.target.value as PoolKind })}
          >
            {vocab.poolKinds.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
          {kindDisagrees ? (
            <p className="text-body-tiny text-text-danger">
              Pool {knownPool?.name} is registered as {knownPool?.kind}. G-OB4 reads the card, so
              this mismatch decides whether offers are permitted.
            </p>
          ) : null}
        </div>

        {/* `concurrency_share` deliberately has no control here.
            It is on the schema, it validates, it publishes — and nothing reads
            it: `outbound.place` gates on a single tenant-wide
            `OUTBOUND_MAX_IN_FLIGHT` count with no per-card reservation. A
            slider for it would be the exact failure `test_outbound_conduct.py`
            was written about, "configured, validated, versioned and
            publishable, and had no effect", except authored on purpose. It
            wants a real reservation in the fleet gate first. */}
        <NumberField
          id="ob-ivr"
          label="IVR traversal budget"
          value={ob.ivr_max_sec}
          min={15}
          max={300}
          suffix="sec"
          disabled={!editable || !ob.ivr_traversal}
          hint={ob.ivr_traversal ? undefined : "Enable IVR traversal to use this."}
          onCommit={(n) => set({ ivr_max_sec: n })}
        />
      </div>

      <div className="flex flex-wrap gap-200">
        <label className="flex items-center gap-100 text-body-small">
          <Switch
            aria-label="Carrier answering-machine detection"
            checked={ob.carrier_amd}
            disabled={!editable}
            onCheckedChange={(v) => set({ carrier_amd: v })}
          />
          <span>
            Carrier answering-machine detection
            <span className="ml-075 text-text-subtlest">
              a second signal alongside the in-band detector
            </span>
          </span>
        </label>
        <label className="flex items-center gap-100 text-body-small">
          <Switch
            aria-label="Drive DTMF through a switchboard"
            checked={ob.ivr_traversal}
            disabled={!editable}
            onCheckedChange={(v) => set({ ivr_traversal: v })}
          />
          <span>
            Drive DTMF through a switchboard
            <span className="ml-075 text-text-subtlest">to reach a human on a workplace line</span>
          </span>
        </label>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Missions
// ---------------------------------------------------------------------------

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
            <select
              id={`m-entry-${index}`}
              className={SELECT_CLASS}
              disabled={!editable}
              value={entry}
              onChange={(e) => setObjective({ entry_node: e.target.value })}
            >
              <option value="">— choose a step —</option>
              {/* The graph's own claims first: picking one of these is the only
                  way to satisfy G-OB2 without editing the flow. */}
              {Object.entries(graphEntries).map(([obj, node]) => (
                <option key={`${obj}:${node}`} value={node}>
                  {node} (claims {obj})
                </option>
              ))}
              {entry && !Object.values(graphEntries).includes(entry) ? (
                <option value={entry}>{entry} — not in the published flow</option>
              ) : null}
            </select>
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
          <select
            id={`m-cadence-${index}`}
            className={SELECT_CLASS}
            disabled={!editable}
            value={objective.cadence ?? "default"}
            onChange={(e) => setObjective({ cadence: e.target.value })}
          >
            <option value="default">default</option>
            {cadenceNames
              .filter((n) => n !== "default")
              .map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
          </select>
        </div>

        <div className="space-y-050">
          <Label htmlFor={`m-authority-${index}`}>Authority profile</Label>
          <select
            id={`m-authority-${index}`}
            className={SELECT_CLASS}
            disabled={!editable}
            value={objective.authority_profile ?? ""}
            onChange={(e) => setObjective({ authority_profile: e.target.value || null })}
          >
            <option value="">— no extra ceiling —</option>
            {vocab.authorityProfiles.map((p) => (
              <option key={p.name} value={p.name}>
                {p.name}
                {p.ceilingInr === null ? "" : ` (₹${p.ceilingInr})`}
              </option>
            ))}
          </select>
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
        {(productsQuery.data ?? []).length === 0 ? (
          <p className="text-body-tiny text-text-subtle">Product catalog unavailable.</p>
        ) : null}
      </fieldset>

      <fieldset className="space-y-075 rounded-medium border border-border bg-surface-sunken/40 p-100">
        <legend className="px-050 text-body-small font-medium text-text">
          When a machine answers
        </legend>
        <div className="grid gap-100 sm:grid-cols-3">
          <div className="space-y-050">
            <Label htmlFor={`m-vm-${index}`}>Leave a message</Label>
            <select
              id={`m-vm-${index}`}
              className={SELECT_CLASS}
              disabled={!editable}
              value={vm.leave ?? "first_attempt_only"}
              onChange={(e) =>
                setObjective({ voicemail: { ...vm, leave: e.target.value as VoicemailMode } })
              }
            >
              {vocab.voicemailModes.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
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
          <select
            aria-label="Add a mission"
            className={cn(SELECT_CLASS, "w-auto")}
            disabled={!editable || available.length === 0}
            value=""
            onChange={(e) => {
              if (e.target.value) add(e.target.value);
            }}
          >
            <option value="">{available.length ? "Add a mission…" : "All missions added"}</option>
            {available.map((o) => (
              <option key={o} value={o}>
                {o}
              </option>
            ))}
          </select>
          <Plus aria-hidden className="size-100 text-text-subtlest" />
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

// ---------------------------------------------------------------------------
// Cadences
// ---------------------------------------------------------------------------

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
            const name = e.target.value.trim() || "default";
            if (name === cadence.name) return;
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
        <div className="space-y-050">
          <Label htmlFor={`c-tod-${index}`}>Time of day</Label>
          <select
            id={`c-tod-${index}`}
            className={SELECT_CLASS}
            disabled={!editable}
            value={cadence.time_of_day ?? "engine"}
            onChange={(e) => set({ time_of_day: e.target.value as TimeOfDay })}
          >
            {vocab.timeOfDay.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="space-y-050">
        <Label htmlFor={`c-escalate-${index}`}>When the attempts run out</Label>
        <select
          id={`c-escalate-${index}`}
          className={cn(SELECT_CLASS, "sm:w-1/2")}
          disabled={!editable}
          value={cadence.escalate_to ?? ""}
          onChange={(e) => set({ escalate_to: e.target.value || null })}
        >
          <option value="">— stop, escalate to nobody —</option>
          <option value="human">human</option>
          {handoffTargets.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
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
          time_of_day: "engine",
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

// ---------------------------------------------------------------------------
// After the call
// ---------------------------------------------------------------------------

export function PostCallEditor({
  card,
  onChange,
  vocab,
  editable,
}: Omit<OutboundEditorProps, "graphEntries">) {
  const ob = resolvedOutbound(card);
  const pc = ob.post_call;
  const cardTools = useMemo(() => card.tools?.include ?? [], [card.tools]);
  // G-OB6 checks the union: a rule may name a Closer verb *or* any tool this
  // card includes, which is what lets a client add an action without a code
  // change. Offering only the verbs would hide half the vocabulary.
  const actions = useMemo(
    () => Array.from(new Set([...vocab.postCallActions, ...cardTools])).sort(),
    [vocab.postCallActions, cardTools],
  );
  const setPostCall = (next: Partial<CardPostCall>) =>
    patchOutbound(card, onChange, { post_call: { ...pc, ...next } });

  const setRule = (index: number, next: Partial<PostCallRule>) =>
    setPostCall({ on_outcome: pc.on_outcome.map((r, i) => (i === index ? { ...r, ...next } : r)) });

  const used = new Set(pc.on_outcome.map((r) => r.when));
  const unruled = vocab.outcomeCodes.filter((c) => !used.has(c));

  return (
    <div className="space-y-150 rounded-medium border border-border bg-surface p-150">
      <div>
        <h3 className="text-body font-semibold">After the call, on this card</h3>
        <p className="mt-025 max-w-prose text-body-small text-text-subtle">
          Versioned with the agent, so the sentence it said and the follow-up that sentence produced
          carry one version number.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-200">
        <label className="flex items-center gap-100 text-body-small">
          <Switch
            aria-label="Send a written record of what was agreed"
            checked={pc.written_followup}
            disabled={!editable}
            onCheckedChange={(v) => setPostCall({ written_followup: v })}
          />
          Send a written record of what was agreed
        </label>
        <label className="flex items-center gap-100 text-body-small">
          <Switch
            aria-label="Honour promises the agent made"
            checked={pc.obligations}
            disabled={!editable}
            onCheckedChange={(v) => setPostCall({ obligations: v })}
          />
          Honour promises the agent made
        </label>
        <div className="flex items-center gap-100">
          <Label htmlFor="pc-qa">QA</Label>
          <select
            id="pc-qa"
            className={cn(SELECT_CLASS, "w-auto")}
            disabled={!editable}
            value={pc.qa}
            onChange={(e) => setPostCall({ qa: e.target.value as PostCallQa })}
          >
            {vocab.qaModes.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="space-y-100">
        <div className="flex flex-wrap items-center gap-100">
          <span className="text-body-small font-medium">Rules</span>
          <span className="text-body-tiny text-text-subtlest">
            one outcome, and what it triggers
          </span>
          <span className="ml-auto">
            <select
              aria-label="Add a rule"
              className={cn(SELECT_CLASS, "w-auto")}
              disabled={!editable || unruled.length === 0}
              value=""
              onChange={(e) => {
                if (!e.target.value) return;
                setPostCall({ on_outcome: [...pc.on_outcome, { when: e.target.value, do: [] }] });
              }}
            >
              <option value="">
                {unruled.length ? "Add a rule…" : "Every outcome has a rule"}
              </option>
              {unruled.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </span>
        </div>

        {pc.on_outcome.length === 0 ? (
          <p className="max-w-prose text-body-small text-text-subtle">
            No rules. Every outcome still gets recorded; nothing is triggered by it here.
          </p>
        ) : (
          <ul className="divide-y divide-border rounded-medium border border-border">
            {pc.on_outcome.map((rule, index) => (
              <li key={`${rule.when}-${index}`} className="space-y-075 px-150 py-100">
                <div className="flex items-center gap-100">
                  <span className="font-mono text-body-small font-semibold">{rule.when}</span>
                  {!vocab.outcomeCodes.includes(rule.when ?? "") ? (
                    <Lozenge tone="danger">unknown outcome — G-OB6</Lozenge>
                  ) : null}
                  <span className="ml-auto">
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={!editable}
                      onClick={() =>
                        setPostCall({ on_outcome: pc.on_outcome.filter((_, i) => i !== index) })
                      }
                    >
                      <Trash2 aria-hidden className="size-100" />
                      <span className="sr-only">Remove rule for {rule.when}</span>
                    </Button>
                  </span>
                </div>
                <CodeGrid
                  legend="Then"
                  options={actions}
                  selected={rule.do ?? []}
                  disabled={!editable}
                  onToggle={(a) => setRule(index, { do: toggleIn(rule.do ?? [], a) })}
                />
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
