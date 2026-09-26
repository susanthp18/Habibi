// @vitest-environment jsdom
import "@/test/jsdom";

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/agentstudio/client/sdk.gen", () => ({
  getWorkflowVersionsApiV1WorkflowWorkflowIdVersionsGet: async () => ({
    data: [
      {
        id: 3,
        version_number: 3,
        status: "published",
        workflow_json: { nodes: [{ id: "resolve", data: { tool_uuids: ["uuid-promise"] } }] },
      },
    ],
  }),
  listToolsApiV1ToolsGet: async () => ({
    data: [{ tool_uuid: "uuid-promise", name: "promise_to_pay" }],
  }),
}));

const { default: RunProvenance } = await import("./RunProvenance");

describe("Studio run provenance", () => {
  it("shows the pinned version, Studio tool UUID, duration, and failed business code", async () => {
    render(
      <RunProvenance
        workflowId={1}
        definitionId={3}
        direction="inbound"
        logs={{
          realtime_feedback_events: [
            {
              type: "rtf-function-call-start",
              timestamp: "2026-09-26T09:03:00.000Z",
              turn: 1,
              payload: { function_name: "promise_to_pay", tool_call_id: "tool-1" },
            },
            {
              type: "rtf-function-call-end",
              timestamp: "2026-09-26T09:03:00.250Z",
              turn: 1,
              payload: {
                function_name: "promise_to_pay",
                tool_call_id: "tool-1",
                result_summary: { ok: false, error_code: "promise_revision_cap", http_status: 200 },
              },
            },
          ],
        }}
      />,
    );
    expect(await screen.findByText("uuid-promise")).toBeInTheDocument();
    expect(screen.getByText(/Pinned definition:/)).toHaveTextContent("Version 3");
    expect(screen.getByText("Failed: promise_revision_cap")).toBeInTheDocument();
    expect(screen.getByText("250 ms")).toBeInTheDocument();
  });

  it("prefers the tool UUID, duration and verification recorded on the event", async () => {
    render(
      <RunProvenance
        workflowId={1}
        definitionId={3}
        direction="inbound"
        logs={{
          realtime_feedback_events: [
            {
              type: "rtf-function-call-end",
              timestamp: "2026-09-26T09:04:00.000Z",
              turn: 2,
              payload: {
                function_name: "verify_identity",
                tool_call_id: "tool-2",
                result_summary: {
                  ok: true,
                  error_code: null,
                  verified: false,
                  tool_uuid: "uuid-verify",
                  duration_ms: 412,
                },
              },
            },
          ],
        }}
      />,
    );
    expect(await screen.findByText("uuid-verify")).toBeInTheDocument();
    expect(screen.getByText("Not verified")).toBeInTheDocument();
    expect(screen.getByText("412 ms")).toBeInTheDocument();
  });
});
