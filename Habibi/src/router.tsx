import { QueryClient } from "@tanstack/react-query";
import { createRouter } from "@tanstack/react-router";
import { setAfterWrite } from "@/api/config";
import { movesWorkspace } from "@/api/workspace";
import { createMutationCache } from "@/lib/mutation-errors";
import { routeTree } from "./routeTree.gen";

export const getRouter = () => {
  const queryClient = new QueryClient({
    mutationCache: createMutationCache(),
    defaultOptions: {
      queries: {
        retry: 1,
        staleTime: 15_000,
        refetchOnWindowFocus: false,
      },
      mutations: {
        retry: 0,
      },
    },
  });

  // My Workspace's queue and summary stay mounted in the shell (notifications,
  // palette): refresh them after any write that can change them.
  setAfterWrite((path) => {
    if (!movesWorkspace(path)) return;
    void queryClient.invalidateQueries({ queryKey: ["work-items"] });
    void queryClient.invalidateQueries({ queryKey: ["workspace-summary"] });
  });

  const base = (import.meta.env.BASE_URL || "/").replace(/\/$/, "") || "/";
  const router = createRouter({
    routeTree,
    context: { queryClient },
    ...(base !== "/" ? { basepath: base } : {}),
    scrollRestoration: true,
    defaultPreload: "intent",
    // Hovering a link preloads; below the QueryClient staleTime it would
    // refetch data the screen already holds fresh.
    defaultPreloadStaleTime: 15_000,
  });

  return router;
};
