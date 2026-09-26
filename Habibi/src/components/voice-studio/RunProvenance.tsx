import { useEffect, useMemo, useState } from "react";

import {
  getWorkflowVersionsApiV1WorkflowWorkflowIdVersionsGet,
  listToolsApiV1ToolsGet,
} from "@/agentstudio/client/sdk.gen";
import type { WorkflowVersionResponse } from "@/agentstudio/client/types.gen";
import type { WorkflowRunLogs } from "@/agentstudio/components/workflow/conversation/types";

type Props = {
  workflowId: number;
  definitionId: number | null;
  direction: string | null;
  logs: WorkflowRunLogs | null;
};
type NamedTool = { name: string; tool_uuid: string };

function legacyOutcome(result: unknown): boolean | null {
  if (typeof result !== "string") return null;
  if (/["']ok["']:\s*False/.test(result) || /["']status["']:\s*["']error["']/.test(result))
    return false;
  if (/["']ok["']:\s*True/.test(result)) return true;
  return null;
}

export default function RunProvenance({ workflowId, definitionId, direction, logs }: Props) {
  const [version, setVersion] = useState<WorkflowVersionResponse | null>(null);
  const [tools, setTools] = useState<NamedTool[]>([]);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let current = true;
    void Promise.all([
      getWorkflowVersionsApiV1WorkflowWorkflowIdVersionsGet({ path: { workflow_id: workflowId } }),
      listToolsApiV1ToolsGet(),
    ])
      .then(([versions, toolList]) => {
        if (!current) return;
        if (versions.error || !versions.data)
          throw new Error("Could not load the pinned definition");
        setVersion(versions.data.find((v) => v.id === definitionId) ?? null);
        if (toolList.data) setTools(toolList.data);
      })
      .catch((cause: unknown) => {
        if (current)
          setError(cause instanceof Error ? cause.message : "Could not load tool provenance");
      });
    return () => {
      current = false;
    };
  }, [workflowId, definitionId]);
  const attached = useMemo(() => {
    const nodes = version?.workflow_json?.nodes;
    const uuids = new Set<string>();
    if (Array.isArray(nodes))
      for (const node of nodes) {
        if (!node || typeof node !== "object") continue;
        const data = (node as { data?: { tool_uuids?: string[] } }).data;
        for (const uuid of data?.tool_uuids ?? []) uuids.add(uuid);
      }
    return tools.filter((tool) => uuids.has(tool.tool_uuid));
  }, [version, tools]);
  const events = logs?.realtime_feedback_events ?? [];
  const calls = events.filter((event) => event.type === "rtf-function-call-end");
  const starts = new Map(
    events
      .filter((event) => event.type === "rtf-function-call-start" && event.payload.tool_call_id)
      .map((event) => [event.payload.tool_call_id, event]),
  );
  return (
    <section className="rounded-xl border p-5 space-y-3">
      <h2 className="font-semibold">Routing and tool provenance</h2>
      <p className="text-sm">
        Direction: <strong>{direction || "Unknown"}</strong> · Pinned definition:{" "}
        <strong>{definitionId ?? "Unknown"}</strong>
        {version ? ` · Version ${version.version_number}` : ""}
      </p>
      <p className="text-xs text-muted-foreground">
        Tool names and UUIDs come from the pinned workflow definition. Result status is shown only
        when structured metadata was recorded.
      </p>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      {calls.length === 0 ? (
        <p className="text-sm text-muted-foreground">No tool calls recorded.</p>
      ) : (
        <ul className="space-y-2">
          {calls.map((event, index) => {
            const name = event.payload.function_name || "Unknown tool";
            const outcome = event.payload.result_summary;
            // Newer runs record the tool UUID and duration on the event; older
            // ones fall back to name matching and event timestamps.
            const tool = outcome?.tool_uuid
              ? (attached.find((item) => item.tool_uuid === outcome.tool_uuid) ?? {
                  name,
                  tool_uuid: outcome.tool_uuid,
                })
              : attached.find(
                  (item) => item.name.toLowerCase().replace(/[^a-z0-9_]/g, "_") === name,
                );
            const start = starts.get(event.payload.tool_call_id);
            const duration =
              outcome?.duration_ms ??
              (start ? Date.parse(event.timestamp) - Date.parse(start.timestamp) : NaN);
            const succeeded = outcome?.ok ?? legacyOutcome(event.payload.result);
            return (
              <li
                key={`${event.payload.tool_call_id || name}-${index}`}
                className="rounded-md border px-3 py-2 text-sm"
              >
                <span className="font-medium">{tool?.name || name}</span>{" "}
                <span className="text-muted-foreground">
                  {tool ? "Studio tool" : "Workflow action"}
                </span>
                {tool && <code className="ml-2 text-xs">{tool.tool_uuid}</code>}
                <span className="ml-2">
                  {name === "verify_identity" && outcome?.verified === false
                    ? "Not verified"
                    : name === "verify_identity" && outcome?.verified === true
                      ? "Verified"
                      : succeeded === true
                        ? "Succeeded"
                        : succeeded === false
                          ? `Failed${outcome?.error_code ? `: ${outcome.error_code}` : ""}`
                          : "Outcome not recorded"}
                </span>
                {Number.isFinite(duration) && (
                  <span className="ml-2 text-muted-foreground">{duration} ms</span>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
