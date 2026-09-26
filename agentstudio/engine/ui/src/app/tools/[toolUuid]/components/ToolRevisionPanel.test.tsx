import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ToolRevisionPanel, type ToolRevision } from "./ToolRevisionPanel";

const listRevisions = vi.fn();
const submitRevision = vi.fn();

vi.mock("@/client/sdk.gen", () => ({
    listToolRevisionsApiV1ToolsToolUuidRevisionsGet: (...args: unknown[]) =>
        listRevisions(...args),
    submitToolRevisionApiV1ToolsToolUuidRevisionsRevisionSubmitPost: (...args: unknown[]) =>
        submitRevision(...args),
}));

vi.mock("@/host/ToolReview", () => ({
    default: ({ revision, state }: { revision: number; state: string }) => (
        <span>{`review r${revision} ${state}`}</span>
    ),
}));

vi.mock("@/lib/auth", () => ({
    useAuth: () => ({ user: { id: 1 }, getAccessToken: async () => "token", loading: false }),
}));

function revision(overrides: Partial<ToolRevision> = {}): ToolRevision {
    return {
        revision: 3,
        digest: "abcdef0123456789",
        state: "draft",
        snapshot: {
            name: "Post a promise",
            category: "http_api",
            definition: { config: { url: "https://bank.example/promise" } },
        },
        policy: {},
        authoredBy: 1,
        reviewedBy: null,
        createdAt: "2026-09-26T00:00:00Z",
        publishedUsage: 0,
        ...overrides,
    };
}

async function renderPanel(rows: ToolRevision[]) {
    listRevisions.mockResolvedValue({ data: rows, error: undefined });
    render(<ToolRevisionPanel toolUuid="tool-1" />);
    await screen.findByText("Revision history");
}

describe("ToolRevisionPanel", () => {
    beforeEach(() => {
        listRevisions.mockReset();
        submitRevision.mockReset();
    });

    it("submits the latest draft with the policy the reviewer will see", async () => {
        submitRevision.mockResolvedValue({ data: {}, error: undefined });
        await renderPanel([revision(), revision({ revision: 2, state: "approved" })]);

        fireEvent.change(screen.getByLabelText("Success field"), {
            target: { value: "data.ok" },
        });
        fireEvent.change(screen.getByLabelText("Context fields this tool may receive"), {
            target: { value: "initial_context.customer_id, gathered_context.amount" },
        });
        fireEvent.click(screen.getByText("Submit revision 3 for review"));

        await waitFor(() => expect(submitRevision).toHaveBeenCalled());
        const call = submitRevision.mock.calls[0][0];
        expect(call.path).toEqual({ tool_uuid: "tool-1", revision: 3 });
        expect(call.body).toMatchObject({
            risk: "read",
            channels: ["inbound"],
            min_identity: "challenge",
            success_path: "data.ok",
            success_value: true,
            egress_fields: ["initial_context.customer_id", "gathered_context.amount"],
            result_schema: { type: "object" },
        });
    });

    it("will not submit a write without an idempotency parameter", async () => {
        await renderPanel([revision()]);

        fireEvent.click(screen.getByLabelText("Risk"));
        fireEvent.click(screen.getByText("Write — changes a record"));

        const submit = screen.getByText("Submit revision 3 for review").closest("button");
        expect(submit).toBeDisabled();
        expect(screen.getByText("A live write needs an idempotency parameter.")).toBeTruthy();
    });

    it("offers no policy form once a revision has left draft, only its decision", async () => {
        await renderPanel([revision({ state: "submitted" })]);

        expect(screen.queryByText("Submit revision 3 for review")).toBeNull();
        expect(screen.getByText("review r3 submitted")).toBeTruthy();
    });
});
