import {
  ArrowRight,
  Flag,
  MousePointerClick,
  PhoneOff,
  Plus,
  Settings2,
  Trash2,
  Wand2,
} from "lucide-react";

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
import { useOutboundVocabulary } from "@/api/outbound";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

const OPERATORS = Object.keys(OPERATOR_LABELS) as FlowOperator[];

/** Matches the system's Input height and chrome; `select` has no primitive. */
const selectCls =
  "focus-ring h-9 shrink-0 rounded-medium border border-border-input bg-background-input px-075 text-body-small text-text transition-colors hover:bg-background-input-hovered disabled:cursor-not-allowed disabled:opacity-50";

/**
 * The inspector is a panel, not a scrolling column of controls.
 *
 * What is being edited was previously only inferrable from the shape of the
 * form — a step and a transition both opened as an unlabelled stack of inputs,
 * and on a canvas where clicking is how you navigate, that is the one thing the
 * panel has to say first. Header names the selection, body scrolls, footer
 * holds the destructive action so it is reachable without scrolling to the
 * bottom and never sits next to "Add clause".
 */
function InspectorShell({
  icon,
  title,
  subtitle,
  footer,
  children,
}: {
  icon: React.ReactNode;
  title: React.ReactNode;
  subtitle: React.ReactNode;
  footer?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="flex h-full min-h-0 flex-col bg-surface">
      <header className="flex shrink-0 items-center gap-100 border-b border-border px-150 py-100">
        <span className="flex size-7 shrink-0 items-center justify-center rounded-small bg-surface-sunken text-text-subtle">
          {icon}
        </span>
        <span className="min-w-0">
          <span className="block truncate text-body font-semibold leading-tight text-text">
            {title}
          </span>
          <span className="mt-025 block truncate text-body-small leading-tight text-text-subtlest">
            {subtitle}
          </span>
        </span>
      </header>
      <div className="min-h-0 flex-1 space-y-200 overflow-y-auto px-150 py-150">{children}</div>
      {footer && (
        <footer className="shrink-0 border-t border-border px-150 py-100">{footer}</footer>
      )}
    </div>
  );
}

function Section({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-075">
      <h3 className="text-body-micro font-semibold uppercase tracking-wide text-text-subtlest">
        {label}
      </h3>
      {hint && <p className="text-body-small leading-relaxed text-text-subtlest">{hint}</p>}
      {children}
    </section>
  );
}

/**
 * A real segmented control, not three loose buttons.
 *
 * These pick one of a fixed few — how a step speaks, when a transition fires,
 * how clauses combine — and rendering them as unbordered text meant the unset
 * options read as links and the set one as a highlight, with nothing saying the
 * three belonged to one choice.
 */
