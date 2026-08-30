import { Handle, Position, type NodeProps } from "@xyflow/react";
import {
  AlertTriangle,
  Anchor,
  Braces,
  CornerDownRight,
  Ear,
  Flag,
  PhoneOff,
  Wrench,
} from "lucide-react";

import type { FlowNodeData } from "@/api/flow";
import { cn } from "@/lib/utils";
import { useCompact, useDetail } from "./zoom";

/** One of the node's tools, resolved against the `/flow/tools` catalog. */
export type NodeTool = {
  key: string;
  /** Moves the conversation on its own — the source of the dashed ghost edges. */
  moves: boolean;
  /** Owned by the policy engine; its wording is not the model's to choose. */
  locked: boolean;
  /** Absent from the catalog, which the validator reports as an error. */
  unknown: boolean;
};

/**
 * What the canvas passes into a node renderer.
 *
 * Everything past `nodeKey` is injected by FlowCanvas rather than stored on the
 * node, because it is only knowable with the rest of the graph in hand: the
 * tool catalog, the reserved-key map, and the node's degree once the implicit
 * tool hops are counted alongside the authored edges. A card that cannot see
 * those cannot tell you the two things you most want to know at a glance —
 * whether anything reaches this step, and whether anything leaves it.
 */
export type CanvasNodeData = FlowNodeData & {
  nodeKey: string;
  errorCount: number;
  warningCount: number;
  /** In authored order, so the card lists tools the way the inspector does. */
  toolDetail: NodeTool[];
  /** Why a built-in tool routes here, when this key is a reserved one. */
  reservedHint: string | null;
  outCount: number;
  inCount: number;
  implicitOut: number;
  implicitIn: number;
  /** Offered here too, on top of this node's own list. */
  globalToolCount: number;
};

/**
 * Problems the canvas can decide on its own that the server validator does not
 * report.
 *
 * Both are silent at runtime rather than loud at publish, which is exactly the
 * kind that has to be visible while you draw. The first is documented: the
 * export in `voice/flow_export.py` carries `entryLine` across specifically
 * because dropping it once left a live call sitting mute for 24 seconds on
 * `negotiate_ptp`. The second is the shape that strands a caller on a step with
 * nothing to move them off it and no instruction to hang up.
 *
 * Kept advisory and local. Promoting either to a publish-blocking rule is a
 * change to `validate_graph`, not to a renderer.
 */
function localHints(d: CanvasNodeData, type: "conversation" | "end"): string[] {
  if (type !== "conversation") return [];
  const out: string[] = [];
  if (!d.respondImmediately && !(d.entryLine ?? "").trim()) {
    out.push("Listens first with no entry line — silent until the caller speaks.");
  }
  if (!d.endConversation && d.outCount + d.implicitOut === 0) {
    out.push("Nothing leaves this step and it does not end the call.");
  }
  return out;
}

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
        "w-72 rounded-medium border-2 bg-surface shadow-sm transition-shadow",
        selected ? "border-border-brand shadow-overlay" : "border-border",
        errorCount > 0 && "border-border-danger",
        errorCount === 0 && warningCount > 0 && "border-border-warning",
      )}
    >
      {children}
    </div>
  );
}

/**
 * Handles are the only way to draw a transition, and the inspector has to tell
 * people they exist ("Drag from the bottom of a step…") — which is the tell
 * that an 8px dot nobody can see is too small. Sized to be hit, and the source
 * carries the brand colour so the two ends are not interchangeable at a look.
 */
function NodeHandle({ type }: { type: "source" | "target" }) {
  return (
    <Handle
      type={type}
      position={type === "source" ? Position.Bottom : Position.Top}
      className={cn(
        "!size-3 !rounded-full !border-2 !bg-surface transition-transform hover:!scale-125",
        type === "source" ? "!border-border-brand" : "!border-text-subtlest",
      )}
    />
  );
}

