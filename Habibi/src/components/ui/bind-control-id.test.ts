import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { Children, createElement, isValidElement, type ReactElement, type ReactNode } from "react";
import { describe, expect, it } from "vitest";

import { bindControlId } from "./bind-control-id";
import { SelectTrigger } from "./select";
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

function SelectRoot({ children }: { children?: ReactNode }) {
  return createElement("div", null, children);
}

function firstElement(node: ReactNode): ReactElement {
  const el = Children.toArray(node).find(isValidElement);
  if (!el) throw new Error("expected an element");
  return el;
}

function propsOf<P>(node: ReactNode): P {
  return firstElement(node).props as P;
}

describe("bindControlId", () => {
  it("sets id on a native input, which is what Amount (₹) is", () => {
    const bound = bindControlId(createElement("input", { type: "number" }), "amt");
    expect(propsOf<{ id?: string }>(bound).id).toBe("amt");
  });

  it("labels only the first sibling, leaving a hint div unnamed", () => {
    const bound = bindControlId(
      [
        createElement("select", { key: "s" }),
        createElement("div", { key: "h" }, "Outstanding on file"),
      ],
      "cust",
    );
    const kids = Children.toArray(bound);
    expect(propsOf<{ id?: string }>(kids[0]).id).toBe("cust");
    expect(propsOf<{ id?: string }>(kids[1]).id).toBeUndefined();
  });

  it("pushes the id onto SelectTrigger, not the Select root", () => {
    const select = createElement(
      SelectRoot,
      null,
      createElement(SelectTrigger, { className: "h-9" }),
      createElement("div", { key: "menu" }),
    );
    const bound = bindControlId(select, "cust");
    expect(propsOf<{ id?: string }>(bound).id).toBeUndefined();
    const trigger = Children.toArray(propsOf<{ children?: ReactNode }>(bound).children).find(
      (node): node is ReactElement<{ id?: string }> =>
        isValidElement(node) && node.type === SelectTrigger,
    );
    expect(trigger?.props.id).toBe("cust");
  });

  it("names a Slider with aria-label because its root is not labelable", () => {
    const bound = bindControlId(createElement(Slider), "inst", "Installments · 4");
    expect(propsOf<{ id?: string; "aria-label"?: string }>(bound)).toMatchObject({
      id: "inst",
      "aria-label": "Installments · 4",
    });
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
