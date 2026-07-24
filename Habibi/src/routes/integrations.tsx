import { useMemo, useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { toast } from "sonner";
import { AppShell } from "@/components/shell/AppShell";
import { IntegrationsHeader } from "@/components/integrations/IntegrationsHeader";
import { PipelineBanner } from "@/components/integrations/PipelineBanner";
import { ProviderCard } from "@/components/integrations/ProviderCard";
import { ProviderDrawer } from "@/components/integrations/ProviderDrawer";
import { Skeleton } from "@/components/ui/skeleton";
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
      { name: "description", content: "Manage LLM, STT, TTS, telephony, WhatsApp and core-banking keys that back the Pipecat voice AI stack." },
      { property: "og:title", content: "Integrations & API Connections — BigBound AI" },
      { property: "og:description", content: "Provider health, credentials, usage and Pipecat wiring for the inbound collections bot." },
    ],
  }),
  component: IntegrationsPage,
});

function IntegrationsPage() {
  const [env, setEnv] = useState<Env>("sandbox");
  const [category, setCategory] = useState<(typeof CATEGORY_LIST)[number]>("All");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [logs, setLogs] = useState<TestLogEntry[]>([]);
  const [testingIds, setTestingIds] = useState<Set<string>>(new Set());
  const [testingAll, setTestingAll] = useState(false);
  const [localOverrides, setLocalOverrides] = useState<Record<string, Provider>>({});

  const { data: remote = [], isLoading } = useProviders(env);
  const mut = useProviderMutations(env);

  const providers = useMemo(
    () => remote.map((p) => localOverrides[p.id] ?? p),
    [remote, localOverrides],
  );

  const filtered = useMemo(
    () => providers.filter((p) => category === "All" || p.category === category),
    [providers, category],
  );

  const updateProvider = (p: Provider) => {
    // Live mode: credentials are locked — only allow local mock edits.
    if (!USE_MOCK && p.perEnv[env].credentialsLocked) {
      toast.message("Secrets are env/ops-managed — enable/disable and health tests only.");
      return;
    }
    setLocalOverrides((prev) => ({ ...prev, [p.id]: p }));
  };

  const toggleProvider = (id: string, v: boolean) => {
    mut.setEnabled.mutate(
      { id: id as Provider["id"], enabled: v },
      {
        onSuccess: (p) => setLocalOverrides((prev) => ({ ...prev, [p.id]: p })),
        onError: (e) => toast.error(e instanceof Error ? e.message : "Toggle failed"),
      },
    );
  };

  const runOne = async (p: Provider) => {
    setTestingIds((prev) => new Set(prev).add(p.id));
    try {
      const entry = await mut.testOne.mutateAsync(p);
      setLogs((prev) => [...prev, entry]);
      setLocalOverrides((prev) => ({
        ...prev,
        [p.id]: {
          ...p,
          perEnv: {
            ...p.perEnv,
            [env]: {
              ...p.perEnv[env],
              health: entry.ok ? "healthy" : "degraded",
              latencyMs: entry.latencyMs,
            },
          },
        },
      }));
      return entry;
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
    const enabled = providers.filter((p) => p.perEnv[env].enabled);
    const results = await Promise.all(enabled.map(runOne));
    const ok = results.filter((r) => r.ok).length;
    setTestingAll(false);
    toast.success(`${ok} of ${enabled.length} healthy in ${env}`);
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
        <div className="shrink-0 border-b border-[var(--border-token)] bg-surface-card px-4 py-3">
          <IntegrationsHeader env={env} onEnv={setEnv} onTestAll={testAll} testing={testingAll} />
        </div>

        {!USE_MOCK && (
          <div className="shrink-0 border-b border-[var(--border-token)] bg-brand-tint/40 px-4 py-1.5 text-[11px] text-brand-primary-dark">
            Live stack providers only · secrets resolve from process env / vault (not editable here)
          </div>
        )}

        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="space-y-4 p-4">
            {isLoading && providers.length === 0 ? (
              <Skeleton className="h-40 w-full" />
            ) : (
              <>
                <PipelineBanner env={env} onOpen={setSelectedId} providers={providers} />

                <div className="flex flex-wrap items-center gap-1.5">
                  {categories.map((c) => (
                    <button
                      key={c}
                      onClick={() => setCategory(c)}
                      className={cn(
                        "rounded-full border px-2.5 py-1 text-[11px] font-medium transition-colors",
                        category === c
                          ? "border-brand-primary bg-brand-tint text-brand-primary-dark"
                          : "border-[var(--border-token)] bg-white text-text-secondary hover:border-brand-primary/40",
                      )}
                    >
                      {c}
                    </button>
                  ))}
                </div>

                <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
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
            )}
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
