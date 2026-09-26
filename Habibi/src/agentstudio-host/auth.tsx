/* eslint-disable react-refresh/only-export-components -- mirrors the vendor module, which exports its hook beside its provider */
/**
 * `@/lib/auth` for the ported AgentStudio screens.
 *
 * AgentStudio has one login: Habibi's (Entra + RBAC). The screens ask this
 * module who the user is and for a token; the answers come from `/me` and the
 * same credentials every other request uses. Engine-side logins do not exist.
 */
import { useMemo, type ReactNode } from "react";

import { useMe } from "@/api/me";
import { studioAuthHeaders } from "@/api/studio-engine";
import { signOut } from "@/lib/sso";

export interface BaseUser {
  id: string;
  email?: string;
  name?: string;
  image?: string;
}
export interface LocalUser extends BaseUser {
  provider: "local";
  organizationId?: string;
  displayName?: string;
  provider_id?: string;
}
export type AuthUser = LocalUser;
export type AuthProviderType = "local";
export interface AuthToken {
  accessToken: string;
  refreshToken?: string;
  expiresAt?: number;
}
export interface TeamPermission {
  id: string;
}

/**
 * What the screens call "the access token". Requests are signed by the client
 * interceptor, not by this value; screens only use it to decide that a session
 * exists (and to build headers the interceptor then replaces). With an API key
 * instead of Entra (local runs) there is no bearer, so a placeholder stands in.
 */
async function getAccessToken(): Promise<string> {
  const headers = await studioAuthHeaders();
  const bearer = (headers.get("Authorization") ?? "").replace(/^Bearer\s+/i, "");
  if (bearer) return bearer;
  return headers.has("X-API-Key") ? "app-session" : "";
}

function redirectToLogin(): void {
  window.location.assign("/login");
}

function logout(): void {
  void signOut();
}

export function useAuth() {
  const { data: me, isLoading } = useMe();
  const userId = me?.id;
  const userName = me?.name;
  const user: AuthUser | null = useMemo(
    () =>
      userId
        ? {
            id: userId,
            name: userName,
            displayName: userName,
            provider: "local",
            provider_id: userId,
          }
        : null,
    [userId, userName],
  );
  const isAuthenticated = Boolean(me);
  return useMemo(
    () => ({
      user,
      isAuthenticated,
      loading: isLoading,
      getAccessToken,
      redirectToLogin,
      logout,
      // A string, not "local": screens branch on other providers' features.
      provider: "local",
      getSelectedTeam: undefined as (() => unknown) | undefined,
      listPermissions: undefined as
        ((team?: unknown) => Promise<Array<{ id: string }>>) | undefined,
    }),
    [user, isAuthenticated, isLoading],
  );
}

/** Habibi's shell already establishes the session; nothing to provide. */
export function AuthProvider({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
