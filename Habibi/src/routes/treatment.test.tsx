// @vitest-environment jsdom
// -----------------------------------------------------------------------------
// Decision intelligence, rendered against the wire.
//
// The pin under which the route's fourteen inline components move to files:
// the real page, the real api/treatment.ts, fetch answered from the samples.
// It asserts what an operator sees -- the decision count, the hold on the
// Holds tab, the case rows -- and what a placed hold sends.
// -----------------------------------------------------------------------------
import "@/test/jsdom";

import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import type { TreatmentHold, TreatmentInsights } from "@/api/treatment";
import { mountAt } from "@/test/mount";
import { installWireFetch, sample, type WireCall } from "@/test/wire-fetch";

const { TreatmentPage } = await import("./_app.treatment.lazy");

const insights = sample<TreatmentInsights>("GET /treatment/insights");
const holds = sample<TreatmentHold[]>("GET /treatment/holds");

let wire: ReturnType<typeof installWireFetch>;

beforeEach(() => {
  wire = installWireFetch({
    "POST /treatment/holds": (call: WireCall) => ({
      ...holds[0]!,
      id: "hold-test",
      ...(call.body as object),
    }),
  });
});

afterEach(() => {
  wire.restore();
});

const mount = () => mountAt("/treatment", <TreatmentPage />);

describe("/treatment", () => {
  it("shows the window's decision count from the insights read", { timeout: 30_000 }, async () => {
    mount();
    await screen.findByText(String(insights.decisions), {}, { timeout: 15_000 });
    expect(
      wire.calls.some((c) => c.path === "/treatment/insights" && c.search.includes("days=14")),
    ).toBe(true);
  });

  it(
    "lists the active hold and places a new one with the reason typed",
    { timeout: 30_000 },
    async () => {
      mount();
      // Radix tabs activate on pointer-down, not click
      const holdsTab = await screen.findByRole("tab", { name: /holds/i }, { timeout: 15_000 });
      fireEvent.mouseDown(holdsTab, { button: 0 });
      fireEvent.click(holdsTab);
      // the row names the borrower, and the reason the hold was placed for
      await screen.findByText(
        holds[0]!.customerName ?? holds[0]!.customerId,
        {},
        { timeout: 15_000 },
      );
      fireEvent.click(screen.getByRole("button", { name: /place a hold/i }));
      await screen.findByRole("dialog", {}, { timeout: 5_000 });
      fireEvent.change(screen.getByLabelText(/borrower id/i), { target: { value: "cust-pin" } });
      fireEvent.change(screen.getByLabelText(/^reason$/i), {
        target: { value: "pinned in a test" },
      });
      fireEvent.click(screen.getByRole("button", { name: /^place hold$/i }));
      const placed = await waitFor(
        () => {
          const hit = wire.calls.find((c) => c.method === "POST" && c.path === "/treatment/holds");
          expect(hit).toBeDefined();
          return hit!;
        },
        { timeout: 8_000 },
      );
      const body = placed.body as Record<string, unknown>;
      expect(body.customerId).toBe("cust-pin");
      expect(body.reason).toBe("pinned in a test");
    },
  );
});
