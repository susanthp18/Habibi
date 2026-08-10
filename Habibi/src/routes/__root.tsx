import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  Outlet,
  Link,
  createRootRouteWithContext,
  useRouter,
  HeadContent,
  Scripts,
} from "@tanstack/react-router";
import { useEffect, type ReactNode } from "react";

import appCss from "../styles.css?url";
import { reportLovableError } from "../lib/lovable-error-reporting";
import { clearSidebarCollapsedPreference } from "@/components/shell/sidebar-ui";

function NotFoundComponent() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-200">
      <div className="max-w-md text-center">
        <h1 className="text-7xl font-bold text-foreground">404</h1>
        <h2 className="mt-200 text-xl font-semibold text-foreground">Page not found</h2>
        <p className="mt-100 text-sm text-muted-foreground">
          The page you're looking for doesn't exist or has been moved.
        </p>
        <div className="mt-300">
          <Link
            to="/"
            className="inline-flex items-center justify-center rounded-medium bg-primary px-200 py-100 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
          >
            Go home
          </Link>
        </div>
      </div>
    </div>
  );
}

function ErrorComponent({ error, reset }: { error: Error; reset: () => void }) {
  console.error(error);
  const router = useRouter();
  const correlationId =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : `err-${Date.now()}`;
  useEffect(() => {
    reportLovableError(error, {
      boundary: "tanstack_root_error_component",
      correlationId,
    });
    // Stuck collapse preference was bricking every refresh after one bad render.
    clearSidebarCollapsedPreference();
  }, [error, correlationId]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-200">
      <div className="max-w-md text-center">
        <h1 className="text-xl font-semibold tracking-tight text-foreground">
          This page didn't load
        </h1>
        <p className="mt-100 text-sm text-muted-foreground">
          Something went wrong on our end. You can try refreshing or head back home.
        </p>
        <p className="mt-150 break-all rounded-medium bg-muted px-150 py-100 text-left text-body-small text-muted-foreground">
          Reference: {correlationId}
        </p>
        <div className="mt-300 flex flex-wrap justify-center gap-100">
          <button
            onClick={() => {
              clearSidebarCollapsedPreference();
              router.invalidate();
              reset();
            }}
            className="inline-flex items-center justify-center rounded-medium bg-primary px-200 py-100 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
          >
            Try again
          </button>
          <a
            href="/"
            onClick={() => clearSidebarCollapsedPreference()}
            className="inline-flex items-center justify-center rounded-medium border border-input bg-background px-200 py-100 text-sm font-medium text-foreground transition-colors hover:bg-accent"
          >
            Go home
          </a>
        </div>
      </div>
    </div>
  );
}

export const Route = createRootRouteWithContext<{ queryClient: QueryClient }>()({
  head: () => ({
    meta: [
      { charSet: "utf-8" },
      { name: "viewport", content: "width=device-width, initial-scale=1" },
      { title: "BigBound AI — Collections Workspace for BFSI" },
      {
        name: "description",
        content: "Voice-first collections AI with an enterprise CRM workspace for BFSI teams.",
      },
      { property: "og:title", content: "BigBound AI — Collections Workspace for BFSI" },
      {
        property: "og:description",
        content: "Voice-first collections AI with an enterprise CRM workspace for BFSI teams.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
      { name: "theme-color", content: "#1868DB" },
    ],
    links: [
      { rel: "stylesheet", href: appCss },
      // SVG is the source of truth — crisp at every tab and bookmark size. The PNGs
      // exist only for consumers that can't take SVG (iOS home screen, PWA install).
      { rel: "icon", href: "/favicon.svg", type: "image/svg+xml" },
      { rel: "apple-touch-icon", href: "/apple-touch-icon.png" },
      { rel: "manifest", href: "/site.webmanifest" },
      { rel: "preconnect", href: "https://fonts.googleapis.com" },
      { rel: "preconnect", href: "https://fonts.gstatic.com", crossOrigin: "anonymous" },
      {
        // Atlassian Sans/Mono are proprietary, unlicensed for this app — Inter (kept; Atlassian
        // Sans is itself Inter-derived) and JetBrains Mono (same lineage as Atlassian Mono,
        // free/SIL-OFL) stand in. Inter loads as a variable font (wght@1..1000) so Design.md's
        // weight-bold (653) renders exactly instead of snapping to the nearest static cut.
        rel: "stylesheet",
        href: "https://fonts.googleapis.com/css2?family=Inter:wght@1..1000&family=JetBrains+Mono:wght@400;500;600;700&display=swap",
      },
    ],
  }),
  shellComponent: RootShell,
  component: RootComponent,
  notFoundComponent: NotFoundComponent,
  errorComponent: ErrorComponent,
});

function RootShell({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <head>
        <HeadContent />
      </head>
      <body>
        {children}
        <Scripts />
      </body>
    </html>
  );
}

function RootComponent() {
  const { queryClient } = Route.useRouteContext();

  return (
    <QueryClientProvider client={queryClient}>
      {/* Required: nested routes render here. Removing <Outlet /> breaks all child routes. */}
      <Outlet />
    </QueryClientProvider>
  );
}
