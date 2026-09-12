/** One node: its role, prompt, tools, mission entries and the variables it sets. */
import { ArrowRight, Flag, PhoneOff, Plus, Trash2 } from "lucide-react";

import { type FlowIssue, type FlowNode, type FlowTool, type FlowVariable } from "@/api/flow";
import STUDIO_VOCABULARY from "@/lib/studio-vocabulary.json";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { SelectField } from "@/components/ui/select";
import {
  CheckboxRow,
  DeleteButton,
  FieldLabel,
  InspectorShell,
  IssueList,
  MissionEntries,
  Section,
  Segmented,
  ToolList,
  VARIABLE_TYPES,
  withSelectedStrays,
} from "./chrome";

export function NodeInspector({
  node,
  tools,
  reservedKeys,
  issues,
  readOnly,
  onChange,
  onDelete,
}: {
  node: FlowNode;
  tools: FlowTool[];
  reservedKeys: Record<string, string>;
  issues: FlowIssue[];
  readOnly: boolean;
  onChange: (next: FlowNode) => void;
  onDelete: () => void;
}) {
  // The canvas blocked drags and deletes in read-only mode and left every
  // field in here live, so a published version you opened to look at could be
  // renamed, re-instructed and re-tooled — silently, because the only guard
  // was on the two gestures nobody reaches for first.
  const set = (patch: Partial<FlowNode>) => {
    if (readOnly) return;
    onChange({ ...node, ...patch });
  };
  const setData = (patch: Partial<FlowNode["data"]>) => {
    if (readOnly) return;
    onChange({ ...node, data: { ...node.data, ...patch } });
  };

  const toggleMission = (key: string) => {
    const current = node.data.entryFor ?? [];
    setData({
      entryFor: current.includes(key) ? current.filter((m) => m !== key) : [...current, key],
    });
  };

  const toggleTool = (key: string) => {
    const has = node.data.tools.includes(key);
    setData({
      tools: has ? node.data.tools.filter((t) => t !== key) : [...node.data.tools, key],
    });
  };

  const setVariable = (index: number, patch: Partial<FlowVariable>) => {
    const next = node.data.extractVariables.map((v, i) => (i === index ? { ...v, ...patch } : v));
    setData({ extractVariables: next });
  };

  const reservedHint = reservedKeys[node.key];
  const isEnd = node.type === "end";

  return (
    <InspectorShell
      icon={
        isEnd ? (
          <PhoneOff className="h-4 w-4 text-text-danger" />
        ) : node.data.isStart ? (
          <Flag className="h-4 w-4 text-text-brand" />
        ) : (
          <ArrowRight className="h-4 w-4" />
        )
      }
      title={node.data.name || "Untitled step"}
      subtitle={
        <>
          <span className="font-mono">{node.key}</span>
          <span className="mx-050">·</span>
          {isEnd ? "ends the call" : node.data.isStart ? "start step" : "step"}
        </>
      }
      footer={
        <DeleteButton
          label={isEnd ? "Delete end node" : "Delete step"}
          disabled={readOnly}
          onClick={onDelete}
        />
      }
    >
      <IssueList issues={issues} />

      <Section label="Identity">
        <label className="block space-y-050">
          <FieldLabel>Name</FieldLabel>
          <Input
            value={node.data.name}
            disabled={readOnly}
            placeholder="What this step is called"
            onChange={(e) => setData({ name: e.target.value })}
          />
        </label>
        <label className="block space-y-050">
          <FieldLabel
            hint={
              reservedHint ? (
                <>
                  <strong className="text-text-subtle">Reserved key.</strong> {reservedHint}
                </>
              ) : (
                "The stable name the runtime transitions by. Renaming the step does not change it."
              )
            }
          >
            Key
          </FieldLabel>
          <Input
            className="font-mono"
            value={node.key}
            disabled={readOnly}
            onChange={(e) => set({ key: e.target.value })}
          />
        </label>
      </Section>

      {!isEnd && (
        <>
          <Section label="What the bot does here">
            <Segmented
              value={node.data.instructionType}
              disabled={readOnly}
              onChange={(next) => setData({ instructionType: next })}
              options={[
                {
                  value: "prompt",
                  label: "Instruct the model",
                  title: "Describe the goal; the model chooses its words",
                },
                {
                  value: "say",
                  label: "Say verbatim",
                  title: "Spoken word for word, exactly as written",
                },
              ]}
            />
            <Textarea
              className="min-h-[8rem] resize-y leading-relaxed"
              value={node.data.instructions}
              disabled={readOnly}
              onChange={(e) => setData({ instructions: e.target.value })}
              placeholder={
                node.data.instructionType === "say"
                  ? "The exact words to speak."
                  : "What the bot should accomplish at this step."
              }
            />
            <p className="text-body-small text-text-subtlest">
              Use <code className="font-mono text-text-subtle">{"{{variable}}"}</code> to insert a
              captured value.
            </p>
          </Section>

          <Section label="Behaviour">
            <div className="space-y-025">
              <CheckboxRow
                checked={node.data.isStart}
                disabled={readOnly}
                label="Start step (inbound)"
                hint="Where a call that came TO us begins. Only one step can hold it. An outbound mission does not start here — give it its own door below."
                onChange={(next) => setData({ isStart: next })}
              />
              <CheckboxRow
                checked={!node.data.respondImmediately}
                disabled={readOnly}
                label="Listen before speaking"
                onChange={(next) => setData({ respondImmediately: !next })}
              />
              {/* Hidden only while it is empty AND the step speaks first. An
                  authored line stays visible whatever the checkbox says: on a
                  prompt step the runtime speaks it either way, and on a Say step
                  it is never read — both are things the author has to be able
                  to see to fix. */}
              {(!node.data.respondImmediately || (node.data.entryLine ?? "").trim()) && (
                <label className="block space-y-050 rounded-medium bg-surface-sunken px-100 py-075">
                  <FieldLabel
                    hint={
                      node.data.instructionType === "say"
                        ? "Not spoken on a Say verbatim step — the scripted text above is the line. Clear this, or switch the step to Instruct the model."
                        : "A step that listens without speaking is silent until someone talks. If the caller is moved here right after answering, give them this line — otherwise they hear nothing."
                    }
                  >
                    Line spoken on entry
                  </FieldLabel>
                  <Input
                    value={node.data.entryLine}
                    disabled={readOnly}
                    placeholder="Happy to set that up."
                    onChange={(e) => setData({ entryLine: e.target.value })}
                  />
                </label>
              )}
              <CheckboxRow
                checked={node.data.endConversation}
                disabled={readOnly}
                label="End the call after this step"
                onChange={(next) => setData({ endConversation: next })}
              />
            </div>
          </Section>

          <MissionEntries node={node} readOnly={readOnly} onToggle={toggleMission} />

          <Section
            label={`Tools · ${node.data.tools.length}`}
            hint="Offered to the model at this step, on top of the graph's global tools."
          >
            <ToolList
              tools={withSelectedStrays(tools, node.data.tools)}
              selected={(key) => node.data.tools.includes(key)}
              disabled={readOnly}
              onToggle={toggleTool}
            />
          </Section>

          <Section
            label={`Capture from the caller · ${node.data.extractVariables.length}`}
            hint={
              node.data.extractVariables.length === 0
                ? "Nothing captured here. Add a variable to test it in a transition."
                : undefined
            }
          >
            <div className="space-y-075">
              {node.data.extractVariables.map((v, i) => (
                <div key={i} className="space-y-050 rounded-medium border border-border p-075">
                  <div className="flex gap-050">
                    <Input
                      className="font-mono"
                      value={v.key}
                      placeholder="variable_key"
                      disabled={readOnly}
                      onChange={(e) => setVariable(i, { key: e.target.value })}
                    />
                    <SelectField
                      aria-label="Variable type"
                      className="w-[7.5rem] shrink-0"
                      value={v.type}
                      disabled={readOnly}
                      onChange={(val) => setVariable(i, { type: val as FlowVariable["type"] })}
                      options={VARIABLE_TYPES}
                    />
                    <Button
                      variant="ghost"
                      size="icon"
                      disabled={readOnly}
                      title="Remove this variable"
                      className="shrink-0 text-text-subtle hover:text-text-danger"
                      onClick={() =>
                        setData({
                          extractVariables: node.data.extractVariables.filter((_, j) => j !== i),
                        })
                      }
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                  <Input
                    value={v.description}
                    placeholder="What is this? (the model reads it)"
                    disabled={readOnly}
                    onChange={(e) => setVariable(i, { description: e.target.value })}
                  />
                </div>
              ))}
            </div>
            <Button
              variant="outline"
              size="sm"
              disabled={readOnly}
              onClick={() =>
                setData({
                  extractVariables: [
                    ...node.data.extractVariables,
                    { key: "", description: "", type: "string" },
                  ],
                })
              }
            >
              <Plus className="mr-050 h-3.5 w-3.5" /> Add variable
            </Button>
          </Section>
        </>
      )}
    </InspectorShell>
  );
}

// --------------------------------------------------------------------- edge

/**
 * Variables any step of this graph captures, keyed to their declared type.
 *
 * The clause editor is free text, which is how `equals True` got written: the
 * extract tool declares `type: boolean`, so the model returns JSON true, and
 * the value used to be stored `"True"` while the one system boolean the editor
 * teaches against — `identity_verified` — was stored `"true"`. Both spell it
 * `true` now, and a picker is what stops the next author guessing.
 */
/** System variables plus every value the graph's steps capture. */
