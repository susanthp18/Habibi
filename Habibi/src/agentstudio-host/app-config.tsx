/* eslint-disable react-refresh/only-export-components -- mirrors the vendor module, which exports its hook beside its provider */
/**
 * `@/context/AppConfigContext` for the ported screens. The vendor UI read this
 * through a Next.js server route; here it is the engine's /health, fetched
 * through the gateway. TURN flags drive the live test-call page.
 */
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

import { client } from "@/agentstudio/client/client.gen";
import { STUDIO_API_BASE } from "@/api/studio-engine";

type BackendStatus = "reachable" | "unreachable";

export interface AppConfig {
  uiVersion: string;
  apiVersion: string;
  deploymentMode: string;
  authProvider: string;
  turnEnabled: boolean;
  forceTurnRelay: boolean;
  tunnelUrl: string | null;
  backendApiEndpoint: string | null;
  backendStatus: BackendStatus;
  backendUrl: string;
  backendMessage: string | null;
}

interface AppConfigContextType {
  config: AppConfig | null;
  loading: boolean;
  refresh: () => Promise<void>;
}

const unreachable: AppConfig = {
  uiVersion: "agentstudio",
  apiVersion: "unavailable",
  deploymentMode: "oss",
  authProvider: "internal",
  turnEnabled: false,
  forceTurnRelay: false,
  tunnelUrl: null,
  backendApiEndpoint: null,
  backendStatus: "unreachable",
  backendUrl: STUDIO_API_BASE,
  backendMessage: "Voice Studio is not reachable right now.",
};

const AppConfigContext = createContext<AppConfigContextType>({
  config: null,
  loading: true,
  refresh: async () => {},
});

interface Health {
  version?: string;
  deployment_mode?: string;
  auth_provider?: string;
  turn_enabled?: boolean;
  force_turn_relay?: boolean;
  tunnel_url?: string | null;
  backend_api_endpoint?: string | null;
}

export function AppConfigProvider({ children }: { children: ReactNode }) {
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data, error } = await client.get<Health, unknown, false>({ url: "/api/v1/health" });
      if (error || !data) throw new Error("Voice Studio health check failed");
      setConfig({
        uiVersion: "agentstudio",
        apiVersion: data.version ?? "unknown",
        deploymentMode: data.deployment_mode ?? "oss",
        authProvider: data.auth_provider ?? "internal",
        turnEnabled: Boolean(data.turn_enabled),
        forceTurnRelay: Boolean(data.force_turn_relay),
        tunnelUrl: data.tunnel_url ?? null,
        backendApiEndpoint: data.backend_api_endpoint ?? null,
        backendStatus: "reachable",
        backendUrl: STUDIO_API_BASE,
        backendMessage: null,
      });
    } catch {
      setConfig(unreachable);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <AppConfigContext.Provider value={{ config, loading, refresh: load }}>
      {children}
    </AppConfigContext.Provider>
  );
}

export function useAppConfig() {
  return useContext(AppConfigContext);
}
