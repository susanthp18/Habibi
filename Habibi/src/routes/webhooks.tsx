import { useMemo, useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { toast } from "sonner";
import { AppShell } from "@/components/shell/AppShell";
import { WebhooksHeader } from "@/components/webhooks/WebhooksHeader";
import { WebhooksStats } from "@/components/webhooks/WebhooksStats";
import { EndpointTable } from "@/components/webhooks/EndpointTable";
import { EndpointSheet } from "@/components/webhooks/EndpointSheet";
import { EndpointDrawer } from "@/components/webhooks/EndpointDrawer";
import { EventCatalogDialog } from "@/components/webhooks/EventCatalogDialog";
import { DeliveryLogPane } from "@/components/webhooks/DeliveryLogPane";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Pause, Play, KeyRound, Trash2 } from "lucide-react";
import {
  useWebhookDeliveries,
  useWebhookEndpoints,
  useWebhookMutations,
  type WebhookDraft,
} from "@/api/webhooks";
import { USE_MOCK } from "@/api/config";
import type { Endpoint } from "@/data/webhooks-seed";

export const Route = createFileRoute("/webhooks")({
  head: () => ({
    meta: [
      { title: "Webhooks & Event Subscriptions — BigBound AI" },
      { name: "description", content: "Register downstream endpoints, subscribe them to CRM events, and monitor delivery, retries and signing." },
      { property: "og:title", content: "Webhooks & Event Subscriptions — BigBound AI" },
      { property: "og:description", content: "How the Pipecat backend and the client's legacy banking systems stay in sync with the bot." },
    ],
  }),
  component: WebhooksPage,
});

