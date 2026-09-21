// @vitest-environment jsdom
import "@/test/jsdom";

import { render, screen } from "@testing-library/react";
import {
  Outlet,
  RouterProvider,
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
} from "@tanstack/react-router";
import { describe, expect, it } from "vitest";

import type { AtRiskAccount } from "@/api/types/dashboard";
import { AtRiskAccounts } from "./AtRiskAccounts";

const anita: AtRiskAccount = {
  id: "anita-desai",
  name: "Anita Desai",
  account: "AC-88214",
  outstanding: 12480,
  daysPastDue: 92,
  risk: "critical",
  lastContact: "2026-07-19T08:45:00+00:00",
  product: "Personal Loan",
};

function mount() {
  const rootRoute = createRootRoute({ component: Outlet });
  const dashboard = createRoute({
    getParentRoute: () => rootRoute,
    path: "/dashboard",
    component: () => <AtRiskAccounts accounts={[anita]} />,
  });
  const customer = createRoute({
    getParentRoute: () => rootRoute,
    path: "/customers/$customerId",
    component: () => null,
  });
  const router = createRouter({
    routeTree: rootRoute.addChildren([dashboard, customer]),
    history: createMemoryHistory({ initialEntries: ["/dashboard"] }),
  });
  return render(<RouterProvider router={router} />);
}

describe("AtRiskAccounts", () => {
  it("opens Customer 360 for the account row, not a coming-soon toast", async () => {
    mount();
    const link = await screen.findByRole("link", { name: /Anita Desai/i });
    expect(link).toHaveAttribute("href", "/customers/anita-desai");
  });
});
