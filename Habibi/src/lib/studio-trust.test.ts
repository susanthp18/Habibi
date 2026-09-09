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

describe("studio truth wiring", () => {
  it("invalidates both deployment query roots after rollback", () => {
    const prompt = readFileSync(join(here, "..", "api", "prompt-studio.ts"), "utf8");
    expect(prompt).toContain('queryKey: ["deployments"]');
    expect(prompt).toContain('["bot-deployments"]');
    const studio = readFileSync(join(here, "..", "api", "agent-studio.ts"), "utf8");
    expect(studio).toContain('queryKey: ["deployments"]');
    expect(studio).toContain('queryKey: ["bot-deployments"]');
  });

  it("Ship tab rolls back the prior deployment and surfaces experiment errors", () => {
    const src = readFileSync(
      join(here, "..", "components", "prompt-studio", "ShipTab.tsx"),
      "utf8",
    );
    expect(src).toContain("shipRollbackTarget");
    expect(src).toContain("experiments.isError");
    expect(src).toContain('status === "running"');
    // The shadow control is gone, not merely disabled: `experiment.shadow` was
    // removed from the card, so there is nothing to tick. This used to assert
    // the disabled checkbox's copy, which is the weakness of a source grep —
    // it pinned a sentence rather than the absence of a control, and went red
    // for the change that made it true.
    expect(src).not.toContain("value.shadow");
  });

  it("Outbound and Flow failed reads are not empty/zero", () => {
    const outbound = readFileSync(
      join(here, "..", "components", "prompt-studio", "OutboundTab.tsx"),
      "utf8",
    );
    expect(outbound).toContain("preview.isError");
    expect(outbound).toContain("campaigns.isError");
    expect(outbound).toContain("stats.isError");
    const flow = readFileSync(join(here, "..", "components", "flow", "FlowInspector.tsx"), "utf8");
    expect(flow).toContain("vocab.isError");
  });

  it("Guardrails labels unenforced controls as post-reply flags", () => {
    const src = readFileSync(
      join(here, "..", "components", "prompt-studio", "GuardrailsPanel.tsx"),
      "utf8",
    );
    expect(src).toContain("not a live hard-block");
  });

  it("Bindings disable non-live models", () => {
    const src = readFileSync(
      join(here, "..", "components", "prompt-studio", "BindingsTab.tsx"),
      "utf8",
    );
    expect(src).toContain("modelBindingSelectable");
  });
});
