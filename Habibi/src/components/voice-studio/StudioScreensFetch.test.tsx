// @vitest-environment jsdom
import "@/test/jsdom";

import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const calls = vi.hoisted(() => ({
  tools: vi.fn(),
  telephony: vi.fn(),
  apiKeys: vi.fn(),
  serviceKeys: vi.fn(),
}));
const user = { id: "operator", name: "Operator" };
const getAccessToken = async () => "session";
const redirectToLogin = () => {};
const params = new URLSearchParams();

vi.mock("@/agentstudio-host/auth", () => ({
  useAuth: () => ({ user, loading: false, getAccessToken, redirectToLogin }),
}));
vi.mock("@/agentstudio-host/shims/next-navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  useSearchParams: () => params,
}));
vi.mock("@/agentstudio-host/shims/next-link", () => ({
  default: ({ children }: { children: React.ReactNode }) => <a href="/studio">{children}</a>,
}));
vi.mock("@/agentstudio/client/sdk.gen", () => ({
  listToolsApiV1ToolsGet: calls.tools,
  listTelephonyConfigurationsApiV1OrganizationsTelephonyConfigsGet: calls.telephony,
  getApiKeysApiV1UserApiKeysGet: calls.apiKeys,
  getServiceKeysApiV1UserServiceKeysGet: calls.serviceKeys,
}));
vi.mock("@/agentstudio/context/TelephonyConfigWarningsContext", () => ({
  useTelephonyConfigWarnings: () => ({
    telnyxMissingWebhookPublicKeyCount: 0,
    vonageMissingSignatureSecretCount: 0,
    refresh: vi.fn(),
  }),
}));
vi.mock("@/agentstudio/components/telephony/ConfigFormDialog", () => ({
  ConfigFormDialog: () => null,
}));
vi.mock("@/agentstudio/components/http", () => ({ CredentialSelector: () => null }));
vi.mock("@/agentstudio-host/app-config", () => ({
  useAppConfig: () => ({ config: { deploymentMode: "oss" } }),
}));
vi.mock("@/agentstudio/hooks/useOrganizationTimezone", () => ({
  useOrganizationTimezone: () => "Asia/Kolkata",
}));
vi.mock("@/agentstudio-host/whitelabel", () => ({ WHITELABEL: false }));

const { default: ToolsPage } = await import("@/agentstudio/app/tools/page");
const { default: TelephonyPage } = await import("@/agentstudio/app/telephony-configurations/page");
const { default: DevelopersPage } = await import("@/agentstudio/app/api-keys/page");

describe("Voice Studio list screens", () => {
  beforeEach(() => {
    calls.tools.mockReset().mockResolvedValue({ data: [] });
    calls.telephony.mockReset().mockResolvedValue({ data: { configurations: [] } });
    calls.apiKeys.mockReset().mockResolvedValue({ data: [] });
    calls.serviceKeys.mockReset().mockResolvedValue({ data: [] });
  });

  it("fetches Tools once on mount and not again on a rerender", async () => {
    const page = render(<ToolsPage />);
    await waitFor(() => expect(calls.tools).toHaveBeenCalledTimes(1));
    page.rerender(<ToolsPage />);
    expect(calls.tools).toHaveBeenCalledTimes(1);
  });

  it("fetches Telephony once and shows a failed refresh", async () => {
    calls.telephony.mockResolvedValue({ error: { detail: "Provider unavailable" } });
    const page = render(<TelephonyPage />);
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("Provider unavailable"),
    );
    page.rerender(<TelephonyPage />);
    expect(calls.telephony).toHaveBeenCalledTimes(1);
  });

  it("fetches both Developers key lists once", async () => {
    const page = render(<DevelopersPage />);
    await waitFor(() => {
      expect(calls.apiKeys).toHaveBeenCalledTimes(1);
      expect(calls.serviceKeys).toHaveBeenCalledTimes(1);
    });
    page.rerender(<DevelopersPage />);
    expect(calls.apiKeys).toHaveBeenCalledTimes(1);
    expect(calls.serviceKeys).toHaveBeenCalledTimes(1);
  });
});