function WebhooksPage() {
  const { data: endpoints = [], isLoading: loadingEp } = useWebhookEndpoints();
  const { data: deliveries = [], isLoading: loadingDlv } = useWebhookDeliveries();
  const mut = useWebhookMutations();

  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [activeId, setActiveId] = useState<string | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [editing, setEditing] = useState<Endpoint | null>(null);
  const [catalogOpen, setCatalogOpen] = useState(false);

  const activeEndpoint = useMemo(
    () => endpoints.find((e) => e.id === activeId) ?? null,
    [endpoints, activeId],
  );

  const updateEndpoint = (ep: Endpoint) => {
    mut.update.mutate(ep, {
      onSuccess: () => toast.success(`Saved ${ep.name}`),
      onError: (e) => toast.error(e instanceof Error ? e.message : "Save failed"),
    });
  };

  const deleteEndpoint = (ep: Endpoint) => {
    mut.remove.mutate(ep, {
      onSuccess: () => {
        if (activeId === ep.id) setDrawerOpen(false);
        setSelectedIds((prev) => {
          const next = new Set(prev);
          next.delete(ep.id);
          return next;
        });
        toast.success(`Deleted ${ep.name}`);
      },
      onError: (e) => toast.error(e instanceof Error ? e.message : "Delete failed"),
    });
  };

  const rotateOne = (ep: Endpoint) => {
    mut.rotate.mutate(ep, {
      onSuccess: (res) => {
        toast.success(`Rotated secret for ${ep.name}`, {
          description: res.secretOnce
            ? `Copy now: ${res.secretOnce.slice(0, 12)}… (shown once)`
            : "Redeploy the receiver with the new secret.",
        });
      },
      onError: (e) => toast.error(e instanceof Error ? e.message : "Rotate failed"),
    });
  };

  const testFire = (ep: Endpoint) => {
    mut.testFire.mutate(
      { ep },
      {
        onSuccess: (d) => {
          if (d.status === "success") toast.success(`${ep.name} → ${d.httpStatus} · ${d.latencyMs}ms`);
          else toast.error(`${ep.name} → ${d.httpStatus} · ${d.latencyMs}ms`);
        },
        onError: (e) => toast.error(e instanceof Error ? e.message : "Test failed"),
      },
    );
  };

  const togglePause = (ep: Endpoint) => {
    const next: Endpoint = { ...ep, status: ep.status === "paused" ? "active" : "paused" };
    updateEndpoint(next);
  };

  const openDrawer = (id: string) => {
    setActiveId(id);
    setDrawerOpen(true);
  };

  const openNew = () => {
    setEditing(null);
    setSheetOpen(true);
  };

  const openEdit = (ep: Endpoint) => {
    setEditing(ep);
    setSheetOpen(true);
  };

  const handleSaveDraft = (draft: WebhookDraft, andTest = false) => {
    if (editing) {
      const merged: Endpoint = { ...editing, ...draft } as Endpoint;
      mut.update.mutate(merged, {
        onSuccess: () => {
          toast.success(`Saved ${merged.name}`);
          setSheetOpen(false);
          if (andTest) testFire(merged);
        },
        onError: (e) => toast.error(e instanceof Error ? e.message : "Save failed"),
      });
    } else {
      mut.create.mutate(draft, {
        onSuccess: (created) => {
          toast.success(`Created ${created.name}`, {
            description: created.secretOnce
              ? `Signing secret (once): ${created.secretOnce.slice(0, 16)}…`
              : undefined,
          });
          setSheetOpen(false);
          if (andTest) testFire(created);
        },
        onError: (e) => toast.error(e instanceof Error ? e.message : "Create failed"),
      });
    }
  };

  const retryDelivery = (d: (typeof deliveries)[number]) => {
    mut.retry.mutate(d, {
      onSuccess: (next) => {
        if (next.status === "success") toast.success(`Retry succeeded · ${next.httpStatus}`);
        else toast.error(`Retry failed · ${next.httpStatus}`);
      },
      onError: (e) => toast.error(e instanceof Error ? e.message : "Retry failed"),
    });
  };

  const selectedEndpoints = endpoints.filter((e) => selectedIds.has(e.id));

  const bulkPause = (pause: boolean) => {
    selectedEndpoints.forEach((ep) =>
      updateEndpoint({ ...ep, status: pause ? "paused" : "active" }),
    );
    toast.info(`${selectedEndpoints.length} endpoint(s) ${pause ? "paused" : "resumed"}`);
  };
  const bulkRotate = () => selectedEndpoints.forEach(rotateOne);
  const bulkDelete = () => {
    selectedEndpoints.forEach(deleteEndpoint);
    setSelectedIds(new Set());
  };
  const rotateAll = () => endpoints.forEach(rotateOne);

  if (loadingEp && endpoints.length === 0) {
    return (
      <AppShell>
        <div className="p-6"><Skeleton className="h-48 w-full" /></div>
      </AppShell>
    );
  }

  return (
    <AppShell>
      <div className="flex h-full min-h-0 flex-col">
        {!USE_MOCK && (
          <div className="shrink-0 border-b border-[var(--border-token)] bg-brand-tint/40 px-6 py-1.5 text-[11px] text-brand-primary-dark">
            Live webhooks · test-fire is simulated (no real egress). Secrets returned once on create/rotate.
          </div>
        )}
        <WebhooksHeader
          onNew={openNew}
          onCatalog={() => setCatalogOpen(true)}
          onRotateAll={rotateAll}
        />
        <WebhooksStats endpoints={endpoints} deliveries={deliveries} />

        {selectedIds.size > 0 && (
          <div className="flex shrink-0 items-center gap-2 border-b border-[var(--border-token)] bg-brand-tint/60 px-6 py-2 text-[12px]">
            <span className="font-semibold text-brand-primary-dark">
              {selectedIds.size} selected
            </span>
            <div className="ml-auto flex gap-2">
              <Button size="sm" variant="outline" onClick={() => bulkPause(true)}>
                <Pause className="mr-1 h-3.5 w-3.5" /> Pause
              </Button>
              <Button size="sm" variant="outline" onClick={() => bulkPause(false)}>
                <Play className="mr-1 h-3.5 w-3.5" /> Resume
              </Button>
              <Button size="sm" variant="outline" onClick={bulkRotate}>
                <KeyRound className="mr-1 h-3.5 w-3.5" /> Rotate
              </Button>
              <Button
                size="sm"
                variant="outline"
                className="text-rose-600 hover:text-rose-700"
                onClick={bulkDelete}
              >
                <Trash2 className="mr-1 h-3.5 w-3.5" /> Delete
              </Button>
            </div>
          </div>
        )}

        <div className="flex min-h-0 flex-[3] flex-col">
          <EndpointTable
            endpoints={endpoints}
            deliveries={deliveries}
            selectedIds={selectedIds}
            activeId={activeId}
            onToggleSelect={(id) =>
              setSelectedIds((prev) => {
                const next = new Set(prev);
                if (next.has(id)) next.delete(id);
                else next.add(id);
                return next;
              })
            }
            onToggleAll={(v) => setSelectedIds(v ? new Set(endpoints.map((e) => e.id)) : new Set())}
            onRowClick={openDrawer}
            onEdit={openEdit}
            onTestFire={testFire}
            onTogglePause={togglePause}
            onRotate={rotateOne}
            onDelete={deleteEndpoint}
          />
        </div>

        <div className="flex min-h-[240px] flex-[2] flex-col">
          {loadingDlv && deliveries.length === 0 ? (
            <Skeleton className="m-4 h-32" />
          ) : (
            <DeliveryLogPane
              endpoints={endpoints}
              deliveries={deliveries}
              onRetry={retryDelivery}
            />
          )}
        </div>
      </div>

      <EndpointSheet
        open={sheetOpen}
        onOpenChange={setSheetOpen}
        initial={editing}
        onSave={(d) => handleSaveDraft(d, false)}
        onSaveAndTest={(d) => handleSaveDraft(d, true)}
      />

      <EndpointDrawer
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
        endpoint={activeEndpoint}
        deliveries={deliveries}
        onUpdate={updateEndpoint}
        onDelete={(ep) => {
          deleteEndpoint(ep);
          setDrawerOpen(false);
        }}
        onAppendDelivery={() => {
          /* live path invalidates via mutations */
        }}
        onRotate={rotateOne}
        onRetry={retryDelivery}
        onTestFire={(ep, event) =>
          mut.testFire.mutate(
            { ep, event },
            {
              onSuccess: (d) => {
                if (d.status === "success") toast.success(`Test → ${d.httpStatus} · ${d.latencyMs}ms`);
                else toast.error(`Test → ${d.httpStatus} · ${d.latencyMs}ms`);
              },
              onError: (e) => toast.error(e instanceof Error ? e.message : "Test failed"),
            },
          )
        }
      />

      <EventCatalogDialog open={catalogOpen} onOpenChange={setCatalogOpen} />
    </AppShell>
  );
}