function IssueBadge({ errorCount, warningCount }: { errorCount: number; warningCount: number }) {
  if (errorCount === 0 && warningCount === 0) return null;
  const danger = errorCount > 0;
  const count = danger ? errorCount : warningCount;
  return (
    <span
      title={
        danger
          ? `${errorCount} error${errorCount === 1 ? "" : "s"} — blocks publish`
          : `${warningCount} warning${warningCount === 1 ? "" : "s"} — advisory`
      }
      className={cn(
        "flex shrink-0 items-center gap-025 rounded-small px-050 text-body-micro font-semibold tabular-nums",
        danger
          ? "bg-background-danger text-text-danger"
          : "bg-background-warning text-text-warning-bolder",
      )}
    >
      <AlertTriangle className="h-3 w-3" />
      {count}
    </span>
  );
}

const chipCls =
  "flex shrink-0 items-center gap-025 rounded-small bg-surface-sunken px-075 py-025 text-body-micro text-text-subtle";

function Chip({
  icon: Icon,
  label,
  title,
  tone = "neutral",
}: {
  icon?: typeof Wrench;
  label: string;
  title?: string;
  tone?: "neutral" | "danger" | "brand";
}) {
  return (
    <span
      title={title}
      className={cn(
        chipCls,
        tone === "danger" && "bg-background-danger text-text-danger",
        tone === "brand" && "bg-background-brand-subtlest text-text-brand",
      )}
    >
      {Icon && <Icon className="h-3 w-3 shrink-0" />}
      {label}
    </span>
  );
}

/**
 * The spoken-word treatment: an entry line and a verbatim script are both exact
 * wording, and neither should look like an instruction to the model.
 */
function SpokenLine({ label, text }: { label: string; text: string }) {
  return (
    <p
      title={text}
      className="border-l-2 border-border-bold pl-075 text-body-tiny italic leading-snug text-text-subtle"
    >
      <span className="mr-050 not-italic text-body-micro uppercase tracking-wide text-text-subtlest">
        {label}
      </span>
      <span className="line-clamp-2">{text}</span>
    </p>
  );
}

function HintStrip({ hints }: { hints: string[] }) {
  if (hints.length === 0) return null;
  return (
    <div className="space-y-025">
      {hints.map((hint) => (
        <p
          key={hint}
          className="flex items-start gap-050 rounded-small bg-background-warning px-075 py-050 text-body-micro leading-snug text-text-warning-bolder"
        >
          <AlertTriangle className="mt-025 h-3 w-3 shrink-0" />
          {hint}
        </p>
      ))}
    </div>
  );
}

/**
 * The meta row: the exceptional facts first, the counts last.
 *
 * Every chip here answers "how does this step differ from the default", which
 * is why an ordinary node shows only its key. Counts collapse into names once
 * there is room for them — that a node has three tools is much less useful to
 * know than that one of its tools hangs up the call.
 */
function MetaRow({ d, detail }: { d: CanvasNodeData; detail: boolean }) {
  const variables = d.extractVariables ?? [];
  const outbound = d.outCount + d.implicitOut;
  return (
    <div className="flex flex-wrap items-center gap-050">
      <span className="rounded-small bg-surface-sunken px-075 py-025 font-mono text-body-micro text-text-subtlest">
        {d.nodeKey}
      </span>

      {d.reservedHint && (
        <Chip
          icon={Anchor}
          label="reserved"
          tone="brand"
          title={`Reserved key — ${d.reservedHint}. A built-in tool moves the call here without an authored edge.`}
        />
      )}
      {d.instructionType === "say" && (
        <Chip label="verbatim" title="Spoken word for word — the model does not rephrase it" />
      )}
      {!d.respondImmediately && (
        <Chip icon={Ear} label="listens" title="Waits for the caller instead of speaking first" />
      )}
      {d.endConversation && (
        <Chip
          icon={PhoneOff}
          label="hangs up"
          tone="danger"
          title="The call ends after this step"
        />
      )}

      <span className="ml-auto flex shrink-0 items-center gap-050">
        {d.globalToolCount > 0 && !detail && (
          <span
            className="text-body-micro text-text-subtlest"
            title={`${d.globalToolCount} global tools are offered here as well`}
          >
            +{d.globalToolCount}
          </span>
        )}
        {d.toolDetail.length > 0 && !detail && (
          <Chip
            icon={Wrench}
            label={String(d.toolDetail.length)}
            title={d.toolDetail.map((t) => t.key).join(", ")}
          />
        )}
        {variables.length > 0 && !detail && (
          <Chip
            icon={Braces}
            label={String(variables.length)}
            title={variables.map((v) => `${v.key || "?"}: ${v.type}`).join(", ")}
          />
        )}
        <Chip
          icon={CornerDownRight}
          label={String(outbound)}
          tone={outbound === 0 && !d.endConversation ? "danger" : "neutral"}
          title={
            `${d.outCount} authored transition${d.outCount === 1 ? "" : "s"} out` +
            (d.implicitOut > 0 ? `, ${d.implicitOut} performed by a tool` : "") +
            ` · ${d.inCount + d.implicitIn} in`
          }
        />
      </span>
    </div>
  );
}

