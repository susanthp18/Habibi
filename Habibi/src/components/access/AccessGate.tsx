import type { ReactNode } from "react";

import { needsAccessRequest, useMe } from "@/api/me";
import { NoAccess } from "@/components/access/NoAccess";
import { SessionRenewal } from "@/components/access/SessionRenewal";
import { LoadingState } from "@/components/ui/loading-state";
import { isSessionRenewal } from "@/lib/sso";

/**
 * First-login and deactivated operators can authenticate, but they have
 * nothing to do in the console until an admin grants a role. Replace the
 * page with the request form instead of letting every screen fail-read.
 */
export function AccessGate({ children }: { children: ReactNode }) {
  const me = useMe();

  if (me.isPending) {
    return (
      <div className="grid h-full place-items-center p-300">
        <LoadingState label="Checking your access" />
      </div>
    );
  }

  if (me.isError) {
    return (
      <div className="grid h-full place-items-center p-300">
        {isSessionRenewal(me.error) ? <SessionRenewal /> : <NoAccess label="PayInt" error={me.error} />}
      </div>
    );
  }

  if (needsAccessRequest(me.data)) {
    return (
      <div className="grid h-full place-items-center p-300">
        <NoAccess label="PayInt" />
      </div>
    );
  }

  return children;
}
