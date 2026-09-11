import type { Dispatch, SetStateAction } from "react";
import { toast } from "sonner";
import { Workflow } from "lucide-react";
import { Button } from "@/components/ui/button";
import { FlowCanvas } from "@/components/flow/FlowCanvas";
import {
  emptyGraph,
  fetchBuiltInFlow,
  isEmptyGraph,
  type FlowGraph,
  type FlowIssue,
} from "@/api/flow";

/** The Flow tab: unreadable-graph panel, empty-graph panel, or the canvas. */
export function FlowTabBody({
  flow,
  setFlow,
  flowUnreadable,
  loadingBuiltIn,
  setLoadingBuiltIn,
  setReplaceUnreadable,
  onFlowValidation,
  grantTools,
}: {
  flow: FlowGraph | null;
  setFlow: Dispatch<SetStateAction<FlowGraph | null>>;
  flowUnreadable: boolean;
  loadingBuiltIn: boolean;
  setLoadingBuiltIn: Dispatch<SetStateAction<boolean>>;
  setReplaceUnreadable: Dispatch<SetStateAction<boolean>>;
  onFlowValidation: (r: { ok: boolean; issues: FlowIssue[] }) => void;
  grantTools?: string[];
}) {
  return (
    <div className="h-full min-h-0">
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
              Voice calls only: WhatsApp answers from the prompt and walks the graph on text. This
              version runs the built-in collections script — Python that publish and rollback cannot
              touch. Load it here to turn it into a graph you own: it then publishes and rolls back
              with this prompt version. Nothing changes for live callers until you publish. Set{" "}
              <code className="font-mono text-text-subtlest">VOICE_FLOW_GRAPH=legacy</code> to force
              the built-in script even when a graph exists.
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
        <FlowCanvas
          graph={flow as FlowGraph}
          onChange={setFlow}
          onValidation={onFlowValidation}
          grantTools={grantTools}
        />
      )}
    </div>
  );
}
