// @vitest-environment jsdom
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { useId, type ReactNode } from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import "@/test/jsdom";

import { bindControlId } from "./bind-control-id";
import { Input } from "./input";
import { Label } from "./label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./select";
import { Slider } from "./slider";

const srcRoot = join(dirname(fileURLToPath(import.meta.url)), "../..");

const FIELD_SHEETS = [
  "components/promises/PromiseSheet.tsx",
  "components/promises/PlanBuilderSheet.tsx",
  "components/customer360/ActionSheets.tsx",
  "components/disputes/DisputeSheet.tsx",
  "components/documents/NewRequestSheet.tsx",
  "components/documents/RequestSheet.tsx",
] as const;

/** Same shape as the six business-form Field helpers: useId + htmlFor + bindControlId. */
function Field({ label, children }: { label: string; children: ReactNode }) {
  const id = useId();
  return (
    <div>
      <Label htmlFor={id}>{label}</Label>
      {bindControlId(children, id, label)}
    </div>
  );
}

describe("bindControlId", () => {
  it("pairs Amount (₹) with the number input, so the accessible name is the visible words", () => {
    render(
      <Field label="Amount (₹)">
        <Input type="number" defaultValue="5000" />
      </Field>,
    );
    const control = screen.getByLabelText("Amount (₹)");
    expect(control).toBeInstanceOf(HTMLInputElement);
    expect(control).toHaveAttribute("type", "number");
  });

  it("labels only the first sibling, leaving a hint unnamed", () => {
    render(
      <Field label="Customer">
        <select>
          <option>Ada</option>
        </select>
        <div>Outstanding on file</div>
      </Field>,
    );
    expect(screen.getByLabelText("Customer").tagName).toBe("SELECT");
    expect(screen.getByText("Outstanding on file")).not.toHaveAttribute("id");
  });

  it("pushes the id onto SelectTrigger, not the Select root", () => {
    render(
      <Field label="Customer">
        <Select defaultValue="ada">
          <SelectTrigger className="h-9">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="ada">Ada</SelectItem>
          </SelectContent>
        </Select>
      </Field>,
    );
    const trigger = screen.getByRole("combobox", { name: "Customer" });
    expect(trigger).toHaveAttribute("id");
    expect(trigger.tagName).toBe("BUTTON");
  });

  it("names a Slider with aria-label because its root is not labelable", () => {
    render(
      <Field label="Installments · 4">
        <Slider defaultValue={[4]} min={1} max={12} />
      </Field>,
    );
    expect(screen.getByLabelText("Installments · 4")).toHaveAttribute(
      "aria-label",
      "Installments · 4",
    );
  });
});

describe("the six Field helpers adopt the pairing", () => {
  it.each(FIELD_SHEETS)("%s generates an id and pairs htmlFor", (rel) => {
    const src = readFileSync(join(srcRoot, rel), "utf8");
    expect(src).toContain("useId()");
    expect(src).toContain("htmlFor={id}");
    expect(src).toContain("bindControlId");
  });
});
