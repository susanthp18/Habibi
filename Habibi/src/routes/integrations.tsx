import { useMemo, useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { AppShell } from "@/components/shell/AppShell";
import { IntegrationsHeader } from "@/components/integrations/IntegrationsHeader";
import { PipelineBanner } from "@/components/integrations/PipelineBanner";
import { ProviderCard } from "@/components/integrations/ProviderCard";
import { ProviderDrawer } from "@/components/integrations/ProviderDrawer";
import { PoolHealthStrip } from "@/components/integrations/PoolHealthStrip";
import {
  ConnectorsPanel,
  GatewayPanel,
  OurMcpPanel,
  VaultPanel,
  A2aPartnersPanel,
} from "@/components/integrations/McpConsole";
import { LoadingState } from "@/components/ui/loading-state";
import {
  CATEGORY_LIST,
  type Env,
  type Provider,
  type TestLogEntry,
} from "@/data/integrations-seed";
import { useProviderMutations, useProviders } from "@/api/integrations";
import { USE_MOCK } from "@/api/config";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/integrations")({
  head: () => ({
    meta: [
      { title: "Integrations & API Connections — BigBound AI" },
      {
        name: "description",
        content:
          "Manage LLM, STT, TTS, telephony, WhatsApp and core-banking keys that back the Pipecat voice AI stack.",
      },
      { property: "og:title", content: "Integrations & API Connections — BigBound AI" },
      {
        property: "og:description",
        content:
          "Provider health, credentials, usage and Pipecat wiring for the inbound collections bot.",
      },
    ],
  }),
  component: IntegrationsPage,
});

type ConsoleTab = "providers" | "connectors" | "mcp" | "a2a" | "vault" | "gateway";

