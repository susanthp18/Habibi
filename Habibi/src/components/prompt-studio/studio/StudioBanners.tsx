import { useState } from "react";
import { useNavigate } from "@tanstack/react-router";

/** The card could not be re-read; the author is editing the copy loaded earlier. */
export function CardStaleBanner({ botId, error }: { botId: string; error: unknown }) {
  return (
    <div className="mx-250 mt-150 rounded-medium border border-border-warning-subtle bg-background-warning-subtler px-150 py-100 text-body-small text-text-warning-bolder">
      The card could not be re-read (
      {error instanceof Error ? error.message : "the API did not answer"}). You are editing the copy
      loaded earlier; saves still go to {botId}.
    </div>
  );
}

/**
 * The knowledge-base sent the author here to fix a coverage gap. Banner only:
 * nothing is auto-injected into the prompt. Dismiss clears the search params
 * so a reload does not bring it back.
 */
export function GapBanner({
  botId,
  unansweredId,
  note,
}: {
  botId: string;
  unansweredId?: string;
  note?: string;
}) {
  const navigate = useNavigate();
  const [dismissed, setDismissed] = useState(false);
  if (dismissed || !(note || unansweredId)) return null;
  return (
    <div className="mx-250 mt-150 flex items-start justify-between gap-150 rounded-medium border border-border-warning-subtle bg-background-warning-subtler px-150 py-100 text-body-small text-text-warning-bolder">
      <div>
        <div className="font-semibold text-text-warning-bolder">Fixing unanswered question</div>
        <div className="mt-025 text-text-warning-bolder/90">
          {note || "Review the system prompt for this coverage gap."}
          {unansweredId ? (
            <span className="ml-050 font-mono text-body-small text-text-warning-bolder/70">
              ({unansweredId})
            </span>
          ) : null}
        </div>
        <div className="mt-050 text-body-small text-text-warning-bolder/80">
          Banner only — edit the prompt yourself; nothing is auto-injected.
        </div>
      </div>
      <button
        type="button"
        onClick={() => {
          setDismissed(true);
          void navigate({ to: "/agent-studio/$botId", params: { botId }, search: {} });
        }}
        className="shrink-0 rounded border border-border-warning px-100 py-025 text-body-small hover:bg-background-warning-subtler"
      >
        Dismiss
      </button>
    </div>
  );
}
