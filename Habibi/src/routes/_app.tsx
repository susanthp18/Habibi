import { createFileRoute, Outlet } from "@tanstack/react-router";
import { AppShell } from "@/components/shell/AppShell";

/**
 * The application shell as a pathless layout route. Every signed-in page is a
 * child of this route and renders inside one AppShell mounted here, rather than
 * each page wrapping itself (twenty-nine did, and `/login` did not).
 */
export const Route = createFileRoute("/_app")({
  component: () => (
    <AppShell>
      <Outlet />
    </AppShell>
  ),
});