/** Tools and captured values by name — only worth the height when zoomed in. */
function DetailRows({ d }: { d: CanvasNodeData }) {
  const variables = d.extractVariables ?? [];
  const hasTools = d.toolDetail.length > 0 || d.globalToolCount > 0;
  if (!hasTools && variables.length === 0) return null;
  return (
    <div className="space-y-075 border-t border-border px-150 py-075">
      {hasTools && (
        <div className="space-y-025">
          <div className="text-body-micro uppercase tracking-wide text-text-subtlest">Tools</div>
          <div className="flex flex-wrap gap-050">
            {d.toolDetail.map((tool) => (
              <span
                key={tool.key}
                title={
                  tool.unknown
                    ? `${tool.key} is not in the tool catalog — publish will reject it`
                    : tool.moves
                      ? `${tool.key} moves the call on its own`
                      : tool.key
                }
                className={cn(
                  "flex items-center gap-025 rounded-small px-075 py-025 font-mono text-body-micro",
                  tool.unknown
                    ? "bg-background-danger text-text-danger line-through"
                    : "bg-surface-sunken text-text-subtle",
                )}
              >
                {tool.key}
                {tool.moves && !tool.unknown && (
                  <CornerDownRight className="h-2.5 w-2.5 text-text-brand" />
                )}
                {tool.locked && !tool.unknown && (
                  <span className="text-body-micro text-text-subtlest">policy</span>
                )}
              </span>
            ))}
            {d.globalToolCount > 0 && (
              <span
                title="Offered at every step, set on the graph rather than here"
                className="rounded-small border border-dashed border-border px-075 py-025 text-body-micro text-text-subtlest"
              >
                +{d.globalToolCount} global
              </span>
            )}
          </div>
        </div>
      )}
      {variables.length > 0 && (
        <div className="space-y-025">
          <div className="text-body-micro uppercase tracking-wide text-text-subtlest">Captures</div>
          <div className="flex flex-wrap gap-050">
            {variables.map((v, i) => (
              <span
                key={`${v.key}-${i}`}
                title={v.description || "No description — the model reads this field"}
                className={cn(
                  "rounded-small px-075 py-025 font-mono text-body-micro",
                  v.key.trim()
                    ? "bg-surface-sunken text-text-subtle"
                    : "bg-background-danger text-text-danger",
                )}
              >
                {v.key.trim() || "(unnamed)"}
                <span className="text-text-subtlest">:{v.type}</span>
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export function ConversationNode({ data, selected }: NodeProps) {
  const d = data as unknown as CanvasNodeData;
  const compact = useCompact();
  const detail = useDetail();
  const hints = localHints(d, "conversation");

  if (compact) {
    return (
      <NodeShell selected={!!selected} errorCount={d.errorCount} warningCount={d.warningCount}>
        {!d.isStart && <NodeHandle type="target" />}
        <div className="flex items-center gap-100 px-150 py-200">
          {d.isStart && <Flag className="h-5 w-5 shrink-0 text-text-brand" />}
          {/* Type scales with the zoom-out so it stays legible on screen. */}
          <span className="truncate font-mono heading-medium font-semibold text-text">
            {d.nodeKey}
          </span>
          {(d.errorCount > 0 || d.warningCount > 0 || hints.length > 0) && (
            <AlertTriangle
              className={cn(
                "ml-auto h-5 w-5 shrink-0",
                d.errorCount > 0 ? "text-text-danger" : "text-text-warning",
              )}
            />
          )}
        </div>
        <NodeHandle type="source" />
      </NodeShell>
    );
  }

  return (
    <NodeShell selected={!!selected} errorCount={d.errorCount} warningCount={d.warningCount}>
      {/* The start node is the entry point, so it has no inbound handle. */}
      {!d.isStart && <NodeHandle type="target" />}

      <div className="flex items-center justify-between gap-100 border-b border-border px-150 py-075">
        <div className="flex min-w-0 items-center gap-075">
          {d.isStart && (
            <Flag className="h-3.5 w-3.5 shrink-0 text-text-brand" aria-label="Start" />
          )}
          <span className="truncate text-body-small font-semibold text-text" title={d.name}>
            {d.name || <span className="italic text-text-subtlest">Untitled step</span>}
          </span>
        </div>
        <IssueBadge errorCount={d.errorCount} warningCount={d.warningCount} />
      </div>

      <div className="space-y-075 px-150 py-100">
        {(d.entryLine ?? "").trim() && <SpokenLine label="on entry" text={d.entryLine} />}
        {d.instructionType === "say" ? (
          <SpokenLine label="says" text={d.instructions?.trim() || "(nothing to say)"} />
        ) : (
          <p className="line-clamp-3 text-body-small leading-relaxed text-text-subtle">
            {d.instructions?.trim() || (
              <span className="italic text-text-subtlest">No instructions yet</span>
            )}
          </p>
        )}
        <HintStrip hints={hints} />
        <MetaRow d={d} detail={detail} />
      </div>

      {detail && <DetailRows d={d} />}

      <NodeHandle type="source" />
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
  const stranded = d.inCount + d.implicitIn === 0;

  if (compact) {
    return (
      <NodeShell selected={!!selected} errorCount={d.errorCount} warningCount={d.warningCount}>
        <NodeHandle type="target" />
        <div className="flex items-center gap-100 px-150 py-200">
          <PhoneOff className="h-5 w-5 shrink-0 text-text-danger" />
          <span className="truncate font-mono heading-medium font-semibold text-text">
            {d.nodeKey}
          </span>
          {(d.errorCount > 0 || d.warningCount > 0) && (
            <AlertTriangle
              className={cn(
                "ml-auto h-5 w-5 shrink-0",
                d.errorCount > 0 ? "text-text-danger" : "text-text-warning",
              )}
            />
          )}
        </div>
      </NodeShell>
    );
  }

  return (
    <NodeShell selected={!!selected} errorCount={d.errorCount} warningCount={d.warningCount}>
      <NodeHandle type="target" />
      <div className="flex items-center gap-075 border-b border-border px-150 py-075">
        <PhoneOff className="h-3.5 w-3.5 shrink-0 text-text-danger" />
        <span className="truncate text-body-small font-semibold text-text" title={d.name}>
          {d.name || "End call"}
        </span>
        {/* An error on the terminal node used to show as a red border and
            nothing else — the one node with no error affordance at all. */}
        <span className="ml-auto flex items-center gap-050">
          <IssueBadge errorCount={d.errorCount} warningCount={d.warningCount} />
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-050 px-150 py-075">
        <span className="rounded-small bg-surface-sunken px-075 py-025 font-mono text-body-micro text-text-subtlest">
          {d.nodeKey}
        </span>
        {d.reservedHint && (
          <Chip
            icon={Anchor}
            label="reserved"
            tone="brand"
            title={`Reserved key — ${d.reservedHint}.`}
          />
        )}
        <Chip
          icon={CornerDownRight}
          label={String(d.inCount + d.implicitIn)}
          tone={stranded ? "danger" : "neutral"}
          title={
            stranded
              ? "Nothing transitions into this node — the call can never reach it"
              : `${d.inCount} authored transition${d.inCount === 1 ? "" : "s"} in` +
                (d.implicitIn > 0 ? `, ${d.implicitIn} performed by a tool` : "")
          }
        />
      </div>
    </NodeShell>
  );
}

export const flowNodeTypes = {
  conversation: ConversationNode,
  end: EndNode,
};
