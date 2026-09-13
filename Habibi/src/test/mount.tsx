/**
 * Mount a screen or panel the way the app does: inside a query client and a
 * memory router, so `Link`, `useNavigate` and the api/ hooks all work. Pair
 * with `installWireFetch` so the api/ modules run for real against the wire
 * samples. Every route test used to carry its own copy of this.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  Outlet,
  RouterProvider,
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
} from "@tanstack/react-router";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";

export function mountAt(
  path: string,
  element: ReactElement,
  options: { entry?: string; validateSearch?: (search: Record<string, unknown>) => unknown } = {},
) {
  const rootRoute = createRootRoute({ component: Outlet });
  const route = createRoute({
    getParentRoute: () => rootRoute,
    path,
    validateSearch: options.validateSearch,
    component: () => element,
  });
  const router = createRouter({
    routeTree: rootRoute.addChildren([route]),
    history: createMemoryHistory({ initialEntries: [options.entry ?? path] }),
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}
