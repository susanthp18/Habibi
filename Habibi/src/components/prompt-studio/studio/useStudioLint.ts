import { useCallback, useMemo, useState } from "react";
import { toast } from "sonner";
import { useAutoLint, type PromptLintFinding } from "@/api/prompt-studio";
import type { Guardrails } from "@/api/types/prompt-studio";
import type { useStudioQueries } from "./useStudioQueries";

/** The costed critique's own codes; the auto pass never returns them. */
const ADVISORY_CODES = ["llm_checklist", "llm_lint_failed", "llm_lint_unavailable"];

/**
 * The two lint passes, as one list.
 *
 * The deterministic pass runs continuously (`useAutoLint`) -- it used to need
 * a button, and three PUBLISHED cards carried CRM tokens that delete the line
 * they sit on because nobody had pressed it. The critique pass answers on
 * demand and is additive; its rows are kept only while the prompt and the
 * guardrails are what was actually critiqued, so advice never outlives its
 * subject. The lint is a function of prompt *and* guardrails: toggling
 * alwaysDiscloseRecording used to leave a "missing_recording_disclosure" on
 * screen for a prompt that no longer had that rule.
 */
export function useStudioLint({
  prompt,
  guardrails,
  lintMutation,
  onRead,
}: {
  prompt: string;
  guardrails: Guardrails;
  lintMutation: ReturnType<typeof useStudioQueries>["lintMutation"];
  /** Take the author to the findings ("Read" on the critique toast). */
  onRead: () => void;
}) {
  const [critiqued, setCritiqued] = useState<PromptLintFinding[]>([]);
  const [critiquedFp, setCritiquedFp] = useState<string | null>(null);
  const fp = useMemo(() => JSON.stringify({ prompt, guardrails }), [prompt, guardrails]);
  const auto = useAutoLint({ prompt, guardrails });

  const findings = useMemo(() => {
    const advisory =
      critiquedFp === fp ? critiqued.filter((f) => ADVISORY_CODES.includes(f.code)) : [];
    return [...(auto.data ?? []), ...advisory];
  }, [auto.data, critiqued, critiquedFp, fp]);

  const clear = useCallback(() => {
    setCritiqued([]);
    setCritiquedFp(null);
  }, []);

  // Still a request for the whole lint with `includeLlm`, because the backend
  // owns that composition; only the advisory rows are kept from the response,
  // the deterministic ones being on screen already.
  const critique = useCallback(async () => {
    try {
      const rows = await lintMutation.mutateAsync({ prompt, guardrails, includeLlm: true });
      setCritiqued(rows);
      setCritiquedFp(JSON.stringify({ prompt, guardrails }));
      const advice = rows.filter((f) => f.code === "llm_checklist");
      const unavailable = rows.find(
        (f) => f.code === "llm_lint_failed" || f.code === "llm_lint_unavailable",
      );
      if (unavailable) {
        // A review that could not run must never read as a clean bill of health.
        toast.error("Critique unavailable", { description: unavailable.message });
      } else if (!advice.length) {
        toast.success("Critique clean — nothing flagged in the wording");
      } else {
        toast.message(`Critique: ${advice.length} suggestion(s)`, {
          description: "Advisory — listed beside the editor, nothing was changed",
          action: { label: "Read", onClick: onRead },
        });
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Lint failed");
    }
  }, [lintMutation, prompt, guardrails, onRead]);

  return {
    findings,
    failed: auto.isError,
    pending: auto.isPending && !auto.data,
    busy: lintMutation.isPending,
    critique,
    clear,
  };
}
