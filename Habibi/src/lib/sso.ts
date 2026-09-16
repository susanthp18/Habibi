/**
 * Operator SSO. Entra owns the password; this module is the only MSAL owner.
 */
import {
  InteractionRequiredAuthError,
  PublicClientApplication,
  type AccountInfo,
  type RedirectRequest,
} from "@azure/msal-browser";

function clientId(): string {
  return (import.meta.env.VITE_ENTRA_CLIENT_ID as string | undefined)?.trim() ?? "";
}

function tenantId(): string {
  return (import.meta.env.VITE_ENTRA_TENANT_ID as string | undefined)?.trim() ?? "";
}

function apiScope(): string {
  return (import.meta.env.VITE_ENTRA_API_SCOPE as string | undefined)?.trim() ?? "";
}

export function entraVarsPresent(client: string, tenant: string, scope: string): boolean {
  return Boolean(client.trim() && tenant.trim() && scope.trim());
}

export function entraConfigured(): boolean {
  return entraVarsPresent(clientId(), tenantId(), apiScope());
}

/** Entra allows http://localhost, not http://127.0.0.1, as a SPA redirect. */
export function entraLoopbackOrigin(origin: string): string {
  try {
    const url = new URL(origin);
    if (url.hostname === "127.0.0.1") url.hostname = "localhost";
    return url.origin;
  } catch {
    return origin;
  }
}

export function bounceOffLoopbackIp(): boolean {
  if (typeof window === "undefined") return false;
  if (window.location.hostname !== "127.0.0.1") return false;
  const next = new URL(window.location.href);
  next.hostname = "localhost";
  window.location.replace(next.href);
  return true;
}

export function loginRedirectUri(origin?: string): string {
  const base = import.meta.env.BASE_URL || "/";
  const prefix = base.endsWith("/") ? base : `${base}/`;
  const here = entraLoopbackOrigin(origin ?? window.location.origin);
  return new URL("login", `${here}${prefix}`).href;
}

export function logoutRedirectUri(origin?: string): string {
  const here = entraLoopbackOrigin(origin ?? window.location.origin);
  return `${here}/`;
}

let pcaPromise: Promise<PublicClientApplication> | null = null;
let activeAccount: AccountInfo | null = null;

function rememberAccount(pca: PublicClientApplication, account?: AccountInfo | null) {
  const next = account ?? pca.getActiveAccount() ?? pca.getAllAccounts()[0] ?? null;
  if (next) pca.setActiveAccount(next);
  activeAccount = next;
}

export async function getMsal(): Promise<PublicClientApplication | null> {
  if (typeof window === "undefined") return null;
  if (!entraConfigured()) return null;
  pcaPromise ??= (async () => {
    const pca = new PublicClientApplication({
      auth: {
        clientId: clientId(),
        authority: `https://login.microsoftonline.com/${tenantId()}`,
        redirectUri: loginRedirectUri(),
        postLogoutRedirectUri: logoutRedirectUri(),
      },
      cache: { cacheLocation: "sessionStorage" },
    });
    await pca.initialize();
    const result = await pca.handleRedirectPromise();
    rememberAccount(pca, result?.account);
    return pca;
  })();
  return pcaPromise;
}

export async function completeRedirect(): Promise<AccountInfo | null> {
  const pca = await getMsal();
  if (!pca) return null;
  rememberAccount(pca);
  return activeAccount;
}

function tokenRequest(account: AccountInfo): RedirectRequest {
  return { account, scopes: [apiScope()] };
}

let tokenCache: { value: string; expiresAt: number } | null = null;

export async function getAccessToken(): Promise<string | null> {
  const pca = await getMsal();
  if (!pca) return null;
  rememberAccount(pca);
  if (!activeAccount) return null;
  const now = Date.now();
  if (tokenCache && tokenCache.expiresAt - 60_000 > now) return tokenCache.value;
  try {
    const silent = await pca.acquireTokenSilent(tokenRequest(activeAccount));
    tokenCache = {
      value: silent.accessToken,
      expiresAt: silent.expiresOn?.getTime() ?? now + 5 * 60_000,
    };
    return silent.accessToken;
  } catch (err) {
    tokenCache = null;
    if (err instanceof InteractionRequiredAuthError) {
      await pca.acquireTokenRedirect(tokenRequest(activeAccount));
      return null;
    }
    throw err;
  }
}

export function entraDisplayName(): string {
  return entraAccountName(activeAccount);
}

export function entraAccountName(account: AccountInfo | null | undefined): string {
  if (!account) return "";
  const claims = account.idTokenClaims;
  const name = typeof claims?.name === "string" ? claims.name : "";
  return name || account.name || "";
}

export async function signInWithMicrosoft(): Promise<{ ok: true } | { ok: false; reason: string }> {
  if (!entraConfigured()) {
    return {
      ok: false,
      reason: "Microsoft sign-in is not connected yet. The app registration lands next.",
    };
  }
  const pca = await getMsal();
  if (!pca) {
    return { ok: false, reason: "Microsoft sign-in could not start in this browser." };
  }
  await pca.loginRedirect({ scopes: [apiScope()] });
  return { ok: true };
}

export async function signOut(): Promise<void> {
  tokenCache = null;
  const pca = await getMsal();
  activeAccount = null;
  if (!pca) {
    window.location.assign("/");
    return;
  }
  await pca.logoutRedirect({ postLogoutRedirectUri: logoutRedirectUri() });
}
