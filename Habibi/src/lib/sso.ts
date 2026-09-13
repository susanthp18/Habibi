/**
 * Operator SSO. Entra owns the password; this module only starts the MSAL
 * redirect. Until the app registration exists, the login page still renders
 * and the button reports that the IdP is not wired.
 */

export function entraConfigured(): boolean {
  const id = (import.meta.env.VITE_ENTRA_CLIENT_ID as string | undefined)?.trim();
  const tenant = (import.meta.env.VITE_ENTRA_TENANT_ID as string | undefined)?.trim();
  return Boolean(id && tenant);
}

export function signInWithMicrosoft(): { ok: true } | { ok: false; reason: string } {
  if (!entraConfigured()) {
    return {
      ok: false,
      reason: "Microsoft sign-in is not connected yet. The app registration lands next.",
    };
  }
  // MSAL redirect is wired in the Entra package. This file stays the only call site.
  return {
    ok: false,
    reason: "Microsoft sign-in is configured but is not ready yet.",
  };
}
