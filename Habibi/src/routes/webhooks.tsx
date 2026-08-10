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
import type { Endpoint, EventKey } from "@/data/webhooks-seed";

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

  const revealSecretOnce = (name: string, secretOnce: string | null | undefined) => {
    if (!secretOnce) {
      toast.success(`Rotated secret for ${name}`, {
        description: "Redeploy the receiver with the new secret.",
      });
      return;
    }
    toast.success(`Rotated secret for ${name}`, {
      description: secretOnce,
      duration: 60_000,
      action: {
        label: "Copy",
        onClick: () => {
          void navigator.clipboard?.writeText(secretOnce);
        },
      },
    });
  };

  const rotateOne = (ep: Endpoint) => {
    mut.rotate.mutate(ep, {
      onSuccess: (res) => revealSecretOnce(ep.name, res.secretOnce),
      onError: (e) => toast.error(e instanceof Error ? e.message : "Rotate failed"),
    });
  };

  const testFire = async (ep: Endpoint, event?: EventKey) => {
    const d = await mut.testFire.mutateAsync(
      event ? { ep, event } : { ep },
    );
    if (d.status === "success") toast.success(`${ep.name} → ${d.httpStatus} · ${d.latencyMs}ms`);
    else toast.error(`${ep.name} → ${d.httpStatus} · ${d.latencyMs}ms`);
    return d;
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
          if (andTest) void testFire(merged).catch((e) => toast.error(e instanceof Error ? e.message : "Test failed"));
        },
        onError: (e) => toast.error(e instanceof Error ? e.message : "Save failed"),
      });
    } else {
      mut.create.mutate(draft, {
        onSuccess: (created) => {
          toast.success(`Created ${created.name}`, {
            description: created.secretOnce ?? undefined,
            duration: created.secretOnce ? 60_000 : undefined,
            action: created.secretOnce
              ? {
                  label: "Copy",
                  onClick: () => {
                    void navigator.clipboard?.writeText(created.secretOnce!);
                  },
                }
              : undefined,
          });
          setSheetOpen(false);
          if (andTest) void testFire(created).catch((e) => toast.error(e instanceof Error ? e.message : "Test failed"));
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
    void runSequential(
      pause ? "Paused" : "Resumed",
      selectedEndpoints,
      (ep) => mut.update.mutateAsync({ ...ep, status: pause ? "paused" : "active" }),
    );
  };
  // Bulk actions run one at a time and report a summary. forEach fired N
  // concurrent mutations with no ceiling, and the two destructive ones — a
  // rotate breaks every receiver until it is redeployed, a delete is
  // unrecoverable — had no confirmation at all. bulkDelete also cleared the
  // selection before any request had come back, so a partial failure left the
  // user with no idea which endpoints survived.
  const [bulkBusy, setBulkBusy] = useState(false);

  const runSequential = async (
    label: string,
    targets: Endpoint[],
    run: (ep: Endpoint) => Promise<unknown>,
  ) => {
    if (!targets.length || bulkBusy) return [];
    setBulkBusy(true);
    const failed: string[] = [];
    try {
      for (const ep of targets) {
        try {
          await run(ep);
        } catch {
          failed.push(ep.name);
        }
      }
    } finally {
      setBulkBusy(false);
    }
    if (failed.length) {
      toast.error(
        `${label}: ${targets.length - failed.length}/${targets.length} succeeded — failed: ${failed.join(", ")}`,
      );
    } else {
      toast.success(`${label}: ${targets.length} endpoint(s)`);
    }
    return failed;
  };

  const confirmRotate = (count: number) =>
    window.confirm(
      `Rotate the signing secret for ${count} endpoint(s)? Each receiver stops verifying deliveries until it is redeployed with the new secret.`,
    );

  const rotateSequential = async (ep: Endpoint) => {
    const res = await mut.rotate.mutateAsync(ep);
    revealSecretOnce(ep.name, res.secretOnce);
  };

  const bulkRotate = () => {
    if (!confirmRotate(selectedEndpoints.length)) return;
    void runSequential("Rotated", selectedEndpoints, rotateSequential);
  };

  const bulkDelete = () => {
    if (
      !window.confirm(
        `Delete ${selectedEndpoints.length} endpoint(s)? This cannot be undone.`,
      )
    )
      return;
    const ids = selectedEndpoints.map((e) => e.id);
    void runSequential("Deleted", selectedEndpoints, (ep) => mut.remove.mutateAsync(ep)).then(
      () => {
        if (activeId && ids.includes(activeId)) setDrawerOpen(false);
        setSelectedIds(new Set());
      },
    );
  };

  const rotateAll = () => {
    if (!confirmRotate(endpoints.length)) return;
    void runSequential("Rotated", endpoints, rotateSequential);
  };

  if (loadingEp && endpoints.length === 0) {
    return (
      <AppShell>
        <div className="p-300"><Skeleton className="h-48 w-full" /></div>
      </AppShell>
    );
  }

  return (
    <AppShell>
      <div className="flex h-full min-h-0 flex-col">
        {!USE_MOCK && (
          <div className="shrink-0 border-b border-border bg-background-brand-subtlest/40 px-300 py-075 text-body-small text-text-brand">
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
          <div className="flex shrink-0 items-center gap-100 border-b border-border bg-background-brand-subtlest/60 px-300 py-100 text-body-small">
            <span className="font-semibold text-text-brand">
              {selectedIds.size} selected
            </span>
            <div className="ml-auto flex gap-100">
              <Button size="sm" variant="outline" onClick={() => bulkPause(true)}>
                <Pause className="mr-050 h-3.5 w-3.5" /> Pause
              </Button>
              <Button size="sm" variant="outline" onClick={() => bulkPause(false)}>
                <Play className="mr-050 h-3.5 w-3.5" /> Resume
              </Button>
              <Button size="sm" variant="outline" onClick={bulkRotate}>
                <KeyRound className="mr-050 h-3.5 w-3.5" /> Rotate
              </Button>
              <Button
                size="sm"
                variant="outline"
                className="text-text-danger hover:text-text-danger-bolder"
                onClick={bulkDelete}
              >
                <Trash2 className="mr-050 h-3.5 w-3.5" /> Delete
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

        <div className="flex min-h-[15rem] flex-[2] flex-col">
          {loadingDlv && deliveries.length === 0 ? (
            <Skeleton className="m-200 h-32" />
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
        onTestFire={async (ep, event) => {
          try {
            await testFire(ep, event);
          } catch (e) {
            toast.error(e instanceof Error ? e.message : "Test failed");
            throw e;
          }
        }}
      />

      <EventCatalogDialog open={catalogOpen} onOpenChange={setCatalogOpen} />
    </AppShell>
  );
}
