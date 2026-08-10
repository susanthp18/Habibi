import { Plus, Trash2, Wand2 } from "lucide-react";

import {
  OPERATOR_LABELS,
  UNARY_OPERATORS,
  defaultCondition,
  type FlowCondition,
  type FlowConditionType,
  type FlowEdge,
  type FlowIssue,
  type FlowNode,
  type FlowOperator,
  type FlowTool,
  type FlowVariable,
} from "@/api/flow";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const OPERATORS = Object.keys(OPERATOR_LABELS) as FlowOperator[];

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-050">
      <div className="text-body-small font-semibold text-text-subtlest">{label}</div>
      {children}
    </div>
  );
}

const inputCls =
  "w-full rounded-small border border-border bg-surface px-100 py-050 text-body-small text-text outline-none focus:border-border-brand";

function IssueList({ issues }: { issues: FlowIssue[] }) {
  if (issues.length === 0) return null;
  return (
    <ul className="space-y-050">
      {issues.map((issue, i) => (
        <li
          key={`${issue.code}-${i}`}
          className={cn(
            "rounded-small px-100 py-075 text-body-small",
            issue.severity === "error"
              ? "bg-background-danger text-text-danger"
              : "bg-surface-sunken text-text-subtle",
          )}
        >
          {issue.message}
        </li>
      ))}
    </ul>
  );
}

// --------------------------------------------------------------------- node

