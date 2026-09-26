import { describe, expect, it } from "vitest";

import {
  SessionRenewalNeeded,
  entraAccountName,
  entraVarsPresent,
  isSessionRenewal,
  loginRedirectUri,
  logoutRedirectUri,
} from "./sso";

describe("entraVarsPresent", () => {
  it("is false when any of client, tenant, or scope is blank", () => {
    expect(entraVarsPresent("", "tid", "scope")).toBe(false);
    expect(entraVarsPresent("cid", "", "scope")).toBe(false);
    expect(entraVarsPresent("cid", "tid", "")).toBe(false);
  });

  it("is true only when all three are set", () => {
    expect(entraVarsPresent("cid", "tid", "api://app/access_as_user")).toBe(true);
  });
});

describe("redirect URIs", () => {
  it("sends unauthenticated operators to /login on this origin", () => {
    expect(loginRedirectUri("http://localhost:8080")).toBe("http://localhost:8080/login");
  });

  it("rewrites http://127.0.0.1 to localhost because Entra SPA forbids that loopback IP", () => {
    expect(loginRedirectUri("http://127.0.0.1:8080")).toBe("http://localhost:8080/login");
  });

  it("returns Sign out to the landing origin", () => {
    expect(logoutRedirectUri("http://localhost:8080")).toBe("http://localhost:8080/");
  });
});

describe("isSessionRenewal", () => {
  it("is only the Microsoft session failure, not a missing role", () => {
    expect(isSessionRenewal(new SessionRenewalNeeded())).toBe(true);
    expect(isSessionRenewal(new Error("forbidden"))).toBe(false);
  });
});

describe("entraAccountName", () => {
  it("prefers the ID-token name over the account display name", () => {
    expect(
      entraAccountName({
        name: "Mailbox",
        idTokenClaims: { name: "Susanth P" },
      } as never),
    ).toBe("Susanth P");
  });
});
