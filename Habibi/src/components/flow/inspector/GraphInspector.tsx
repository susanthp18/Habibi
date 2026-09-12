/** The graph-level inspector: the card's flow as a whole, its issues and its tool grant. */
import { MousePointerClick, Settings2 } from "lucide-react";

import { type FlowIssue, type FlowTool } from "@/api/flow";
import STUDIO_VOCABULARY from "@/lib/studio-vocabulary.json";
import { InspectorShell, IssueList, Section, ToolList, withSelectedStrays } from "./chrome";

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
  // What G16 warns about: the runtime strips these from the globals before
  // the first turn, so a CRM read ticked here is offered on no step at all.
  const stripped = globalTools.filter((t) =>
    STUDIO_VOCABULARY.globalToolsStrippedAtRuntime.includes(t),
  );

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
          tools={withSelectedStrays(tools, [...selected])}
          selected={(key) => selected.has(key)}
          disabled={readOnly}
          onToggle={toggle}
        />
        {stripped.length > 0 && (
          <p className="mt-075 text-body-small text-text-warning-bolder">
            {stripped.map((t) => (
              <code key={t} className="mr-050 font-mono">
                {t}
              </code>
            ))}
            {stripped.length === 1 ? "is" : "are"} stripped from the globals before the first turn —
            a CRM read belongs on the step that may use it. The compiler reports this as G16.
          </p>
        )}
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
