import { Copy, RefreshCw, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { signalFloorApproval } from "@/api/floor";
import { useCopilotStream } from "@/api/handoff";
import { Lozenge } from "@/components/ui/lozenge";
import { copyText, handoffErrorWords } from "./handoff-words";

type Props = {
  interactionId: string;
  /** perm-supervisor-write: approving or rejecting what waits on a person. */
  canSignal: boolean;
};

const ENGINE_WORDS: Record<string, string> = {
  authority: "authority decision",
  treatment: "treatment plan",
};

/** The engines' draft for this case: what to say on the call back, and any
 * approval waiting on a supervisor. Advice to copy, never something said. */
export function HandoffCopilot({ interactionId, canSignal }: Props) {
  const stream = useCopilotStream(interactionId);
  const signal = async (id: string, name: "approve" | "reject") => {
    try {
      await signalFloorApproval(id, name);
      toast.success(name === "approve" ? "Approved — the workflow resumes" : "Rejected");
      stream.refresh();
    } catch (e) {
      toast.error(handoffErrorWords(e));
    }
  };

  return (
    <div className="rounded-large border border-border bg-surface">
      <div className="flex items-center justify-between border-b border-border px-150 py-100">
        <h2 className="flex items-center gap-075 text-body-small font-semibold text-text">
          <Sparkles className="h-3.5 w-3.5 text-text-brand" />
          Copilot
        </h2>
        <div className="flex items-center gap-075">
          {stream.streaming ? (
            <Lozenge tone="selected">drafting</Lozenge>
          ) : stream.error ? (
            <Lozenge tone="danger">unavailable</Lozenge>
          ) : stream.unavailable.length ? (
            <Lozenge tone="warning">partial</Lozenge>
          ) : stream.done ? (
            <Lozenge tone="success">ready</Lozenge>
          ) : null}
          <button
            type="button"
            onClick={stream.refresh}
            disabled={stream.streaming}
            aria-label="Refresh the copilot"
            title="Refresh"
            className="grid h-300 w-300 place-items-center rounded-medium text-text-subtle hover:bg-surface-sunken disabled:opacity-50"
          >
            <RefreshCw className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      <div className="space-y-100 px-150 py-150">
        {stream.card?.displayName || stream.card?.botId ? (
          <div className="flex flex-wrap gap-050">
            <Lozenge tone="neutral">{stream.card.displayName || stream.card.botId}</Lozenge>
          </div>
        ) : null}

        {stream.unavailable.length ? (
          <p role="status" className="text-body-small text-text-warning">
            Couldn't load the{" "}
            {stream.unavailable.map((name) => ENGINE_WORDS[name] ?? name).join(" or the ")}. Check
            it before offering anything.
          </p>
        ) : null}

        {stream.whisper ? (
          <p className="whitespace-pre-wrap text-body-small leading-snug text-text">
            {stream.whisper}
          </p>
        ) : stream.error ? (
          <p className="text-body-small text-text-danger">Couldn't load the copilot.</p>
        ) : stream.streaming ? (
          <p className="text-body-small text-text-subtlest">Drafting…</p>
        ) : (
          <p className="text-body-small text-text-subtlest">No draft for this case.</p>
        )}

        {stream.vetoes.length > 0 ? (
          <p className="text-body-small text-text-danger">Veto: {stream.vetoes.join(" · ")}</p>
        ) : null}

        {stream.whisper && !stream.streaming ? (
          <button
            type="button"
            onClick={() => void copyText(stream.whisper)}
            className="flex items-center gap-050 rounded-medium border border-border px-100 py-050 text-body-small font-semibold text-text hover:bg-surface-sunken"
          >
            <Copy className="h-3 w-3" />
            Copy
          </button>
        ) : null}
      </div>

      {stream.approvals.length > 0 ? (
        <div className="border-t border-border bg-background-warning-subtler px-150 py-100">
          <h3 className="mb-075 text-body-small font-semibold text-text">
            {canSignal ? "Waiting for your approval" : "Waiting for a supervisor's approval"}
          </h3>
          <ul className="space-y-050">
            {stream.approvals.map((job) => (
              <li
                key={job.id}
                className="flex items-center justify-between gap-100 text-body-small"
              >
                <span className="min-w-0 truncate text-text">
                  {job.workflowType.replace(/_/g, " ")}
                  {job.inputRequiredReason
                    ? ` · ${job.inputRequiredReason.replace(/_/g, " ")}`
                    : ""}
                </span>
                {canSignal ? (
                  <span className="flex shrink-0 gap-050">
                    <button
                      type="button"
                      className="rounded px-075 py-025 font-medium text-text-brand"
                      onClick={() => void signal(job.id, "approve")}
                    >
                      Approve
                    </button>
                    <button
                      type="button"
                      className="rounded px-075 py-025 text-text-subtle"
                      onClick={() => void signal(job.id, "reject")}
                    >
                      Reject
                    </button>
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
