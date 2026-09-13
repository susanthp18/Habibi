import { Suspense, lazy, useState, type Dispatch, type SetStateAction } from "react";
import { toast } from "sonner";
import { Workflow } from "lucide-react";
import { Button } from "@/components/ui/button";
import { LoadingState } from "@/components/ui/loading-state";
import {
  emptyGraph,
  fetchBuiltInFlow,
  isEmptyGraph,
  type FlowGraph,
  type FlowIssue,
} from "@/api/flow";

// The canvas is xyflow plus every node editor -- the studio's largest chunk,
// and most sessions never open the Flow tab. It loads when the tab does.
const FlowCanvas = lazy(() =>
  import("@/components/flow/FlowCanvas").then((m) => ({ default: m.FlowCanvas })),
);

/** The Flow tab: unreadable-graph panel, empty-graph panel, or the canvas. */
export function FlowTabBody({
  flow,
  setFlow,
  flowUnreadable,
  setReplaceUnreadable,
  onFlowValidation,
  grantTools,
  channels,
}: {
  flow: FlowGraph | null;
  setFlow: Dispatch<SetStateAction<FlowGraph | null>>;
  flowUnreadable: boolean;
  setReplaceUnreadable: (value: boolean) => void;
  onFlowValidation: (r: { ok: boolean; issues: FlowIssue[] }) => void;
  grantTools?: string[];
  /** The card's channels; a graph on a card no walker serves is kept but never walked. */
  channels?: string[];
}) {
  const walked = !channels || channels.some((c) => c === "voice" || c === "whatsapp");
  const [loadingBuiltIn, setLoadingBuiltIn] = useState(false);
  return (
    <div className="h-full min-h-0">
      {!walked ? (
        <div className="mb-100 rounded-medium border border-border-warning bg-background-warning-subtler px-150 py-100 text-body-small text-text-warning-bolder">
          This card serves neither voice nor WhatsApp, so nothing walks this graph. It is kept with
          the version; edits here change what a voice or WhatsApp binding would run.
        </div>
      ) : null}
      {flowUnreadable ? (
        // Not "no authored flow". The backend could not parse this
        // version's stored graph and served the empty sentinel in
        // its place so the rest of the bot stays reachable; saying
        // "no authored flow" here would present a corrupt row as a
        // deliberate choice, and the fix — load the built-in script
        // or restore an earlier version — is a different fix.
        <div className="flex h-full flex-col items-center justify-center gap-200 rounded-medium border border-dashed border-border-danger bg-background-danger-subtler/40 text-center">
          <div className="max-w-lg space-y-100 px-200">
            <h3 className="heading-small text-text-danger-bolder">
              This version&apos;s stored graph could not be read
            </h3>
            <p className="text-body-small leading-relaxed text-text-subtle">
              The saved JSON does not match the flow schema, so the editor is showing nothing rather
              than showing you something that is not what is stored.
              {/* It used to say "Nothing has been changed" and mean it
                  only until the next keystroke: the first autosave
                  wrote the empty sentinel over the column. The editor
                  now holds this version's flow at null so no save
                  touches it, and the server refuses the same write,
                  so replacing it takes one of these two buttons. */}{" "}
              Editing another tab will not touch it — saves leave this column alone until you
              replace it here, or restore an earlier version from History.
            </p>
          </div>
          <div className="flex flex-wrap justify-center gap-100">
            <Button
              variant="primary"
              disabled={loadingBuiltIn}
              onClick={() => {
                setLoadingBuiltIn(true);
                void fetchBuiltInFlow()
                  .then((g) => {
                    setReplaceUnreadable(true);
                    setFlow(g);
                    toast.success(
                      `Loaded the built-in script — ${g.nodes.length} nodes. Publish to make it live.`,
                    );
                  })
                  .catch((err: unknown) =>
                    toast.error(
                      err instanceof Error ? err.message : "Could not load the built-in flow",
                    ),
                  )
                  .finally(() => setLoadingBuiltIn(false));
              }}
            >
              <Workflow className="mr-050 h-4 w-4" />
              {loadingBuiltIn ? "Loading…" : "Replace with the built-in script"}
            </Button>
            <Button
              variant="outline"
              onClick={() => {
                setReplaceUnreadable(true);
                setFlow(emptyGraph());
              }}
            >
              Replace with a blank graph
            </Button>
          </div>
        </div>
      ) : isEmptyGraph(flow) ? (
        // An empty flow is meaningful, not missing: the runtime reads
        // it as "use the built-in collections script". Seeding a graph
        // on load would silently change what this version does, so it
        // takes an explicit action.
        <div className="flex h-full flex-col items-center justify-center gap-200 rounded-medium border border-dashed border-border bg-surface-sunken/40 text-center">
          <span className="flex size-10 items-center justify-center rounded-medium border border-border bg-surface text-text-subtle">
            <Workflow className="h-5 w-5" />
          </span>
          <div className="max-w-lg space-y-100 px-200">
            <h3 className="heading-small text-text">No authored flow</h3>
            <p className="text-body-small leading-relaxed text-text-subtle">
              Voice calls walk this graph; WhatsApp walks it with the text walker. Without one, this
              version runs the built-in collections script, which publish and rollback cannot touch.
              Load it here to turn it into a graph you own: it then publishes and rolls back with
              this prompt version. Nothing changes for live callers until you publish.
            </p>
          </div>
          <div className="flex flex-wrap justify-center gap-100">
            <Button
              variant="primary"
              disabled={loadingBuiltIn}
              onClick={() => {
                setLoadingBuiltIn(true);
                void fetchBuiltInFlow()
                  .then((g) => {
                    setFlow(g);
                    toast.success(
                      `Loaded the built-in script — ${g.nodes.length} nodes. Publish to make it live.`,
                    );
                  })
                  .catch((err: unknown) =>
                    toast.error(
                      err instanceof Error ? err.message : "Could not load the built-in flow",
                    ),
                  )
                  .finally(() => setLoadingBuiltIn(false));
              }}
            >
              <Workflow className="mr-050 h-4 w-4" />
              {loadingBuiltIn ? "Loading…" : "Load the built-in script"}
            </Button>
            <Button variant="outline" onClick={() => setFlow(emptyGraph())}>
              Start from blank
            </Button>
          </div>
        </div>
      ) : (
        <Suspense
          fallback={
            <div className="grid h-full place-items-center">
              <LoadingState label="Loading the canvas" />
            </div>
          }
        >
          <FlowCanvas
            graph={flow as FlowGraph}
            onChange={setFlow}
            onValidation={onFlowValidation}
            grantTools={grantTools}
          />
        </Suspense>
      )}
    </div>
  );
}
