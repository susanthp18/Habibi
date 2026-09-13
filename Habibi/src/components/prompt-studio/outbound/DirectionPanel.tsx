import type { CardOutbound, Direction, PoolKind } from "@/api/agent-card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Lozenge } from "@/components/ui/lozenge";
import { Switch } from "@/components/ui/switch";
import { SelectField } from "@/components/ui/select";
import { NumberField, patchOutbound, resolvedOutbound, type OutboundEditorProps } from "./shared";

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
          <SelectField
            id="ob-direction"
            size="compact"
            disabled={!editable}
            value={ob.direction}
            onChange={(v) => set({ direction: v as Direction })}
            options={vocab.directions.map((d) => ({ value: d, label: d }))}
          />
        </div>

        <div className="space-y-050">
          <Label htmlFor="ob-pool">Caller-ID pool</Label>
          {poolNames.length > 0 ? (
            <SelectField
              id="ob-pool"
              size="compact"
              disabled={!editable}
              value={ob.number_pool ?? ""}
              onChange={(v) => {
                const name = v || null;
                const match = vocab.numberPools.find((p) => p.name === name);
                // Adopt the pool's own kind on selection. Choosing a 1600-series
                // pool and leaving pool_kind on "general" is the combination
                // G-OB4 cannot catch — the gate trusts the card.
                set({
                  number_pool: name,
                  ...(match ? { pool_kind: match.kind as PoolKind } : {}),
                });
              }}
              options={[
                { value: "", label: "— share the general pool —" },
                ...vocab.numberPools.map((p) => ({
                  value: p.name,
                  label: `${p.name} (${p.kind})`,
                })),
              ]}
            />
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
          <SelectField
            id="ob-pool-kind"
            size="compact"
            disabled={!editable}
            value={ob.pool_kind}
            onChange={(v) => set({ pool_kind: v as PoolKind })}
            options={vocab.poolKinds.map((k) => ({ value: k, label: k }))}
          />
          {kindDisagrees ? (
            <p className="text-body-tiny text-text-danger">
              Pool {knownPool?.name} is registered as {knownPool?.kind}. G-OB4 reads the card, so
              this mismatch decides whether offers are permitted.
            </p>
          ) : null}
        </div>

        {/* `concurrency_share` and the cadence's `time_of_day` are gone from the
            card, not merely uncontrolled here: both published, validated and
            were read by nobody. They come back with a reservation in the fleet
            gate and a dial-time scheduler respectively — with a consumer, or
            not at all. */}
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
