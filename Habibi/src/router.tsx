import { QueryClient } from "@tanstack/react-query";
import { createRouter } from "@tanstack/react-router";
import { createMutationCache } from "@/lib/mutation-errors";
import { routeTree } from "./routeTree.gen";

export const getRouter = () => {
  const queryClient = new QueryClient({
    mutationCache: createMutationCache(),
    defaultOptions: {
      queries: {
        retry: 1,
        staleTime: 15_000,
        refetchOnWindowFocus: true,
      },
      mutations: {
        retry: 0,
      },
    },
  });

  const router = createRouter({
    routeTree,
    context: { queryClient },
    scrollRestoration: true,
    defaultPreload: "intent",
    // Hovering a link preloads; below the QueryClient staleTime it would
    // refetch data the screen already holds fresh.
    defaultPreloadStaleTime: 15_000,
  });

  return router;
};
