/**
 * The canvas's chrome: zoom, the fit-to-graph camera, the validity pill, the
 * status bar and the reload dialog. Nothing here edits the graph.
 */
import { useEffect, useMemo, useRef } from "react";
import { useNodesInitialized, useReactFlow, useStore, useUpdateNodeInternals } from "@xyflow/react";
import { AlertTriangle, CheckCircle2, Loader2, ZoomIn, ZoomOut } from "lucide-react";
import type { FlowGraph } from "@/api/flow";
import { Button } from "@/components/ui/button";
import { Lozenge } from "@/components/ui/lozenge";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { cn } from "@/lib/utils";

export const MIN_ZOOM = 0.15;
export const MAX_ZOOM = 2;

/**
 * The zoom readout and its two buttons.
 *
 * Its own component so the subscription lives at the leaf. Read from
 * FlowCanvasInner, `s.transform[2]` re-renders the entire canvas on every wheel
 * tick — the node and edge renderers deliberately select booleans from the same
 * value for exactly this reason.
 */
export function ZoomControls() {
  const zoom = useStore((s) => s.transform[2]);
  const { zoomIn, zoomOut } = useReactFlow();
  return (
    <div className="flex shrink-0 items-center gap-025">
      <Button
        variant="ghost"
        size="icon-compact"
        onClick={() => void zoomOut({ duration: 120 })}
        disabled={zoom <= MIN_ZOOM + 0.001}
        title="Zoom out"
      >
        <ZoomOut className="h-3.5 w-3.5" />
      </Button>
      <span className="w-10 text-center tabular-nums text-text-subtle">
        {Math.round(zoom * 100)}%
      </span>
      <Button
        variant="ghost"
        size="icon-compact"
        onClick={() => void zoomIn({ duration: 120 })}
        disabled={zoom >= MAX_ZOOM - 0.001}
        title="Zoom in"
      >
        <ZoomIn className="h-3.5 w-3.5" />
      </Button>
    </div>
  );
}

/** Divider between toolbar groups, so the groups read as groups. */
export function Rule() {
  return <span aria-hidden className="h-4 w-px shrink-0 bg-border" />;
}

/** A sample of one edge treatment, for the legend in the status bar. */
export function EdgeSwatch({
  color,
  dash,
  width = 1.6,
  round = false,
}: {
  color: string;
  dash?: string;
  width?: number;
  round?: boolean;
}) {
  return (
    <svg width="20" height="6" aria-hidden className="shrink-0">
      <line
        x1="0"
        y1="3"
        x2="20"
        y2="3"
        stroke={color}
        strokeWidth={width}
        strokeDasharray={dash}
        strokeLinecap={round ? "round" : undefined}
      />
    </svg>
  );
}

export function FitToGraph({ signature }: { signature: string }) {
  // `signature` folds in anything that should re-frame and re-measure the
  // graph: the node set, and the shape of the pane. Entering full screen keeps
  // the component mounted, so without the pane in the key the camera stayed on
  // the crop it had at a third of the width — a zoomed-in corner of the graph,
  // with the rest off-screen.
  const { fitView } = useReactFlow();
  const initialized = useNodesInitialized();
  const updateNodeInternals = useUpdateNodeInternals();
  const nodeIds = useMemo(
    // The leading segment is the pane key, not a node id.
    () => signature.split("|").slice(1),
    [signature],
  );
  // Switching tabs unmounts this canvas, and on the way back the pane is
  // mounted before layout has given it a size. `initialized` flips true while
  // the pane is still 0x0, so fitView framed a degenerate box, parked the
  // camera off the graph, and marked the fit done — the canvas came back blank
  // and stayed blank. Waiting for real dimensions is what makes the return trip
  // survivable.
  const paneReady = useStore((s) => s.width > 0 && s.height > 0);
  // Every node has a real measured box.
  //
  // `useNodesInitialized()` is not enough on its own: it can report true while
  // the nodes still have no dimensions, and fitView against a collapsed
  // bounding box does not fail — it computes an enormous zoom, clamps to
  // maxZoom (2), and parks there. The canvas then opens showing two or three
  // giant cards with the rest of the graph off-screen, and because the fit
  // marked itself done it never corrects once the real sizes arrive. A graph
  // that looks permanently "zoomed in" is this, not a zoom anyone asked for.
  const measured = useStore((s) => {
    if (s.nodeLookup.size === 0) return false;
    for (const node of s.nodeLookup.values()) {
      if (!node.measured?.width || !node.measured?.height) return false;
    }
    return true;
  });
  const fitted = useRef<string | null>(null);
  const remeasured = useRef<string | null>(null);

  // Force a re-read of every node's DOM box once the pane has a size.
  //
  // xyflow measures nodes with a ResizeObserver, and an observer never
  // delivers a first entry for an element that was mounted without layout —
  // which is exactly what a hidden tab panel is, and what a background browser
  // tab is. The nodes then stay unmeasured: xyflow renders each one
  // `visibility: hidden` and refuses to draw a single edge, so the canvas comes
  // back from a tab switch as an empty grid. Nothing recovers on its own,
  // because nothing resizes afterwards and the observer stays silent for the
  // life of the component. Twelve nodes, twenty-one transitions, and not one
  // line on screen.
  useEffect(() => {
    if (!paneReady || nodeIds.length === 0) return;
    if (remeasured.current === signature) return;
    remeasured.current = signature;
    updateNodeInternals(nodeIds);
  }, [paneReady, signature, nodeIds, updateNodeInternals]);

  useEffect(() => {
    if (!initialized || !paneReady || !measured || !signature) return;
    if (fitted.current === signature) return;
    fitted.current = signature;
    void fitView({ padding: 0.15, duration: 200 });
  }, [initialized, paneReady, measured, signature, fitView]);

  return null;
}

