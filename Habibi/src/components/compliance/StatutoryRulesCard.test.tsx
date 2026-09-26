// @vitest-environment jsdom
// -----------------------------------------------------------------------------
// Statutory rule sets: the approver reads the rules, and the maker cannot be
// the checker. The API existed with no screen, so seeded sets stayed drafts.
// -----------------------------------------------------------------------------
import "@/test/jsdom";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { PolicyRuleSet } from "@/api/compliance";

const state: { sets: PolicyRuleSet[]; me: { id: string; permissions: string[] } } = {
  sets: [],
  me: {
    id: "u-maker",
    permissions: ["perm-policy-publish", "perm-policy-approve", "perm-platform-write"],
  },
};
const mutate = vi.fn();

vi.mock("@/api/compliance", () => ({
  usePolicyRuleSets: () => ({ data: state.sets, isLoading: false, isError: false }),
  usePolicyRuleSetAction: () => ({ mutate, isPending: false, variables: undefined }),
}));
vi.mock("@/api/me", () => ({
  useMe: () => ({ data: state.me }),
  can: (me: { permissions: string[] }, p: string) => me.permissions.includes(p),
}));

import { StatutoryRulesCard } from "./StatutoryRulesCard";

function set(over: Partial<PolicyRuleSet>): PolicyRuleSet {
  return {
    id: "PRS-STATUTORY-V1",
    scope: "statutory",
    version: 1,
    label: "RBI outsourcing of recovery",
    effective_from: "2020-01-01T00:00:00Z",
    effective_to: "2027-01-01T00:00:00Z",
    publication_state: "draft",
    rules: [
      {
        kind: "calling_window",
        channel: "voice",
        params: { startHour: 8, endHour: 19 },
        citation: "x",
      },
    ],
    ...over,
  };
}

function show() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <StatutoryRulesCard />
    </QueryClientProvider>,
  );
}

describe("StatutoryRulesCard", () => {
  it("shows what a draft says and lets the maker submit it", () => {
    state.sets = [set({})];
    show();
    expect(screen.getByText("voice calls only 08:00–19:00")).toBeInTheDocument();
    screen.getByRole("button", { name: "Submit for approval" }).click();
    expect(mutate).toHaveBeenCalledWith({ id: "PRS-STATUTORY-V1", action: "submit" });
  });

  it("does not offer approval to the person who submitted it", () => {
    state.sets = [set({ publication_state: "pending_approval", published_by_user_id: "u-maker" })];
    show();
    expect(screen.queryByRole("button", { name: "Approve and publish" })).toBeNull();
    expect(screen.getByText(/a different approver must publish it/)).toBeInTheDocument();
  });

  it("offers approval to a different checker", () => {
    state.sets = [set({ publication_state: "pending_approval", published_by_user_id: "u-other" })];
    show();
    expect(screen.getByRole("button", { name: "Approve and publish" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reject" })).toBeInTheDocument();
  });

  it("a tenant compliance officer sees the set but cannot act on it", () => {
    // The database refuses a tenant's write to a platform-wide row; offering
    // the button anyway is how Submit became a 500.
    state.me = { id: "u-officer", permissions: ["perm-policy-publish", "perm-policy-approve"] };
    state.sets = [set({})];
    show();
    expect(screen.queryByRole("button", { name: "Submit for approval" })).toBeNull();
    expect(
      screen.getByText(/a platform administrator submits and approves it/),
    ).toBeInTheDocument();
  });

  it("break-glass: the named operator self-approves only with a written reason", () => {
    state.me = {
      id: "u-maker",
      permissions: ["perm-policy-publish", "perm-policy-approve", "perm-platform-write"],
    };
    state.sets = [
      set({
        publication_state: "pending_approval",
        published_by_user_id: "u-maker",
        selfApprovable: true,
      }),
    ];
    mutate.mockClear();
    show();
    fireEvent.click(screen.getByRole("button", { name: /Approve my own submission/ }));
    const go = screen.getByRole("button", { name: "Self-approve and publish" });
    expect(go).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/four eyes/), { target: { value: "too short" } });
    expect(go).toBeDisabled();
    const reason = "Sole operator on the demo tenant; RBI text confirmed.";
    fireEvent.change(screen.getByLabelText(/four eyes/), { target: { value: reason } });
    fireEvent.click(go);
    expect(mutate).toHaveBeenCalledWith({
      id: "PRS-STATUTORY-V1",
      action: "approve",
      selfApprovalReason: reason,
    });
  });

  it("a published self-approval says so", () => {
    state.sets = [
      set({
        publication_state: "published",
        published_by_user_id: "u-maker",
        approved_by_user_id: "u-maker",
      }),
    ];
    show();
    expect(screen.getByText("self-approved (break-glass)")).toBeInTheDocument();
  });
});
