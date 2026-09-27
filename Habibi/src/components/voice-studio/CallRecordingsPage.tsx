import { Fragment, useEffect, useState } from "react";
import { Link } from "@tanstack/react-router";

import { client } from "@/agentstudio/client/client.gen";
import type { UsageHistoryResponse } from "@/agentstudio/client/types.gen";
import { useRecording } from "@/api/recordings";
import { useRunInteraction } from "@/api/voice-studio";
import { detailFromError } from "@/agentstudio/lib/apiError";
import { formatDateTime } from "@/agentstudio/lib/dateTime";
import { useOrganizationTimezone } from "@/agentstudio/hooks/useOrganizationTimezone";

/**
 * A run's recording, played through PayInt: the redacted copy (every finding
 * beeped), or the original for a viewer with raw-PII permission -- the same
 * rule and audit as the Audit and Redaction pages. The engine does not sign
 * call audio for the browser.
 */
function RunRecording({ runId }: { runId: number }) {
  const link = useRunInteraction(runId);
  const interactionId = link.data?.interactionId ?? "";
  const recording = useRecording(interactionId, "auto");
  if (link.isPending) return <p className="text-sm text-muted-foreground">Finding the call…</p>;
  if (!interactionId)
    return (
      <p className="text-sm text-muted-foreground">
        This run was not filed as a customer call (a test or unconnected run), so it has no PayInt
        recording.
      </p>
    );
  return (
    <div className="flex flex-wrap items-center gap-3">
      {recording.kind === "ready" ? (
        // The call's transcript on the run page is the caption track.
        // eslint-disable-next-line jsx-a11y/media-has-caption
        <audio src={recording.src} controls className="min-w-[20rem] flex-1" />
      ) : (
        <span className="text-sm text-muted-foreground">
          {recording.kind === "loading"
            ? "Loading recording…"
            : recording.kind === "pending"
              ? "The redacted recording is still being made."
              : recording.kind === "none"
                ? "No recording."
                : "The recording could not be loaded."}
        </span>
      )}
      {recording.kind === "ready" && (
        <span className="text-xs text-muted-foreground">
          {recording.variant === "redacted" ? "Redacted: personal data beeped" : "Original"}
        </span>
      )}
      <Link to="/audit" search={{ id: interactionId }} className="text-sm underline">
        Open in Audit
      </Link>
    </div>
  );
}

const telephonyFilter = JSON.stringify([
  { attribute: "callChannel", type: "radio", value: { status: "telephony" } },
]);

export default function CallRecordingsPage() {
  const [page, setPage] = useState(1);
  const [refresh, setRefresh] = useState(0);
  const [data, setData] = useState<UsageHistoryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [playing, setPlaying] = useState<number | null>(null);
  const timezone = useOrganizationTimezone();

  useEffect(() => {
    let current = true;
    setLoading(true);
    setError(null);
    void client
      .get<{ response: UsageHistoryResponse }>({
        url: "/api/v1/organizations/usage/runs",
        query: { page, limit: 25, has_recording: true, filters: telephonyFilter },
      })
      .then((response) => {
        if (!current) return;
        if (response.error || !response.data)
          throw new Error(detailFromError(response.error) || "Could not load call recordings");
        setData(response.data);
      })
      .catch((cause: unknown) => {
        if (current)
          setError(cause instanceof Error ? cause.message : "Could not load call recordings");
      })
      .finally(() => {
        if (current) setLoading(false);
      });
    return () => {
      current = false;
    };
  }, [page, refresh]);

  return (
    <div className="container mx-auto max-w-6xl space-y-5 px-4 py-8">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Call recordings</h1>
          <p className="text-sm text-muted-foreground">
            Studio phone calls with available audio. Uploaded prompt audio is in the Audio Library.
          </p>
        </div>
        <button
          type="button"
          className="rounded-md border px-3 py-2 text-sm"
          disabled={loading}
          onClick={() => setRefresh((n) => n + 1)}
        >
          Refresh
        </button>
      </div>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      {loading && (
        <p role="status" className="text-sm text-muted-foreground">
          Refreshing call recordings…
        </p>
      )}
      {data && (
        <>
          {data.runs.length === 0 ? (
            <p className="rounded-md border p-6 text-sm">No Studio call recordings found.</p>
          ) : (
            <div className="overflow-x-auto rounded-md border">
              <table className="w-full text-left text-sm">
                <thead className="bg-muted/50">
                  <tr>
                    <th className="p-3">Time</th>
                    <th className="p-3">Agent</th>
                    <th className="p-3">Direction</th>
                    <th className="p-3">Duration</th>
                    <th className="p-3">Run</th>
                    <th className="p-3">Audio</th>
                  </tr>
                </thead>
                <tbody>
                  {data.runs.map((run) => (
                    <Fragment key={run.id}>
                      <tr className="border-t">
                        <td className="p-3">{formatDateTime(run.created_at, timezone)}</td>
                        <td className="p-3">{run.workflow_name || `Agent ${run.workflow_id}`}</td>
                        <td className="p-3">{run.call_type || "Unknown"}</td>
                        <td className="p-3">{Math.round(run.call_duration_seconds || 0)}s</td>
                        <td className="p-3">
                          <Link
                            to="/studio/workflow/$workflowId/run/$runId"
                            params={{ workflowId: String(run.workflow_id), runId: String(run.id) }}
                            className="underline"
                          >
                            #{run.id}
                          </Link>
                        </td>
                        <td className="p-3">
                          <button
                            className="underline disabled:opacity-50"
                            disabled={!run.recording_url}
                            onClick={() => setPlaying(playing === run.id ? null : run.id)}
                          >
                            {playing === run.id ? "Close" : "Play"}
                          </button>
                        </td>
                      </tr>
                      {playing === run.id && (
                        <tr className="border-t bg-muted/30">
                          <td colSpan={6} className="p-3">
                            <RunRecording runId={run.id} />
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="flex items-center gap-3 text-sm">
            <button
              className="rounded border px-3 py-1 disabled:opacity-50"
              disabled={page <= 1}
              onClick={() => setPage(page - 1)}
            >
              Previous
            </button>
            <span>
              Page {page} of {Math.max(1, data.total_pages)}
            </span>
            <button
              className="rounded border px-3 py-1 disabled:opacity-50"
              disabled={page >= data.total_pages}
              onClick={() => setPage(page + 1)}
            >
              Next
            </button>
          </div>
        </>
      )}
    </div>
  );
}