export function NodeInspector({
  node,
  tools,
  reservedKeys,
  issues,
  onChange,
  onDelete,
}: {
  node: FlowNode;
  tools: FlowTool[];
  reservedKeys: Record<string, string>;
  issues: FlowIssue[];
  onChange: (next: FlowNode) => void;
  onDelete: () => void;
}) {
  const set = (patch: Partial<FlowNode>) => onChange({ ...node, ...patch });
  const setData = (patch: Partial<FlowNode["data"]>) =>
    onChange({ ...node, data: { ...node.data, ...patch } });

  const toggleTool = (key: string) => {
    const has = node.data.tools.includes(key);
    setData({
      tools: has
        ? node.data.tools.filter((t) => t !== key)
        : [...node.data.tools, key],
    });
  };

  const setVariable = (index: number, patch: Partial<FlowVariable>) => {
    const next = node.data.extractVariables.map((v, i) =>
      i === index ? { ...v, ...patch } : v,
    );
    setData({ extractVariables: next });
  };

  const reservedHint = reservedKeys[node.key];

  return (
    <div className="space-y-150">
      <IssueList issues={issues} />

      <Section label="Name">
        <input
          className={inputCls}
          value={node.data.name}
          onChange={(e) => setData({ name: e.target.value })}
        />
      </Section>

      <Section label="Key">
        <input
          className={cn(inputCls, "font-mono")}
          value={node.key}
          onChange={(e) => set({ key: e.target.value })}
        />
        <p className="text-body-small leading-relaxed text-text-subtlest">
          {reservedHint ? (
            <>
              <strong className="text-text-subtle">Reserved key.</strong>{" "}
              {reservedHint}
            </>
          ) : (
            "The stable name the runtime transitions by. Renaming the node above does not change it."
          )}
        </p>
      </Section>

      {node.type === "conversation" && (
        <>
          <Section label="What the bot does here">
            <div className="mb-050 flex gap-050">
              {(["prompt", "say"] as const).map((mode) => (
                <button
                  key={mode}
                  type="button"
                  onClick={() => setData({ instructionType: mode })}
                  className={cn(
                    "rounded-small px-100 py-050 text-body-small",
                    node.data.instructionType === mode
                      ? "bg-background-brand-subtlest font-medium text-text-brand"
                      : "text-text-subtle hover:bg-surface-sunken",
                  )}
                >
                  {mode === "prompt" ? "Instruct the model" : "Say verbatim"}
                </button>
              ))}
            </div>
            <textarea
              className={cn(inputCls, "min-h-[7rem] resize-y leading-relaxed")}
              value={node.data.instructions}
              onChange={(e) => setData({ instructions: e.target.value })}
              placeholder={
                node.data.instructionType === "say"
                  ? "The exact words to speak."
                  : "What the bot should accomplish at this step."
              }
            />
            <p className="text-body-small text-text-subtlest">
              Use <code className="font-mono">{"{{variable}}"}</code> to insert a
              captured value.
            </p>
          </Section>

          <Section label="Behaviour">
            <label className="flex items-center gap-075 text-body-small text-text">
              <input
                type="checkbox"
                checked={node.data.isStart}
                onChange={(e) => setData({ isStart: e.target.checked })}
              />
              Start node
            </label>
            <label className="flex items-center gap-075 text-body-small text-text">
              <input
                type="checkbox"
                checked={!node.data.respondImmediately}
                onChange={(e) => setData({ respondImmediately: !e.target.checked })}
              />
              Listen before speaking
            </label>
            <label className="flex items-center gap-075 text-body-small text-text">
              <input
                type="checkbox"
                checked={node.data.endConversation}
                onChange={(e) => setData({ endConversation: e.target.checked })}
              />
              End the call after this step
            </label>
          </Section>

          <Section label={`Tools (${node.data.tools.length})`}>
            <div className="max-h-64 space-y-025 overflow-y-auto rounded-small border border-border p-075">
              {tools.map((tool) => (
                <label
                  key={tool.key}
                  className="flex cursor-pointer items-start gap-075 rounded-small px-050 py-050 hover:bg-surface-sunken"
                  title={tool.description}
                >
                  <input
                    type="checkbox"
                    className="mt-050"
                    checked={node.data.tools.includes(tool.key)}
                    onChange={() => toggleTool(tool.key)}
                  />
                  <span className="min-w-0">
                    <span className="block font-mono text-body-small text-text">
                      {tool.key}
                      {tool.transitions && (
                        <span
                          title="This tool moves the conversation on its own"
                          className="ml-050 rounded-small bg-surface-sunken px-050 text-[0.6rem] text-text-subtle"
                        >
                          moves
                        </span>
                      )}
                    </span>
                    <span className="block truncate text-[0.7rem] text-text-subtlest">
                      {tool.description}
                    </span>
                  </span>
                </label>
              ))}
            </div>
          </Section>

          <Section label="Capture from the caller">
            {node.data.extractVariables.length === 0 && (
              <p className="text-body-small text-text-subtlest">
                Nothing captured here. Add a variable to test it in a transition.
              </p>
            )}
            <div className="space-y-075">
              {node.data.extractVariables.map((v, i) => (
                <div
                  key={i}
                  className="space-y-050 rounded-small border border-border p-075"
                >
                  <div className="flex gap-050">
                    <input
                      className={cn(inputCls, "font-mono")}
                      value={v.key}
                      placeholder="variable_key"
                      onChange={(e) => setVariable(i, { key: e.target.value })}
                    />
                    <select
                      className={inputCls}
                      value={v.type}
                      onChange={(e) =>
                        setVariable(i, {
                          type: e.target.value as FlowVariable["type"],
                        })
                      }
                    >
                      <option value="string">text</option>
                      <option value="number">number</option>
                      <option value="boolean">yes/no</option>
                    </select>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() =>
                        setData({
                          extractVariables: node.data.extractVariables.filter(
                            (_, j) => j !== i,
                          ),
                        })
                      }
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                  <input
                    className={inputCls}
                    value={v.description}
                    placeholder="What is this? (the model reads it)"
                    onChange={(e) => setVariable(i, { description: e.target.value })}
                  />
                </div>
              ))}
            </div>
            <Button
              variant="outline"
              size="sm"
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

      <Button variant="outline" size="sm" onClick={onDelete}>
        <Trash2 className="mr-050 h-3.5 w-3.5" /> Delete node
      </Button>
    </div>
  );
}

// --------------------------------------------------------------------- edge

export function EdgeInspector({
  edge,
  sourceName,
  targetName,
  issues,
  onChange,
  onDelete,
}: {
  edge: FlowEdge;
  sourceName: string;
  targetName: string;
  issues: FlowIssue[];
  onChange: (next: FlowEdge) => void;
  onDelete: () => void;
}) {
  const condition = edge.data.condition;
  const setCondition = (patch: Partial<FlowCondition>) =>
    onChange({ ...edge, data: { condition: { ...condition, ...patch } } });

  const setClause = (index: number, patch: Partial<FlowCondition["clauses"][number]>) =>
    setCondition({
      clauses: condition.clauses.map((c, i) => (i === index ? { ...c, ...patch } : c)),
    });

  return (
    <div className="space-y-150">
      <IssueList issues={issues} />

      <div className="rounded-small bg-surface-sunken px-100 py-075 text-body-small text-text-subtle">
        {sourceName} <span className="text-text-subtlest">→</span> {targetName}
      </div>

      <Section label="Fires when">
        <div className="flex flex-wrap gap-050">
          {(["prompt", "expression", "always"] as const).map((type) => (
            <button
              key={type}
              type="button"
              onClick={() =>
                // Switching type replaces the condition wholesale — a half-kept
                // shape would let an invisible field decide a live transition.
                type !== condition.type &&
                onChange({
                  ...edge,
                  data: { condition: defaultCondition(type as FlowConditionType) },
                })
              }
              className={cn(
                "rounded-small px-100 py-050 text-body-small",
                condition.type === type
                  ? "bg-background-brand-subtlest font-medium text-text-brand"
                  : "text-text-subtle hover:bg-surface-sunken",
              )}
            >
              {type === "prompt"
                ? "The model decides"
                : type === "expression"
                  ? "A captured value"
                  : "Always"}
            </button>
          ))}
        </div>
      </Section>

      {condition.type === "prompt" && (
        <Section label="Condition">
          <textarea
            className={cn(inputCls, "min-h-[5rem] resize-y")}
            value={condition.prompt}
            onChange={(e) => setCondition({ prompt: e.target.value })}
            placeholder="e.g. The caller agreed to a payment date"
          />
          <p className="flex items-start gap-050 text-body-small leading-relaxed text-text-subtlest">
            <Wand2 className="mt-025 h-3 w-3 shrink-0" />
            This text becomes the description of a tool the model can call. Write
            it as the situation, not as an instruction.
          </p>
        </Section>
      )}

      {condition.type === "expression" && (
        <Section label="Clauses">
          <div className="mb-050 flex gap-050">
            {(["all", "any"] as const).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => setCondition({ match: m })}
                className={cn(
                  "rounded-small px-100 py-050 text-body-small",
                  condition.match === m
                    ? "bg-background-brand-subtlest font-medium text-text-brand"
                    : "text-text-subtle hover:bg-surface-sunken",
                )}
              >
                match {m}
              </button>
            ))}
          </div>
          <div className="space-y-075">
            {condition.clauses.map((clause, i) => (
              <div key={i} className="flex gap-050">
                <input
                  className={cn(inputCls, "font-mono")}
                  value={clause.variable}
                  placeholder="variable"
                  onChange={(e) => setClause(i, { variable: e.target.value })}
                />
                <select
                  className={inputCls}
                  value={clause.operator}
                  onChange={(e) =>
                    setClause(i, { operator: e.target.value as FlowOperator })
                  }
                >
                  {OPERATORS.map((op) => (
                    <option key={op} value={op}>
                      {OPERATOR_LABELS[op]}
                    </option>
                  ))}
                </select>
                {!UNARY_OPERATORS.has(clause.operator) && (
                  <input
                    className={inputCls}
                    value={clause.value ?? ""}
                    placeholder="value"
                    onChange={(e) => setClause(i, { value: e.target.value })}
                  />
                )}
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() =>
                    setCondition({
                      clauses: condition.clauses.filter((_, j) => j !== i),
                    })
                  }
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </div>
            ))}
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() =>
              setCondition({
                clauses: [
                  ...condition.clauses,
                  { variable: "", operator: "equals", value: "" },
                ],
              })
            }
          >
            <Plus className="mr-050 h-3.5 w-3.5" /> Add clause
          </Button>
        </Section>
      )}

      {condition.type === "always" && (
        <p className="rounded-small bg-surface-sunken px-100 py-075 text-body-small leading-relaxed text-text-subtle">
          Moves on as soon as this step finishes. It must be the node's only
          transition — any sibling could never fire.
        </p>
      )}

      <Button variant="outline" size="sm" onClick={onDelete}>
        <Trash2 className="mr-050 h-3.5 w-3.5" /> Delete transition
      </Button>
    </div>
  );
}
