// -----------------------------------------------------------------------------
// The acting user — one identity for the whole app.
//
// The shell used to render a hardcoded "Priya Shah · Team Delta" while the
// backend recorded every write against `priya-nair` ("Priya Nair"). Two
// identities that disagree make the audit trail lie, so both now come from
// GET /me. Entra authenticates; this payload is who PayInt will authorize.
// -----------------------------------------------------------------------------

import { useQuery } from "@tanstack/react-query";

import { isSessionRenewal } from "@/lib/sso";

import { apiGet, retryUnlessClientError } from "./config";

export interface Me {
  id: string;
  name: string;
  kind: "human" | "bot";
  team: string | null;
  status: string | null;
  tenantId: string;
  /** Effective permission ids (authz catalog), from the actor's roles. */
  permissions: string[];
}

/** Whether the acting user holds a permission; unknown (not loaded) reads as false. */
export function can(me: Me | undefined, permission: string): boolean {
  return Boolean(me?.permissions?.includes(permission));
}

/** Signed in, but PayInt has not granted a role (or the account is parked). */
export function needsAccessRequest(me: Me | undefined): boolean {
  if (!me) return false;
  if ((me.status || "").toLowerCase() === "inactive") return true;
  return (me.permissions?.length ?? 0) === 0;
}

export async function fetchMe(): Promise<Me> {
  return apiGet<Me>("/me");
}

export function useMe() {
  return useQuery({
    queryKey: ["me"],
    queryFn: fetchMe,
    staleTime: 5 * 60_000,
    // A failed Microsoft renewal does not start succeeding on the third try.
    // Retrying it is what held "Checking your access" for the length of
    // several timeouts.
    retry: (failureCount, error) =>
      !isSessionRenewal(error) && retryUnlessClientError(failureCount, error),
  });
}

let meCache: Promise<Me> | null = null;

/** For non-hook callers (mutations, defaults). */
export function currentActor(): Promise<Me> {
  if (!meCache) {
    meCache = fetchMe().catch((err) => {
      meCache = null;
      throw err;
    });
  }
  return meCache;
}
