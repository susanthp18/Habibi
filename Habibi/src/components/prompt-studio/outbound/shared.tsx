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

import type { AgentCard, CardOutbound, CardPostCall, Objective } from "@/api/agent-card";
import type { OutboundVocabulary } from "@/api/outbound";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

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

export function patchOutbound(
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
export function NumberField({
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
export function CodeGrid({
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

export function toggleIn(list: string[], code: string): string[] {
  return list.includes(code) ? list.filter((c) => c !== code) : [...list, code];
}
