// @vitest-environment jsdom
// -----------------------------------------------------------------------------
// Agent routing: a channel change is validated against the published agent
// before it can be activated, and failures are shown, not swallowed.
// -----------------------------------------------------------------------------
import "@/test/jsdom";

import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { mountAt } from "@/test/mount";

const check = vi.fn();
const assign = vi.fn();
const state = { permissions: ["perm-agent-publish", "perm-voice-operate"] };

vi.mock("@/api/voice-studio", () => ({
  useStudioRouting: () => ({
    status: "success",
    isPending: false,
    isError: false,
    isSuccess: true,
    data: {
      agents: [
        { id: 4, name: "Collections - overdue reminder" },
        { id: 9, name: "WhatsApp - customer help" },
      ],
      bindings: [{ objective: "*", engine_workflow_id: 4, label: null }],
      numbers: [],
    },
  }),
  useCheckRouting: () => ({ mutateAsync: check, isPending: false, isError: false }),
  useAssignRouting: () => ({
    mutateAsync: assign,
    isPending: false,
    isError: false,
    isSuccess: false,
  }),
}));
vi.mock("@/api/me", () => ({
  useMe: () => ({ data: { permissions: state.permissions } }),
  can: (me: { permissions: string[] }, p: string) => me.permissions.includes(p),
}));

const { default: RoutingPage } = await import("./RoutingPage");

async function chooseWhatsAppAgent() {
  mountAt("/", <RoutingPage />);
  expect(
    await screen.findByText(/Outbound \*: Collections - overdue reminder/),
  ).toBeInTheDocument();
  // SelectField renders a combobox; pick by keyboard-free click flow.
  fireEvent.click(screen.getByLabelText("Channel"));
  fireEvent.click(await screen.findByRole("option", { name: "WhatsApp" }));
  fireEvent.click(screen.getByLabelText("Published agent"));
  fireEvent.click(await screen.findByRole("option", { name: "WhatsApp - customer help" }));
}

describe("Voice Studio agent routing", () => {
  beforeEach(() => {
    check.mockReset();
    assign.mockReset();
    state.permissions = ["perm-agent-publish", "perm-voice-operate"];
  });

  it("activates only after the selection validates", async () => {
    check.mockResolvedValue({
      ok: true,
      errors: [],
      warnings: [],
      name: "WhatsApp - customer help",
      version: 2,
      definitionId: 21,
    });
    await chooseWhatsAppAgent();
    const activate = screen.getByRole("button", { name: "Activate routing" });
    expect(activate).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Validate selection" }));
    expect(await screen.findByText("Ready to activate")).toBeInTheDocument();
    expect(check).toHaveBeenCalledWith({ channel: "whatsapp", workflowId: 9 });
    await waitFor(() => expect(activate).toBeEnabled());
    fireEvent.click(activate);
    await waitFor(() =>
      expect(assign).toHaveBeenCalledWith({ channel: "whatsapp", workflowId: 9 }),
    );
  });

  it("shows why a selection is not ready and keeps activation off", async () => {
    check.mockResolvedValue({
      ok: false,
      errors: ["general: needs a human handoff"],
      warnings: [],
    });
    await chooseWhatsAppAgent();
    fireEvent.click(screen.getByRole("button", { name: "Validate selection" }));
    expect(await screen.findByText("general: needs a human handoff")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Activate routing" })).toBeDisabled();
  });

  it("does not let a user without both permissions activate", async () => {
    state.permissions = ["perm-agent-publish"];
    check.mockResolvedValue({
      ok: true,
      errors: [],
      warnings: [],
      name: "x",
      version: 1,
      definitionId: 1,
    });
    await chooseWhatsAppAgent();
    fireEvent.click(screen.getByRole("button", { name: "Validate selection" }));
    await screen.findByText("Ready to activate");
    expect(screen.getByRole("button", { name: "Activate routing" })).toBeDisabled();
  });
});
