import { createFileRoute, Outlet } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { AccessGate } from "@/components/access/AccessGate";
import { AppShell } from "@/components/shell/AppShell";
import {
  bounceOffLoopbackIp,
  completeRedirect,
  entraConfigured,
  loginRedirectUri,
} from "@/lib/sso";

/**
 * The application shell as a pathless layout route. Every signed-in page is a
 * child of this route and renders inside one AppShell mounted here, rather than
 * each page wrapping itself (twenty-nine did, and `/login` did not).
 */
export const Route = createFileRoute("/_app")({
  // Browser only, like /studio: the API token exists only in the browser, so a
  // server-side loader (the Customer 360's) went out unsigned and a hard load
  // or refresh of that page answered 500.
  ssr: false,
  component: GatedShell,
});

function GatedShell() {
  const [ready, setReady] = useState(() => !entraConfigured());

  useEffect(() => {
    if (bounceOffLoopbackIp()) return;
    if (!entraConfigured()) return;
    let cancelled = false;
    void completeRedirect().then((account) => {
      if (cancelled) return;
      if (!account) {
        window.location.assign(loginRedirectUri());
        return;
      }
      setReady(true);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!ready) return null;
  return (
    <AppShell>
      <AccessGate>
        <Outlet />
      </AccessGate>
    </AppShell>
  );
}
