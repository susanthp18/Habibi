/** The inspector rail's shared pieces: the shell, sections, segmented controls, tool rows, issue lists. */
import { Trash2 } from "lucide-react";

import {
  OPERATOR_LABELS,
  type FlowGraph,
  type FlowIssue,
  type FlowNode,
  type FlowOperator,
  type FlowTool,
  useFlowTools,
} from "@/api/flow";
import { useOutboundVocabulary } from "@/api/outbound";
import STUDIO_VOCABULARY from "@/lib/studio-vocabulary.json";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export const OPERATORS = Object.keys(OPERATOR_LABELS) as FlowOperator[];

export const VARIABLE_TYPES = [
  { value: "string", label: "text" },
  { value: "number", label: "number" },
  { value: "boolean", label: "yes/no" },
];

export const BOOLEAN_VALUES = [
  { value: "true", label: "true" },
  { value: "false", label: "false" },
];

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

export function InspectorShell({
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

export function Section({
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

export function Segmented<T extends string>({
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

export function FieldLabel({
  children,
  hint,
}: {
  children: React.ReactNode;
  hint?: React.ReactNode;
}) {
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

export function MissionEntries({
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
  // disagree. The vocabulary endpoint lists every objective, this one included.
  const missions = (vocab.data?.objectives ?? []).filter((m) => m !== "inbound");

  return (
    <Section label="Starts these outbound missions">
      {vocab.isError ? (
        <p className="text-body-small text-text-danger">
          Could not load outbound missions — this is not a card with none.
        </p>
      ) : missions.length === 0 ? (
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

export function CheckboxRow({
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

export function DeleteButton({
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

export function IssueList({
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

export function ToolRow({
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
          {/* The compiler reports the same thing as G16. Until it is removed
              here or granted on the Tools tab, this step offers a tool the call
              will never be given. */}
          {tool.ungranted && (
            <span
              title="Not in this card's Tool Grant — the runtime drops it and the canvas does not count its hop as an exit"
              className="rounded-small bg-background-danger-subtler px-050 text-body-micro text-text-danger-bolder"
            >
              not on this card
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

/**
 * The picker, plus anything already on this step that the picker no longer
 * offers.
 *
 * `flowToolChoices` narrows the catalog to the card's grant, which is right for
 * *choosing* — but a step that already names an ungranted tool would then show
 * no row for it at all, leaving the author unable to see or remove the one
 * thing the runtime is going to drop. It is appended, marked, and removable.
 */

export function withSelectedStrays(tools: FlowTool[], selectedKeys: string[]): FlowTool[] {
  const known = new Set(tools.map((t) => t.key));
  const strays = selectedKeys
    .filter((key, i) => key && !known.has(key) && selectedKeys.indexOf(key) === i)
    .map<FlowTool>((key) => ({
      key,
      description: "Not on this card — the runtime will drop it at this step.",
      transitions: false,
      ungranted: true,
    }));
  return strays.length ? [...tools, ...strays] : tools;
}

export function ToolList({
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
  // The same query the canvas holds (react-query dedupes it); read here for
  // its state, so an empty list can say whether it is still loading, failed,
  // or genuinely empty -- three different things the list used to call one.
  const catalog = useFlowTools();
  return (
    <div className="max-h-72 space-y-025 overflow-y-auto rounded-medium border border-border p-050">
      {tools.length === 0 ? (
        <p
          className={cn(
            "px-050 py-050 text-body-small",
            catalog.isError ? "text-text-danger" : "text-text-subtlest",
          )}
        >
          {catalog.isPending
            ? "Loading the tool catalog…"
            : catalog.isError
              ? "The tool catalog could not be read; nothing here is offered until it can."
              : "No tools in the catalog."}
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

export function knownVariables(graph: FlowGraph | undefined, system: string[]): string[] {
  const out = new Set<string>(system);
  for (const node of graph?.nodes ?? []) {
    for (const v of node.data.extractVariables ?? []) if (v.key) out.add(v.key);
  }
  return [...out].sort();
}

export function booleanVariables(graph: FlowGraph | undefined): Set<string> {
  const out = new Set<string>(["identity_verified"]);
  for (const node of graph?.nodes ?? []) {
    for (const v of node.data.extractVariables ?? []) {
      if (v.type === "boolean" && v.key) out.add(v.key);
    }
  }
  return out;
}
