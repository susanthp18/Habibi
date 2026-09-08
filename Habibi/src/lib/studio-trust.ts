/**
 * Truth helpers for Agent Studio. Kept out of React so vitest (node, no jsdom)
 * can pin the states the UI used to lie about.
 */

export type EvalStatus = "pass" | "fail" | "skipped" | "error" | string;

/** Worst-of: fail beats pass beats skipped. A failed regression is never green. */
export function worstEvalStatus(...statuses: Array<EvalStatus | null | undefined>): EvalStatus {
  const seen = statuses.filter((s): s is string => Boolean(s));
  if (seen.some((s) => s === "fail" || s === "error")) return "fail";
  if (seen.some((s) => s === "pass")) return "pass";
  return seen[0] ?? "skipped";
}

/**
 * The deployment to roll back *to* — the prior one, never the active row.
 * Rolling back the active id 409s with `deployment_already_active`.
 */
export function shipRollbackTarget(opts: {
  rollbackDeploymentId?: string | null;
  priorDeploymentId?: string | null;
}): string | null {
  return opts.rollbackDeploymentId || opts.priorDeploymentId || null;
}

export type LintDisplay =
  { kind: "error"; message: string } | { kind: "pending" } | { kind: "findings" };

/** A failed lint fetch must not render as a clean prompt. */
export function lintDisplay(opts: {
  isError: boolean;
  isPending: boolean;
  errorMessage?: string;
}): LintDisplay {
  if (opts.isError) {
    return { kind: "error", message: opts.errorMessage || "Lint could not run" };
  }
  if (opts.isPending) return { kind: "pending" };
  return { kind: "findings" };
}

export type ModelRuntime = "live" | "preview_only" | "unavailable" | string;

export function modelBindingSelectable(runtime: ModelRuntime | undefined): boolean {
  return runtime === "live";
}

export function modelBindingLabel(displayName: string, runtime: ModelRuntime | undefined): string {
  if (runtime === "preview_only") return `${displayName} (preview only)`;
  if (runtime === "unavailable") return `${displayName} (unavailable)`;
  return displayName;
}

export type ConnectorHealth = { ok?: boolean } | null | undefined;

export function connectorHealthToast(result: ConnectorHealth): "ok" | "fail" | "empty" {
  if (!result) return "empty";
  return result.ok ? "ok" : "fail";
}
