import { useEffect, useState } from "react";
import { usePublishedPromptVersion } from "@/api/prompt-studio";
import type { CardHandoff, HandoffCarry } from "@/api/agent-card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { SelectField } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";

const CARRY: { value: HandoffCarry; label: string }[] = [
  { value: "brief", label: "brief — the fact packet" },
  { value: "full", label: "full — packet plus the last turns (prefix tokens)" },
];

/**
 * One typed handoff edge, every field the compiler reads. `when` reaches the
 * model as the target enum's description; `carry`, `entry_node`,
 * `bridge_line` and `refusal_line` shape the hop itself, and until this
 * editor existed a card could only carry their defaults.
 */
export function HandoffEdgeEditor({
  edge,
  onChange,
}: {
  edge: CardHandoff;
  onChange: (next: CardHandoff) => void;
}) {
  const targetId = edge.to_bot_id ?? "";
  // The entry node is a local name in the target's published graph -- its
  // draft may name steps the runtime will never see.
  const published = usePublishedPromptVersion(targetId);
  const nodes = (published.data?.flow?.nodes ?? []).filter((n) => n.type !== "end");
  const set = (patch: Partial<CardHandoff>) => onChange({ ...edge, ...patch });
  // Edited as text and parsed on blur, so a half-typed line is not a schema.
  const [payloadText, setPayloadText] = useState(() => payloadFieldsText(edge.payload_schema));
  useEffect(() => {
    setPayloadText(payloadFieldsText(edge.payload_schema));
  }, [edge.to_bot_id, edge.payload_schema]);
  const entryOptions = [
    { value: "", label: "the target's start node" },
    ...nodes.map((n) => ({ value: n.key, label: `${n.data.name} (${n.key})` })),
  ];
  const entryKnown = !edge.entry_node || nodes.some((n) => n.key === edge.entry_node);

  return (
    <div className="grid gap-100 rounded-medium border border-border bg-surface-sunken/40 p-150 md:grid-cols-2">
      <label className="space-y-025 md:col-span-2">
        <Label className="text-body-tiny">When</Label>
        <Input
          size="compact"
          placeholder="e.g. caller asks about a policy"
          value={edge.when ?? ""}
          onChange={(e) => set({ when: e.target.value })}
        />
      </label>
      <div className="space-y-025">
        <Label className="text-body-tiny">Carry</Label>
        <SelectField
          aria-label="Carry"
          size="compact"
          value={edge.carry ?? "brief"}
          onChange={(v) => set({ carry: v as HandoffCarry })}
          options={CARRY}
        />
      </div>
      <div className="space-y-025">
        <Label className="text-body-tiny">Enter at</Label>
        {published.isError ? (
          <p className="text-body-tiny text-text-danger">
            The target&apos;s published graph could not be read; its steps cannot be offered.
          </p>
        ) : (
          <SelectField
            aria-label="Entry node"
            size="compact"
            value={edge.entry_node ?? ""}
            onChange={(v) => set({ entry_node: v })}
            options={
              entryKnown
                ? entryOptions
                : [
                    ...entryOptions,
                    {
                      value: edge.entry_node ?? "",
                      label: `${edge.entry_node} (not in the published graph)`,
                    },
                  ]
            }
          />
        )}
        {published.data === null ? (
          <p className="text-body-tiny text-text-subtle">
            Nothing is published on the target yet; the hop enters its start node.
          </p>
        ) : null}
      </div>
      <label className="space-y-025">
        <Label className="text-body-tiny">Bridge line — a direction, not a script</Label>
        <Textarea
          rows={2}
          placeholder="acknowledge briefly, then say a specialist is joining"
          value={edge.bridge_line ?? ""}
          onChange={(e) => set({ bridge_line: e.target.value })}
        />
      </label>
      <label className="space-y-025">
        <Label className="text-body-tiny">Refusal line — when the hop is over the cap</Label>
        <Textarea
          rows={2}
          placeholder="apologise, and offer a callback from the team"
          value={edge.refusal_line ?? ""}
          onChange={(e) => set({ refusal_line: e.target.value })}
        />
      </label>
      <label className="space-y-025">
        <Label className="text-body-tiny">
          Payload fields — what the model may hand across, one per line as{" "}
          <span className="font-mono">field: what it holds</span>
        </Label>
        <Textarea
          rows={3}
          placeholder={
            "policy_number: the policy the caller asked about\nlapse_reason: their words for why it lapsed"
          }
          value={payloadText}
          onChange={(e) => setPayloadText(e.target.value)}
          onBlur={() => set({ payload_schema: parsePayloadFields(payloadText) })}
        />
        <p className="text-body-tiny text-text-subtle">
          The runtime refuses a payload with a field not named here (G-F7 gates the list at
          publish). Empty means the hop carries only the packet.
        </p>
      </label>
    </div>
  );
}

/** `field: description` lines → the schema map the edge stores; blank lines ignored. */
export function parsePayloadFields(text: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line) continue;
    const i = line.indexOf(":");
    const key = (i === -1 ? line : line.slice(0, i)).trim();
    if (!key) continue;
    out[key] = i === -1 ? "" : line.slice(i + 1).trim();
  }
  return out;
}

function payloadFieldsText(schema: Record<string, unknown> | undefined): string {
  return Object.entries(schema ?? {})
    .map(([k, v]) => (v ? `${k}: ${String(v)}` : k))
    .join("\n");
}
