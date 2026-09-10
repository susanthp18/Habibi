import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  connectorHealthToast,
  lintDisplay,
  modelBindingLabel,
  modelBindingSelectable,
  shipRollbackTarget,
  worstEvalStatus,
} from "./studio-trust";

const here = dirname(fileURLToPath(import.meta.url));

describe("worstEvalStatus", () => {
  it("never greens a failed regression behind a passing red-team", () => {
    expect(worstEvalStatus("pass", "fail")).toBe("fail");
    expect(worstEvalStatus("fail", "pass")).toBe("fail");
    expect(worstEvalStatus("error", "pass")).toBe("fail");
  });

  it("treats a pass as better than skipped, and empty as skipped", () => {
    expect(worstEvalStatus("skipped", "pass")).toBe("pass");
    expect(worstEvalStatus(null, undefined)).toBe("skipped");
  });
});

describe("shipRollbackTarget", () => {
  it("targets the prior deployment, never the active row", () => {
    expect(
      shipRollbackTarget({
        rollbackDeploymentId: "DEP-prior",
        priorDeploymentId: "DEP-older",
      }),
    ).toBe("DEP-prior");
    expect(shipRollbackTarget({ priorDeploymentId: "DEP-older" })).toBe("DEP-older");
    expect(shipRollbackTarget({})).toBeNull();
  });
});

describe("lintDisplay", () => {
  it("does not render a failed fetch as a clean prompt", () => {
    expect(lintDisplay({ isError: true, isPending: false }).kind).toBe("error");
    expect(lintDisplay({ isError: false, isPending: true }).kind).toBe("pending");
    expect(lintDisplay({ isError: false, isPending: false }).kind).toBe("findings");
  });
});

describe("modelBindingSelectable", () => {
  it("only live models are constructable", () => {
    expect(modelBindingSelectable("live")).toBe(true);
    expect(modelBindingSelectable("preview_only")).toBe(false);
    expect(modelBindingSelectable("unavailable")).toBe(false);
    expect(modelBindingLabel("GPT", "preview_only")).toBe("GPT (preview only)");
    expect(modelBindingLabel("GPT", "unavailable")).toBe("GPT (unavailable)");
    expect(modelBindingLabel("GPT", "live")).toBe("GPT");
  });
});

describe("connectorHealthToast", () => {
  it("toasts from ok, not from HTTP 200 with ok:false", () => {
    expect(connectorHealthToast({ ok: true })).toBe("ok");
    expect(connectorHealthToast({ ok: false })).toBe("fail");
    expect(connectorHealthToast(null)).toBe("empty");
  });
});

// The "studio truth wiring" block stood here: six assertions that read a
// component's source for a substring. Each is now either a rendered assertion
// or a lint, next to the thing it describes:
//   ShipTab rollback / experiments  -> ShipTab.test.tsx
//   GuardrailsPanel copy            -> GuardrailsPanel.test.tsx
//   BindingsTab selectable models   -> BindingsTab.test.tsx
//   deployment query keys           -> api/agent-studio.export.test.ts, which
//                                      asserts the key set `invalidateAgentStudio`
//                                      actually invalidates. `prompt-studio.ts`'s
//                                      own rollback mutation is not covered by a
//                                      test; the grep did not cover it either,
//                                      it only checked two strings appeared.
//   OutboundTab                     -> OutboundTab.test.tsx
//   FlowInspector                   -> FlowInspector.test.tsx (via NodeInspector)
//   no raw fetch in a view          -> scripts/check-layering.mjs
//
// `shipRollbackTarget` and `modelBindingSelectable` were already unit-tested
// above, so those two greps asserted nothing the file did not already prove.