/** The one piece of state that decides whether the graph can be published. */
export function ValidityPill({
  neverChecked,
  stale,
  errorCount,
  warningCount,
}: {
  neverChecked: boolean;
  stale: boolean;
  errorCount: number;
  warningCount: number;
}) {
  return (
    <>
      {neverChecked ? (
        // Says what it knows. "Valid" here would be a green tick for
        // a graph nobody has looked at.
        <Lozenge tone="neutral">
          <Loader2 className="animate-spin" />
          Checking…
        </Lozenge>
      ) : (
        <Lozenge
          // Dimmed while the answer describes the previous edit. The
          // counts are usually still right and flickering them to
          // "Checking…" on every keystroke would be unreadable, but
          // they must not look confirmed when they are not.
          className={cn(stale && "opacity-60")}
          title={stale ? "Re-checking — these counts describe the previous edit" : undefined}
          tone={errorCount > 0 ? "danger" : warningCount > 0 ? "warning" : "success"}
        >
          {errorCount > 0 ? (
            <>
              <AlertTriangle />
              {errorCount} error{errorCount === 1 ? "" : "s"}
            </>
          ) : warningCount > 0 ? (
            <>
              <AlertTriangle />
              {warningCount} warning{warningCount === 1 ? "" : "s"}
            </>
          ) : (
            <>
              <CheckCircle2 />
              Valid
            </>
          )}
        </Lozenge>
      )}
    </>
  );
}

/**
 * Document stats, zoom, and the key to the three edge treatments -- the
 * things you consult rather than operate, along the bottom edge where a
 * document's status belongs.
 */
export function CanvasStatusBar({
  graph,
  implicitCount,
  showLegend,
  onEditGlobals,
}: {
  graph: FlowGraph;
  implicitCount: number;
  /** Dropped rather than wrapped when the pane is too narrow for one line. */
  showLegend: boolean;
  onEditGlobals: () => void;
}) {
  const stats = [
    `${graph.nodes.length} step${graph.nodes.length === 1 ? "" : "s"}`,
    `${graph.edges.length} transition${graph.edges.length === 1 ? "" : "s"}`,
  ].join(" · ");
  return (
    <div className="flex shrink-0 items-center gap-100 overflow-hidden border-t border-border px-100 py-050 text-body-micro text-text-subtlest">
      <ZoomControls />

      <Rule />

      <span className="truncate tabular-nums">{stats}</span>

      {implicitCount > 0 && (
        <span
          className="shrink-0 tabular-nums"
          title="Performed by the built-in tools, not authored here. Not saved with the graph."
        >
          · {implicitCount} implicit
        </span>
      )}
      {(graph.globalTools?.length ?? 0) > 0 && (
        <button
          type="button"
          onClick={onEditGlobals}
          className="focus-ring shrink-0 rounded-small tabular-nums underline-offset-2 hover:text-text hover:underline"
          title={`Available from every step: ${(graph.globalTools ?? []).join(", ")}. Click to edit.`}
        >
          · {graph.globalTools.length} global
        </button>
      )}

      {/* Three edge treatments carry three different meanings and none
                  of them is guessable. Dropped rather than wrapped when the pane
                  is too narrow to hold it on one line. */}
      {showLegend && (
        <div className="ml-auto flex shrink-0 items-center gap-150">
          <span className="flex items-center gap-050">
            <EdgeSwatch color="var(--border-bold)" />
            the model decides
          </span>
          <span className="flex items-center gap-050">
            <EdgeSwatch color="var(--border-bold)" dash="7 4" />a captured value
          </span>
          <span className="flex items-center gap-050">
            <EdgeSwatch color="var(--text-subtlest)" dash="1 4" width={1.2} round />a tool moves the
            call
          </span>
        </div>
      )}
    </div>
  );
}

/**
 * Replaces a window.confirm. Reload discards every node, transition and edit
 * on the canvas, so it is worth asking -- in the product's own surface:
 * themed, escapable, and it names what is lost rather than restating the click.
 */
export function ReloadBuiltInDialog({
  open,
  onOpenChange,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void;
}) {
  return (
    <AlertDialog
      open={open}
      onOpenChange={(next) => {
        if (!next) onOpenChange(false);
      }}
    >
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Replace this graph with the built-in script?</AlertDialogTitle>
          <AlertDialogDescription>
            Every node, transition and edit on this canvas is discarded. Nothing changes for live
            callers until you publish.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Keep this graph</AlertDialogCancel>
          <AlertDialogAction
            onClick={() => {
              onOpenChange(false);
              onConfirm();
            }}
          >
            Replace it
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
