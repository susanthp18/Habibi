// @vitest-environment jsdom
/**
 * `SelectField` is the primitive that was missing, so it has to behave like the
 * raw `<select>`s it replaced in the two places Radix does not:
 *
 *   - an item's value may not be the empty string, so "none" needs a sentinel
 *   - `value=""` on the root means *unset*, which is how a placeholder shows
 *
 * Eighty call sites depend on that distinction being made here rather than
 * eighty times, and three of them offer "none" as a choice the user can pick
 * back ("— share the general pool —", "— no extra ceiling —", "— stop, escalate
 * to nobody —"). Getting it wrong shows the placeholder where a chosen answer
 * should be.
 *
 * It also has to carry an `id` down to the trigger: `bindControlId` lands the id
 * on whichever element it is handed, and a Radix `Select` root renders no DOM,
 * so a field that keeps the id on its own root is a form control with no label.
 */
import { useId, useState, type ReactNode } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import "@/test/jsdom";

import { bindControlId } from "./bind-control-id";
import { Label } from "./label";
import { SelectField, type SelectOption } from "./select";

const POOLS: SelectOption[] = [
  { value: "", label: "— share the general pool —" },
  { value: "1600", label: "1600-series (statutory)" },
  { value: "mkt", label: "Marketing pool" },
];

function Controlled({
  initial = "",
  options = POOLS,
}: {
  initial?: string;
  options?: SelectOption[];
}) {
  const [value, setValue] = useState(initial);
  return (
    <>
      <SelectField
        aria-label="Caller-ID pool"
        value={value}
        onChange={setValue}
        options={options}
        placeholder="Pick a pool"
      />
      <output data-testid="value">{value === "" ? "(empty)" : value}</output>
    </>
  );
}

/** The six business-form Field helpers, in miniature. */
function Field({ label, children }: { label: string; children: ReactNode }) {
  const id = useId();
  return (
    <div>
      <Label htmlFor={id}>{label}</Label>
      {bindControlId(children, id, label)}
    </div>
  );
}

describe("SelectField", () => {
  it("shows the none option's own label, not the placeholder, when the value is empty", () => {
    render(<Controlled />);
    const trigger = screen.getByRole("combobox", { name: "Caller-ID pool" });
    expect(trigger).toHaveTextContent("— share the general pool —");
    expect(trigger).not.toHaveTextContent("Pick a pool");
  });

  it("shows the placeholder when the list has no none option to fall back on", () => {
    render(<Controlled options={POOLS.slice(1)} />);
    expect(screen.getByRole("combobox", { name: "Caller-ID pool" })).toHaveTextContent(
      "Pick a pool",
    );
  });

  it("stays controlled when its value arrives after mount", () => {
    // The Sandbox pickers mount empty and get a value once their query lands.
    // Handing Radix `undefined` for "unset" made it uncontrolled, and React
    // warned "changing from uncontrolled to controlled" on every page load.
    // Radix raises it with console.warn (react-use-controllable-state).
    const warnings: unknown[][] = [];
    const original = console.warn;
    console.warn = (...args: unknown[]) => warnings.push(args);
    try {
      const props = { "aria-label": "Prompt", onChange: () => {}, options: POOLS.slice(1) };
      const { rerender } = render(<SelectField {...props} value="" placeholder="Pick a pool" />);
      rerender(<SelectField {...props} value="mkt" placeholder="Pick a pool" />);
      expect(screen.getByRole("combobox", { name: "Prompt" })).toHaveTextContent("Marketing pool");
    } finally {
      console.warn = original;
    }
    expect(warnings.map((a) => String(a[0])).filter((m) => /uncontrolled/i.test(m))).toEqual([]);
  });

  it("reports an empty string, not the sentinel, when none is chosen", async () => {
    const user = userEvent.setup();
    render(<Controlled initial="1600" />);
    await user.click(screen.getByRole("combobox", { name: "Caller-ID pool" }));
    await user.click(await screen.findByRole("option", { name: "— share the general pool —" }));
    // The caller stores what it always stored. The sentinel never escapes.
    expect(screen.getByTestId("value")).toHaveTextContent("(empty)");
  });

  it("reports the chosen value for an ordinary option", async () => {
    const user = userEvent.setup();
    render(<Controlled />);
    await user.click(screen.getByRole("combobox", { name: "Caller-ID pool" }));
    await user.click(await screen.findByRole("option", { name: "Marketing pool" }));
    expect(screen.getByTestId("value")).toHaveTextContent("mkt");
  });

  it("opens to every option it was given", async () => {
    const user = userEvent.setup();
    render(<Controlled />);
    await user.click(screen.getByRole("combobox", { name: "Caller-ID pool" }));
    expect(await screen.findAllByRole("option")).toHaveLength(POOLS.length);
  });

  it("carries a Field's id down to the trigger, so the visible words name the control", () => {
    render(
      <Field label="Customer">
        <SelectField
          value="c1"
          onChange={() => {}}
          options={[{ value: "c1", label: "Ada Lovelace · 4402" }]}
        />
      </Field>,
    );
    const trigger = screen.getByRole("combobox", { name: "Customer" });
    expect(trigger).toHaveAttribute("id");
    expect(trigger.tagName).toBe("BUTTON");
  });

  it("is disabled when the caller says so", () => {
    render(
      <SelectField
        aria-label="Reviewer"
        value=""
        onChange={() => {}}
        options={[]}
        placeholder="Loading reviewers…"
        disabled
      />,
    );
    expect(screen.getByRole("combobox", { name: "Reviewer" })).toBeDisabled();
  });
});
