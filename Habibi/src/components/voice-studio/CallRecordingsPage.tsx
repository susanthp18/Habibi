import { useEffect, useState } from "react";
import { Link } from "@tanstack/react-router";

import { client } from "@/agentstudio/client/client.gen";
import type { UsageHistoryResponse } from "@/agentstudio/client/types.gen";
import { MediaPreviewDialog } from "@/agentstudio/components/MediaPreviewDialog";
import { detailFromError } from "@/agentstudio/lib/apiError";
import { formatDateTime } from "@/agentstudio/lib/dateTime";
import { useOrganizationTimezone } from "@/agentstudio/hooks/useOrganizationTimezone";

const telephonyFilter = JSON.stringify([
  { attribute: "callChannel", type: "radio", value: { status: "telephony" } },
]);

export default function CallRecordingsPage() {
  const [page, setPage] = useState(1);
  const [refresh, setRefresh] = useState(0);
  const [data, setData] = useState<UsageHistoryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const preview = MediaPreviewDialog();
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
                    <tr key={run.id} className="border-t">
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
                          onClick={() =>
                            void preview.openPreview(
                              run.recording_url ?? null,
                              run.transcript_url ?? null,
                              run.id,
                            )
                          }
                        >
                          Play
                        </button>
                      </td>
                    </tr>
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
      {preview.dialog}
    </div>
  );
}
