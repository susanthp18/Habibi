/** One edge: its condition over the graph's variables. */
import { ArrowRight, Plus, Trash2, Wand2 } from "lucide-react";

import {
  OPERATOR_LABELS,
  UNARY_OPERATORS,
  defaultCondition,
  type FlowCondition,
  type FlowConditionType,
  type FlowEdge,
  type FlowGraph,
  type FlowIssue,
  type FlowOperator,
  useFlowVariables,
} from "@/api/flow";
import STUDIO_VOCABULARY from "@/lib/studio-vocabulary.json";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { SelectField } from "@/components/ui/select";
import {
  BOOLEAN_VALUES,
  DeleteButton,
  InspectorShell,
  IssueList,
  OPERATORS,
  Section,
  Segmented,
  booleanVariables,
  knownVariables,
} from "./chrome";

export function EdgeInspector({
  edge,
  sourceName,
  targetName,
  issues,
  readOnly,
  graph,
  onChange,
  onDelete,
}: {
  edge: FlowEdge;
  sourceName: string;
  targetName: string;
  issues: FlowIssue[];
  readOnly: boolean;
  /** Optional so a caller that has no graph to hand still renders free text. */
  graph?: FlowGraph;
  onChange: (next: FlowEdge) => void;
  onDelete: () => void;
}) {
  const booleans = booleanVariables(graph);
  const systemVariables = useFlowVariables();
  const variableNames = knownVariables(graph, systemVariables.data ?? []);
  const condition = edge.data.condition;
  const setCondition = (patch: Partial<FlowCondition>) => {
    if (readOnly) return;
    onChange({ ...edge, data: { condition: { ...condition, ...patch } } });
  };

  const setClause = (index: number, patch: Partial<FlowCondition["clauses"][number]>) =>
    setCondition({
      clauses: condition.clauses.map((c, i) => (i === index ? { ...c, ...patch } : c)),
    });

  return (
    <InspectorShell
      icon={<ArrowRight className="h-4 w-4" />}
      title="Transition"
      subtitle={
        <>
          {sourceName} <span className="text-text-subtlest">→</span> {targetName}
        </>
      }
      footer={<DeleteButton label="Delete transition" disabled={readOnly} onClick={onDelete} />}
    >
      <IssueList issues={issues} />

      <Section label="Fires when">
        <Segmented
          value={condition.type}
          disabled={readOnly}
          onChange={(next) =>
            // Switching type replaces the condition wholesale — a half-kept
            // shape would let an invisible field decide a live transition.
            next !== condition.type &&
            onChange({
              ...edge,
              data: { condition: defaultCondition(next as FlowConditionType) },
            })
          }
          options={[
            {
              value: "prompt",
              label: "The model decides",
              title: "Offered to the model as a tool it may call",
            },
            {
              value: "expression",
              label: "A captured value",
              title: "Evaluated by the runtime, never shown to the model",
            },
            {
              value: "always",
              label: "Always",
              title: "Moves on as soon as the step finishes",
            },
          ]}
        />
      </Section>

      {condition.type === "prompt" && (
        <Section
          label="Condition"
          hint={
            <span className="flex items-start gap-050">
              <Wand2 className="mt-025 h-3 w-3 shrink-0" />
              This text becomes the description of a tool the model can call. Write it as the
              situation, not as an instruction.
            </span>
          }
        >
          <Textarea
            className="min-h-[6rem] resize-y leading-relaxed"
            value={condition.prompt}
            disabled={readOnly}
            onChange={(e) => setCondition({ prompt: e.target.value })}
            placeholder="e.g. The caller agreed to a payment date"
          />
        </Section>
      )}

      {condition.type === "expression" && (
        <Section label={`Clauses · ${condition.clauses.length}`}>
          <Segmented
            value={condition.match}
            disabled={readOnly}
            onChange={(next) => setCondition({ match: next })}
            options={[
              { value: "all", label: "Match all", title: "Every clause must hold" },
              { value: "any", label: "Match any", title: "One clause is enough" },
            ]}
          />
          <div className="space-y-050">
            {condition.clauses.map((clause, i) => (
              <div key={i} className="flex gap-050 rounded-medium border border-border p-075">
                <Input
                  className="font-mono"
                  value={clause.variable}
                  placeholder="variable"
                  list="flow-variable-names"
                  disabled={readOnly}
                  onChange={(e) => setClause(i, { variable: e.target.value })}
                />
                <datalist id="flow-variable-names">
                  {variableNames.map((name) => (
                    <option key={name} value={name} />
                  ))}
                </datalist>
                <SelectField
                  aria-label="Operator"
                  className="w-[9.375rem] shrink-0"
                  value={clause.operator}
                  disabled={readOnly}
                  onChange={(v) => setClause(i, { operator: v as FlowOperator })}
                  options={OPERATORS.map((op) => ({ value: op, label: OPERATOR_LABELS[op] }))}
                />
                {!UNARY_OPERATORS.has(clause.operator) ? (
                  booleans.has(clause.variable) ? (
                    <SelectField
                      aria-label="Value"
                      placeholder="choose…"
                      className="w-[7.5rem] shrink-0"
                      value={clause.value ?? ""}
                      disabled={readOnly}
                      onChange={(v) => setClause(i, { value: v })}
                      options={BOOLEAN_VALUES}
                    />
                  ) : (
                    <Input
                      value={clause.value ?? ""}
                      placeholder="value"
                      disabled={readOnly}
                      onChange={(e) => setClause(i, { value: e.target.value })}
                    />
                  )
                ) : null}
                <Button
                  variant="ghost"
                  size="icon"
                  disabled={readOnly}
                  title="Remove this clause"
                  className="shrink-0 text-text-subtle hover:text-text-danger"
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
            disabled={readOnly}
            onClick={() =>
              setCondition({
                clauses: [...condition.clauses, { variable: "", operator: "equals", value: "" }],
              })
            }
          >
            <Plus className="mr-050 h-3.5 w-3.5" /> Add clause
          </Button>
        </Section>
      )}

      {condition.type === "always" && (
        <p className="rounded-medium border border-border bg-surface-sunken px-100 py-075 text-body-small leading-relaxed text-text-subtle">
          Moves on as soon as this step finishes. It must be the step&apos;s only transition — any
          sibling could never fire.
        </p>
      )}
    </InspectorShell>
  );
}
