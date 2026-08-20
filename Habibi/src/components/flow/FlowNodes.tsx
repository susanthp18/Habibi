import { Handle, Position, type NodeProps } from "@xyflow/react";
import { AlertTriangle, Ear, Flag, PhoneOff, Wrench } from "lucide-react";

import type { FlowNodeData } from "@/api/flow";
import { cn } from "@/lib/utils";
import { useCompact } from "./zoom";

/**
 * What the canvas passes into a node renderer. `issues` is injected by
 * FlowCanvas so a node can show its own validation state — an error that only
 * appears in a list somewhere else is an error nobody fixes.
 */
export type CanvasNodeData = FlowNodeData & {
  nodeKey: string;
  errorCount: number;
  warningCount: number;
};

function NodeShell({
  selected,
  errorCount,
  warningCount,
  children,
}: {
  selected: boolean;
  errorCount: number;
  warningCount: number;
  children: React.ReactNode;
}) {
  return (
    <div
      // border-danger / border-warning, not var(--danger) / var(--warning):
      // those two are used across the codebase but are not defined anywhere in
      // styles.css, so they resolve to nothing and the error state — the whole
      // point of this border — would silently not render.
      className={cn(
        "w-64 rounded-medium border-2 bg-surface shadow-sm transition-colors",
        selected ? "border-border-brand" : "border-border",
        errorCount > 0 && "border-border-danger",
        errorCount === 0 && warningCount > 0 && "border-border-warning",
      )}
    >
      {children}
    </div>
  );
}

export function ConversationNode({ data, selected }: NodeProps) {
  const d = data as unknown as CanvasNodeData;
  const compact = useCompact();
  const inbound = !d.isStart && (
    <Handle
      type="target"
      position={Position.Top}
      className="!h-2 !w-2 !rounded-full !border-2 !border-text-subtlest !bg-surface"
    />
  );
  const outbound = (
    <Handle
      type="source"
      position={Position.Bottom}
      className="!h-2 !w-2 !rounded-full !border-2 !border-text-subtlest !bg-surface"
    />
  );

  if (compact) {
    return (
      <NodeShell
        selected={!!selected}
        errorCount={d.errorCount}
        warningCount={d.warningCount}
      >
        {inbound}
        <div className="flex items-center gap-100 px-150 py-200">
          {d.isStart && <Flag className="h-5 w-5 shrink-0 text-text-brand" />}
          {/* Type scales with the zoom-out so it stays legible on screen. */}
          <span className="truncate font-mono text-[1.35rem] font-semibold text-text">
            {d.nodeKey}
          </span>
          {d.errorCount > 0 && (
            <AlertTriangle className="ml-auto h-5 w-5 shrink-0 text-text-danger" />
          )}
        </div>
        {outbound}
      </NodeShell>
    );
  }

  return (
    <NodeShell
      selected={!!selected}
      errorCount={d.errorCount}
      warningCount={d.warningCount}
    >
      {/* The start node is the entry point, so it has no inbound handle. */}
      {inbound}
      <div className="flex items-center justify-between gap-100 border-b border-border px-150 py-075">
        <div className="flex min-w-0 items-center gap-075">
          {d.isStart && <Flag className="h-3.5 w-3.5 shrink-0 text-text-brand" />}
          <span className="truncate text-body-small font-semibold text-text">{d.name}</span>
        </div>
        {d.errorCount > 0 && (
          <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-text-danger" />
        )}
      </div>

      <div className="px-150 py-100">
        <p className="line-clamp-3 text-body-small leading-relaxed text-text-subtle">
          {d.instructions?.trim() || (
            <span className="italic text-text-subtlest">No instructions yet</span>
          )}
        </p>
        <div className="mt-075 flex flex-wrap items-center gap-050">
          <span className="rounded-small bg-surface-sunken px-075 py-025 font-mono text-[0.65rem] text-text-subtlest">
            {d.nodeKey}
          </span>
          {d.instructionType === "say" && (
            <span className="rounded-small bg-surface-sunken px-075 py-025 text-[0.65rem] text-text-subtle">
              verbatim
            </span>
          )}
          {!d.respondImmediately && (
            <span
              title="Bot listens first instead of speaking"
              className="flex items-center gap-025 rounded-small bg-surface-sunken px-075 py-025 text-[0.65rem] text-text-subtle"
            >
              <Ear className="h-3 w-3" /> listens
            </span>
          )}
          {d.tools.length > 0 && (
            <span className="flex items-center gap-025 rounded-small bg-surface-sunken px-075 py-025 text-[0.65rem] text-text-subtle">
              <Wrench className="h-3 w-3" /> {d.tools.length}
            </span>
          )}
        </div>
      </div>

      <Handle
        type="source"
        position={Position.Bottom}
        className="!h-2 !w-2 !rounded-full !border-2 !border-text-subtlest !bg-surface"
      />
    </NodeShell>
  );
}

export function EndNode({ data, selected }: NodeProps) {
  const d = data as unknown as CanvasNodeData;
  // The end node zooms out with everything else.
  //
  // Only ConversationNode had a compact form, so at overview zoom eleven cards
  // swapped to large key-only type and this one kept 13px text and an 8px key
  // chip — which at that scale is a blank rectangle. On a twelve-node graph the
  // one box with no label on it was the node that ends the call.
  const compact = useCompact();
  const inbound = (
    <Handle
      type="target"
      position={Position.Top}
      className="!h-2 !w-2 !rounded-full !border-2 !border-text-subtlest !bg-surface"
    />
  );

  if (compact) {
    return (
      <NodeShell
        selected={!!selected}
        errorCount={d.errorCount}
        warningCount={d.warningCount}
      >
        {inbound}
        <div className="flex items-center gap-100 px-150 py-200">
          <PhoneOff className="h-5 w-5 shrink-0 text-text-danger" />
          <span className="truncate font-mono text-[1.35rem] font-semibold text-text">
            {d.nodeKey}
          </span>
        </div>
      </NodeShell>
    );
  }

  return (
    <NodeShell
      selected={!!selected}
      errorCount={d.errorCount}
      warningCount={d.warningCount}
    >
      {inbound}
      <div className="flex items-center gap-075 px-150 py-100">
        <PhoneOff className="h-3.5 w-3.5 shrink-0 text-text-danger" />
        <span className="truncate text-body-small font-semibold text-text">{d.name}</span>
        <span className="ml-auto rounded-small bg-surface-sunken px-075 py-025 font-mono text-[0.65rem] text-text-subtlest">
          {d.nodeKey}
        </span>
      </div>
    </NodeShell>
  );
}

export const flowNodeTypes = {
  conversation: ConversationNode,
  end: EndNode,
};
