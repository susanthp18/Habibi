import { Send, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { useQueryClient } from "@tanstack/react-query";
import { signalFloorApproval, useCopilotStream } from "@/api/floor";
import type { Suggestion } from "@/data/handoff-seed";
import { Lozenge } from "@/components/ui/lozenge";
import { USE_MOCK } from "@/api/config";

type Props = {
  interactionId: string;
  onInsert: (s: Suggestion) => void;
  monitor?: boolean;
};

export function HandoffCopilot({ interactionId, onInsert, monitor }: Props) {
  const stream = useCopilotStream(interactionId);
  const qc = useQueryClient();
  const whisper = stream.whisper || stream.engineDraft;
  const signal = async (id: string, name: "approve" | "reject") => {
    try {
      await signalFloorApproval(id, name);
      toast.success(name === "approve" ? "Approved — clerk will resume" : "Rejected");
      void qc.invalidateQueries({ queryKey: ["floor-approvals"] });
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Signal failed");
    }
  };

  return (
    <div className="rounded-large border border-border bg-surface">
      <div className="flex items-center justify-between border-b border-border px-150 py-100">
        <div className="flex items-center gap-075 text-body-small font-semibold text-text">
          <Sparkles className="h-3.5 w-3.5 text-text-brand" />
          Copilot
        </div>
        {stream.streaming ? (
          <Lozenge tone="selected">streaming</Lozenge>
        ) : stream.done ? (
          <Lozenge tone="success">grounded</Lozenge>
        ) : (
          <Lozenge tone="neutral">idle</Lozenge>
        )}
      </div>

      <div className="space-y-100 px-150 py-150">
        {stream.card?.displayName || stream.card?.botId ? (
          <div className="flex flex-wrap gap-050">
            <Lozenge tone="neutral">{stream.card.displayName || stream.card.botId}</Lozenge>
            {(stream.card.skills ?? []).map((skill) => (
              <Lozenge key={skill} tone="information">
                {skill}
              </Lozenge>
            ))}
          </div>
        ) : null}

        {whisper ? (
          <p className="text-body-small leading-snug text-text">
            {whisper}
            {stream.streaming ? (
              <span className="ml-025 inline-block h-3 w-075 animate-pulse bg-background-brand-bold align-middle" />
            ) : null}
          </p>
        ) : (
          <p className="text-body-small text-text-subtlest">Waiting for engine pack…</p>
        )}

        {stream.vetoes.length > 0 ? (
          <p className="text-body-small text-text-danger">Veto: {stream.vetoes.join(" · ")}</p>
        ) : null}

        {stream.error ? (
          <p className="text-body-small text-text-danger">{stream.error}</p>
        ) : null}

        {whisper && !monitor ? (
          <button
            type="button"
            disabled={!whisper}
            onClick={() =>
              onInsert({
                id: `copilot-${interactionId}`,
                title: "Copilot whisper",
                body: whisper,
                source: "Copilot",
                showAfter: 0,
              })
            }
            className="flex items-center gap-050 rounded-medium bg-background-brand-bold px-100 py-050 text-body-small font-semibold text-white hover:bg-background-brand-bold-hovered disabled:opacity-50"
          >
            <Send className="h-3 w-3" />
            Speak this
          </button>
        ) : null}
      </div>

      {!USE_MOCK && stream.approvals.length > 0 ? (
        <div className="border-t border-border bg-background-warning-subtlest px-150 py-100">
          <p className="mb-075 text-body-small font-semibold text-text">Pending approval</p>
          <ul className="space-y-050">
            {stream.approvals.map((job) => (
              <li key={job.id} className="flex items-center justify-between gap-100 text-body-small">
                <span className="min-w-0 truncate text-text">
                  {job.workflowType.replace(/_/g, " ")}
                  {job.inputRequiredReason ? ` · ${job.inputRequiredReason.replace(/_/g, " ")}` : ""}
                </span>
                {monitor ? null : (
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
                )}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