function IntegrationsPage() {
  const [env, setEnv] = useState<Env>("sandbox");
  const [category, setCategory] = useState<(typeof CATEGORY_LIST)[number]>("All");
  const [consoleTab, setConsoleTab] = useState<ConsoleTab>("providers");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [logs, setLogs] = useState<TestLogEntry[]>([]);
  const [testingIds, setTestingIds] = useState<Set<string>>(new Set());
  const [testingAll, setTestingAll] = useState(false);
  // Mock-only local credential edits. Keyed by environment as well as id —
  // an id-only map leaked a sandbox edit into the production view — and
  // deliberately NOT used for toggle/test results any more: those are server
  // truth and go straight into the query cache, so a refetch can correct them.
  // As an override they shadowed refreshed server data permanently.
  const [localOverrides, setLocalOverrides] = useState<Record<string, Provider>>({});

  const { data: remote = [], isLoading } = useProviders(env);
  const mut = useProviderMutations(env);
  const queryClient = useQueryClient();

  const patchProviderCache = (next: Provider) => {
    queryClient.setQueryData<Provider[]>(["providers", env], (prev) =>
      Array.isArray(prev) ? prev.map((p) => (p.id === next.id ? next : p)) : prev,
    );
  };

  const providers = useMemo(
    () => remote.map((p) => localOverrides[`${env}:${p.id}`] ?? p),
    [remote, localOverrides, env],
  );

  const filtered = useMemo(
    () => providers.filter((p) => category === "All" || p.category === category),
    [providers, category],
  );

  const updateProvider = (p: Provider) => {
    // Live mode: credentials are locked — only allow local mock edits.
    const envCfg = p.perEnv?.[env];
    if (!USE_MOCK && envCfg?.credentialsLocked) {
      toast.message("Secrets are env/ops-managed — enable/disable and health tests only.");
      return;
    }
    setLocalOverrides((prev) => ({ ...prev, [`${env}:${p.id}`]: p }));
  };

  const toggleProvider = (id: string, v: boolean) => {
    mut.setEnabled.mutate(
      { id: id as Provider["id"], enabled: v },
      {
        onSuccess: patchProviderCache,
        onError: (e) => toast.error(e instanceof Error ? e.message : "Toggle failed"),
      },
    );
  };

  const runOne = async (p: Provider) => {
    setTestingIds((prev) => new Set(prev).add(p.id));
    try {
      const entry = await mut.testOne.mutateAsync(p);
      setLogs((prev) => [...prev, entry]);
      // Patch from the server-backed cache row, not a local override snapshot.
      const base =
        queryClient.getQueryData<Provider[]>(["providers", env])?.find((x) => x.id === p.id) ?? p;
      const envCfg = base.perEnv?.[env];
      if (!envCfg) return entry;
      patchProviderCache({
        ...base,
        perEnv: {
          ...base.perEnv,
          [env]: {
            ...envCfg,
            health: entry.ok ? "healthy" : "degraded",
            latencyMs: entry.latencyMs,
          },
        },
      });
      return entry;
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Connection test failed");
      return {
        ok: false,
        latencyMs: 0,
        message: "Test failed",
        providerId: p.id,
        env,
        at: new Date().toISOString(),
        id: `err-${Date.now()}`,
        payload: undefined,
      } satisfies TestLogEntry;
    } finally {
      setTestingIds((prev) => {
        const n = new Set(prev);
        n.delete(p.id);
        return n;
      });
    }
  };

  const testAll = async () => {
    setTestingAll(true);
    try {
      const enabled = providers.filter((p) => p.perEnv?.[env]?.enabled);
      const results = await Promise.all(enabled.map(runOne));
      const ok = results.filter((r) => r.ok).length;
      toast.success(`${ok} of ${enabled.length} healthy in ${env}`);
    } finally {
      setTestingAll(false);
    }
  };

  const selected = providers.find((p) => p.id === selectedId) ?? null;

  const categories = useMemo(() => {
    if (USE_MOCK) return CATEGORY_LIST;
    const present = new Set(providers.map((p) => p.category));
    return ["All" as const, ...CATEGORY_LIST.filter((c) => c !== "All" && present.has(c))];
  }, [providers]);

  return (
    <AppShell>
      <div className="flex h-full min-h-0 flex-col overflow-hidden">
        <div className="shrink-0 border-b border-border bg-surface px-200 py-150">
          <IntegrationsHeader
            env={env}
            onEnv={setEnv}
            onTestAll={testAll}
            testing={testingAll}
            showTestAll={consoleTab === "providers"}
          />
        </div>

        <div className="shrink-0 border-b border-border bg-surface px-200">
          <div className="flex gap-050">
            {(
              [
                ["providers", "Providers"],
                ["connectors", "Connectors"],
                ["mcp", "Our MCP"],
                ["a2a", "A2A partners"],
                ["vault", "Vault"],
                ["gateway", "Gateway"],
              ] as const
            ).map(([key, label]) => (
              <button
                key={key}
                type="button"
                onClick={() => setConsoleTab(key)}
                className={cn(
                  "border-b-2 px-150 py-100 text-body-small",
                  consoleTab === key
                    ? "border-border-brand font-semibold text-text-brand"
                    : "border-transparent text-text-subtle hover:text-text",
                )}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        {!USE_MOCK && consoleTab === "providers" && (
          <div className="shrink-0 border-b border-border bg-background-brand-subtlest/40 px-200 py-075 text-body-small text-text-brand">
            Live stack providers only · secrets resolve from process env / vault (not editable here)
          </div>
        )}

        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="space-y-200 p-200">
            {consoleTab === "connectors" && <ConnectorsPanel />}
            {consoleTab === "mcp" && <OurMcpPanel />}
            {consoleTab === "a2a" && <A2aPartnersPanel />}
            {consoleTab === "vault" && <VaultPanel />}
            {consoleTab === "gateway" && <GatewayPanel />}
            {consoleTab === "providers" &&
              (isLoading && providers.length === 0 ? (
                <div className="flex justify-center py-600">
                  <LoadingState label="Loading integrations" />
                </div>
              ) : (
                <>
                  <PoolHealthStrip />

                  <PipelineBanner env={env} onOpen={setSelectedId} providers={providers} />

                  <div className="flex flex-wrap items-center gap-075">
                    {categories.map((c) => (
                      <button
                        key={c}
                        onClick={() => setCategory(c)}
                        className={cn(
                          "rounded-full border px-150 py-050 text-body-small font-medium transition-colors",
                          category === c
                            ? "border-border-brand bg-background-brand-subtlest text-text-brand"
                            : "border-border bg-surface text-text-subtle hover:border-border-brand/40",
                        )}
                      >
                        {c}
                      </button>
                    ))}
                  </div>

                  <div className="grid grid-cols-1 gap-150 md:grid-cols-2 xl:grid-cols-3">
                    {filtered.map((p) => (
                      <ProviderCard
                        key={p.id}
                        provider={p}
                        env={env}
                        selected={selectedId === p.id}
                        testing={testingIds.has(p.id)}
                        onOpen={() => setSelectedId(p.id)}
                        onTest={() => void runOne(p)}
                        onToggle={(v) => toggleProvider(p.id, v)}
                      />
                    ))}
                  </div>
                </>
              ))}
          </div>
        </div>

        <ProviderDrawer
          provider={selected}
          env={env}
          logs={logs}
          onClose={() => setSelectedId(null)}
          onUpdate={updateProvider}
          onAppendLog={(e) => setLogs((prev) => [...prev, e])}
          onTestLive={(p) => void runOne(p)}
        />
      </div>
    </AppShell>
  );
}
