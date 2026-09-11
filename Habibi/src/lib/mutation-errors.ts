import { MutationCache } from "@tanstack/react-query";
import { toast } from "sonner";

import { ApiError } from "@/api/config";

/**
 * Every mutation hook in `src/api` declares who surfaces its failure.
 *
 * `"caller"` — the screen already does (a `.catch` that toasts, an `onError`
 * on the `mutate` call, an `isError` branch it renders). `"toast"` — nothing
 * does, so the cache below does. A rejected write that renders as nothing
 * happening is the studio's most-shipped defect (CONNECTORS-8, EVALS-5,
 * OUTBOUND-14, …); the `no-silent-mutation` lint rule makes the choice
 * mandatory, so a new hook cannot forget to make it.
 */
export type MutationErrors = "toast" | "caller";

declare module "@tanstack/react-query" {
  interface Register {
    mutationMeta: { errors: MutationErrors };
  }
}

export function mutationErrorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.detail || error.message;
  if (error instanceof Error) return error.message;
  return "The request failed.";
}

export function createMutationCache(): MutationCache {
  return new MutationCache({
    onError: (error, _variables, _context, mutation) => {
      if (mutation.meta?.errors === "toast") {
        toast.error(mutationErrorMessage(error), { id: `mutation:${mutationErrorMessage(error)}` });
      }
    },
  });
}