function Segmented<T extends string>({
  value,
  options,
  disabled,
  onChange,
}: {
  value: T;
  options: { value: T; label: string; title?: string }[];
  disabled?: boolean;
  onChange: (next: T) => void;
}) {
  return (
    <div
      role="radiogroup"
      className="inline-flex w-full rounded-medium border border-border bg-surface-sunken p-025"
    >
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={active}
            title={option.title}
            disabled={disabled}
            onClick={() => onChange(option.value)}
            className={cn(
              "focus-ring min-w-0 flex-1 truncate rounded-small px-100 py-050 text-body-small transition-colors disabled:cursor-not-allowed disabled:opacity-50",
              active
                ? "bg-surface font-semibold text-text shadow-sm"
                : "text-text-subtle hover:text-text",
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

function FieldLabel({ children, hint }: { children: React.ReactNode; hint?: React.ReactNode }) {
  return (
    <span className="block">
      <span className="block text-body-small font-medium text-text">{children}</span>
      {hint && (
        <span className="mt-025 block text-body-small leading-relaxed text-text-subtlest">
          {hint}
        </span>
      )}
    </span>
  );
}

/**
 * Which outbound missions begin at this step — the graph's half of G-OB2.
 *
 * The card names an `entry_node` per mission and the graph claims missions with
 * `entryFor`; the compiler checks the two agree and the Outbound tab renders
 * both halves side by side. Until now only the card half was editable, so an
 * author who read "card says dpd_reminder · flow says nothing" in red on the
 * Outbound tab had no control anywhere in the studio that could make the flow
 * say anything. The field existed on the runtime model and in the API payload;
 * it was missing from the editor, which is the one place a node is authored.
 *
 * The mission list comes from `/outbound/card-vocabulary` rather than a
 * constant here, for the reason that endpoint exists: `Objective` is a Literal
 * in the card schema, and an option this panel invents builds a graph the
 * compiler rejects — the author meets the failure at the publish button holding
 * a value they picked from a list we showed them.
 */
function MissionEntries({
  node,
  readOnly,
  onToggle,
}: {
  node: FlowNode;
  readOnly?: boolean;
  onToggle: (key: string) => void;
}) {
  const vocab = useOutboundVocabulary();
  const claimed = node.data.entryFor ?? [];
  // "inbound" is `isStart`'s job and is deliberately not offered twice: a graph
  // has exactly one inbound door, and two ways to set it is two ways to
  // disagree. The endpoint already excludes it; this is belt and braces.
  const missions = (vocab.data?.objectives ?? []).filter((m) => m !== "inbound");

  return (
    <Section label="Starts these outbound missions">
      {missions.length === 0 ? (
        <p className="text-body-small text-text-subtlest">
          {vocab.isPending
            ? "Loading missions…"
            : "No outbound missions available. They come from the card vocabulary."}
        </p>
      ) : (
        <>
          <p className="text-body-small leading-relaxed text-text-subtlest">
            An outbound call does not start at the inbound step. We chose the borrower, the moment
            and the reason, so the mission enters the graph at its own step and joins the shared
            spine from there. A mission whose step is not claimed here falls back to the inbound
            start step and opens by asking the caller why they rang.
          </p>
          <div className="space-y-025">
            {missions.map((mission) => (
              <CheckboxRow
                key={mission}
                checked={claimed.includes(mission)}
                disabled={readOnly}
                label={mission}
                hint={vocab.data?.objectiveBriefs?.[mission]}
                onChange={() => onToggle(mission)}
              />
            ))}
          </div>
        </>
      )}
    </Section>
  );
}

function CheckboxRow({
  checked,
  disabled,
  label,
  hint,
  onChange,
}: {
  checked: boolean;
  disabled?: boolean;
  label: string;
  hint?: string;
  onChange: (next: boolean) => void;
}) {
  return (
    <label
      className={cn(
        "flex items-start gap-075 rounded-small px-050 py-050 text-body-small",
        disabled ? "cursor-not-allowed opacity-60" : "cursor-pointer hover:bg-surface-sunken",
      )}
    >
      <input
        type="checkbox"
        className="mt-025"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span className="min-w-0">
        <span className="block text-text">{label}</span>
        {hint && <span className="mt-025 block leading-relaxed text-text-subtlest">{hint}</span>}
      </span>
    </label>
  );
}

function DeleteButton({
  label,
  disabled,
  onClick,
}: {
  label: string;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <Button
      variant="ghost"
      size="sm"
      disabled={disabled}
      onClick={onClick}
      className="w-full justify-center text-text-danger hover:bg-background-danger hover:text-text-danger"
    >
      <Trash2 className="mr-050 h-3.5 w-3.5" /> {label}
    </Button>
  );
}

/**
 * `onSelect` turns each row into a jump to the thing it is about.
 *
 * FlowNodes states the rule this restores: "an error that only appears in a
 * list somewhere else is an error nobody fixes." The graph-level list was that
 * list — rows of prose, no way to reach the node any of them named, on a canvas
 * where the offending card is usually off-screen.
 */
function IssueList({
  issues,
  onSelect,
  nodeNames,
}: {
  issues: FlowIssue[];
  onSelect?: (issue: FlowIssue) => void;
  nodeNames?: Map<string, string>;
}) {
  if (issues.length === 0) return null;
  return (
    <ul className="space-y-050">
      {issues.map((issue, i) => {
        const target =
          (issue.nodeId && nodeNames?.get(issue.nodeId)) || (issue.edgeId ? "a transition" : null);
        const clickable = Boolean(onSelect && (issue.nodeId || issue.edgeId));
        const tone =
          issue.severity === "error"
            ? "border-border-danger bg-background-danger-subtler text-text-danger-bolder"
            : "border-border-warning bg-background-warning-subtler text-text-warning-bolder";
        const body = (
          <>
            <span className="block leading-relaxed">{issue.message}</span>
            {target && <span className="mt-025 block text-body-micro opacity-75">{target}</span>}
          </>
        );
        return (
          <li key={`${issue.code}-${i}`}>
            {clickable ? (
              <button
                type="button"
                onClick={() => onSelect?.(issue)}
                title="Show this on the canvas"
                className={cn(
                  "focus-ring w-full cursor-pointer rounded-small border-l-2 px-100 py-075 text-left text-body-small transition-opacity hover:opacity-80",
                  tone,
                )}
              >
                {body}
              </button>
            ) : (
              <div className={cn("rounded-small border-l-2 px-100 py-075 text-body-small", tone)}>
                {body}
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}

function ToolRow({
  tool,
  checked,
  onToggle,
  disabled = false,
}: {
  tool: FlowTool;
  checked: boolean;
  onToggle: () => void;
  disabled?: boolean;
}) {
  return (
    <label
      className={cn(
        "flex items-start gap-075 rounded-small px-075 py-050",
        disabled ? "cursor-not-allowed opacity-60" : "cursor-pointer hover:bg-surface-sunken",
      )}
      title={tool.description}
    >
      <input
        type="checkbox"
        className="mt-050"
        checked={checked}
        disabled={disabled}
        onChange={onToggle}
      />
      <span className="min-w-0 flex-1">
        <span className="flex flex-wrap items-center gap-050">
          <span className="font-mono text-body-small text-text">{tool.key}</span>
          {tool.transitions && (
            <span
              title="This tool moves the conversation on its own"
              className="rounded-small bg-background-brand-subtlest px-050 text-body-micro text-text-brand"
            >
              moves
            </span>
          )}
          {/* The catalog has always reported this and the editor has always
              ignored it, so a policy-owned tool looked like any other choice.
              It is still selectable — the compiler requires it on a voice card
              — but what it is should not be a surprise. */}
          {tool.locked && (
            <span
              title="Owned by the policy engine — its wording is not the model's to choose"
              className="rounded-small bg-surface-sunken px-050 text-body-micro text-text-subtle"
            >
              policy
            </span>
          )}
        </span>
        <span className="mt-025 block truncate text-body-tiny text-text-subtlest">
          {tool.description}
        </span>
      </span>
    </label>
  );
}

function ToolList({
  tools,
  selected,
  disabled,
  onToggle,
}: {
  tools: FlowTool[];
  selected: (key: string) => boolean;
  disabled?: boolean;
  onToggle: (key: string) => void;
}) {
  return (
    <div className="max-h-72 space-y-025 overflow-y-auto rounded-medium border border-border p-050">
      {tools.length === 0 ? (
        <p className="px-050 py-050 text-body-small text-text-subtlest">
          Tool catalog unavailable.
        </p>
      ) : (
        tools.map((tool) => (
          <ToolRow
            key={tool.key}
            tool={tool}
            checked={selected(tool.key)}
            disabled={disabled}
            onToggle={() => onToggle(tool.key)}
          />
        ))
      )}
    </div>
  );
}

// -------------------------------------------------------------------- graph

/**
 * Graph-level settings, shown when nothing is selected.
 *
 * `globalTools` is the one authored field with no editor at all: it is
 * validated by `validate_graph`, exported with the built-in script, and read by
 * `flows_dynamic.py` to build the tool set every node inherits — and yet a
 * loaded graph carried global tools nobody could see, and a blank one got three
 * hardcoded ones nobody could change. Editing it meant editing stored JSON.
 */
export function GraphInspector({
  globalTools,
  tools,
  issues,
  nodeNames,
  onChange,
  onSelectIssue,
  readOnly,
}: {
  globalTools: string[];
  tools: FlowTool[];
  issues: FlowIssue[];
  nodeNames: Map<string, string>;
  onChange: (next: string[]) => void;
  onSelectIssue: (issue: FlowIssue) => void;
  readOnly: boolean;
}) {
  // Errors first: the list is what you work down before publishing, and a
  // warning ahead of a blocker buries the thing that is actually stopping you.
  const ordered = [...issues].sort((a, b) =>
    a.severity === b.severity ? 0 : a.severity === "error" ? -1 : 1,
  );
  const errorCount = issues.filter((i) => i.severity === "error").length;
  const selected = new Set(globalTools);
  const toggle = (key: string) => {
    if (readOnly) return;
    onChange(selected.has(key) ? globalTools.filter((t) => t !== key) : [...globalTools, key]);
  };

  return (
    <InspectorShell
      icon={<Settings2 className="h-4 w-4" />}
      title="Graph settings"
      subtitle="Nothing selected"
    >
      {issues.length > 0 && (
        <Section
          label={
            errorCount > 0
              ? `${errorCount} issue${errorCount === 1 ? "" : "s"} blocking publish`
              : `${issues.length} advisory issue${issues.length === 1 ? "" : "s"}`
          }
          hint="Select one to show it on the canvas."
        >
          <IssueList issues={ordered} nodeNames={nodeNames} onSelect={onSelectIssue} />
        </Section>
      )}

      <Section
        label={`Tools available from every step · ${globalTools.length}`}
        hint={
          <>
            Offered at every step on top of that step&apos;s own list. Use it for things a caller
            can ask for at any moment — knowledge lookups, escalation, hanging up.{" "}
            {/* A global marked "moves" transitions from anywhere, so it has no
                one arrow to draw and is not counted in the implicit chip. Saying
                so here is the difference between a canvas that is incomplete and
                one that is lying. */}
            A global marked <span className="font-medium">moves</span> can end or redirect the call
            from <em>any</em> step, so it is not drawn as an arrow and is not part of the implicit
            count.
          </>
        }
      >
        <ToolList
          tools={tools}
          selected={(key) => selected.has(key)}
          disabled={readOnly}
          onToggle={toggle}
        />
      </Section>

      <Section label="On this canvas">
        <ul className="space-y-075 text-body-small leading-relaxed text-text-subtlest">
          <li className="flex items-start gap-075">
            <MousePointerClick className="mt-025 h-3.5 w-3.5 shrink-0" />
            Click a step to edit it, or a transition to set when it fires.
          </li>
          <li className="flex items-start gap-075">
            <span className="mt-075 size-2 shrink-0 rounded-full border-2 border-border-brand" />
            Drag from the dot at the bottom of a step onto the next one to connect them.
          </li>
          <li className="flex items-start gap-075">
            <kbd className="mt-0 shrink-0 rounded-small border border-border bg-surface-sunken px-050 font-mono text-body-micro text-text-subtle">
              Del
            </kbd>
            Removes what is selected, and any transitions attached to it.
          </li>
        </ul>
      </Section>
    </InspectorShell>
  );
}

// --------------------------------------------------------------------- node

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
              {!node.data.respondImmediately && (
                <label className="block space-y-050 rounded-medium bg-surface-sunken px-100 py-075">
                  <FieldLabel hint="A step that listens without speaking is silent until someone talks. If the caller is moved here right after answering, give them this line — otherwise they hear nothing.">
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
              tools={tools}
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
                    <select
                      className={selectCls}
                      value={v.type}
                      disabled={readOnly}
                      onChange={(e) =>
                        setVariable(i, { type: e.target.value as FlowVariable["type"] })
                      }
                    >
                      <option value="string">text</option>
                      <option value="number">number</option>
                      <option value="boolean">yes/no</option>
                    </select>
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

export function EdgeInspector({
  edge,
  sourceName,
  targetName,
  issues,
  readOnly,
  onChange,
  onDelete,
}: {
  edge: FlowEdge;
  sourceName: string;
  targetName: string;
  issues: FlowIssue[];
  readOnly: boolean;
  onChange: (next: FlowEdge) => void;
  onDelete: () => void;
}) {
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
                  disabled={readOnly}
                  onChange={(e) => setClause(i, { variable: e.target.value })}
                />
                <select
                  className={selectCls}
                  value={clause.operator}
                  disabled={readOnly}
                  onChange={(e) => setClause(i, { operator: e.target.value as FlowOperator })}
                >
                  {OPERATORS.map((op) => (
                    <option key={op} value={op}>
                      {OPERATOR_LABELS[op]}
                    </option>
                  ))}
                </select>
                {!UNARY_OPERATORS.has(clause.operator) && (
                  <Input
                    value={clause.value ?? ""}
                    placeholder="value"
                    disabled={readOnly}
                    onChange={(e) => setClause(i, { value: e.target.value })}
                  />
                )}
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
