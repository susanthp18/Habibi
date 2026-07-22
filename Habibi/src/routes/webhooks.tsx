import { useCallback, useMemo, useState } from "react";
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
import { Pause, Play, KeyRound, Trash2 } from "lucide-react";
import {
  SEED_ENDPOINTS,
  SEED_DELIVERIES,
  rotateSecret,
  simulateDelivery,
  type Delivery,
  type Endpoint,
} from "@/data/webhooks-seed";

export const Route = createFileRoute("/webhooks")({
  head: () => ({
    meta: [
      { title: "Webhooks & Event Subscriptions — Collections Agent" },
      { name: "description", content: "Register downstream endpoints, subscribe them to CRM events, and monitor delivery, retries and signing." },
      { property: "og:title", content: "Webhooks & Event Subscriptions" },
      { property: "og:description", content: "How the Pipecat backend and the client's legacy banking systems stay in sync with the bot." },
    ],
  }),
  component: WebhooksPage,
});

function WebhooksPage() {
  const [endpoints, setEndpoints] = useState<Endpoint[]>(SEED_ENDPOINTS);
  const [deliveries, setDeliveries] = useState<Delivery[]>(SEED_DELIVERIES);
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

  const appendDelivery = useCallback((d: Delivery) => {
    setDeliveries((prev) => [d, ...prev]);
  }, []);

  const updateEndpoint = (ep: Endpoint) =>
    setEndpoints((prev) => prev.map((e) => (e.id === ep.id ? ep : e)));

  const deleteEndpoint = (ep: Endpoint) => {
    setEndpoints((prev) => prev.filter((e) => e.id !== ep.id));
    setDeliveries((prev) => prev.filter((d) => d.endpointId !== ep.id));
    if (activeId === ep.id) setDrawerOpen(false);
    setSelectedIds((prev) => {
      const next = new Set(prev);
      next.delete(ep.id);
      return next;
    });
    toast.success(`Deleted ${ep.name}`);
  };

  const rotateOne = (ep: Endpoint) => {
    const secret = rotateSecret(ep.algo);
    updateEndpoint({ ...ep, secret });
    toast.success(`Rotated secret for ${ep.name}`, {
      description: "Redeploy the receiver with the new secret.",
    });
  };

  const testFire = (ep: Endpoint) => {
    const evt = ep.events[0] ?? "call.completed";
    const d = simulateDelivery(ep, evt);
    appendDelivery(d);
    if (d.status === "success") toast.success(`${ep.name} → ${d.httpStatus} · ${d.latencyMs}ms`);
    else toast.error(`${ep.name} → ${d.httpStatus} · ${d.latencyMs}ms`);
  };

  const togglePause = (ep: Endpoint) => {
    const next: Endpoint = { ...ep, status: ep.status === "paused" ? "active" : "paused" };
    updateEndpoint(next);
    toast.info(`${ep.name} ${next.status}`);
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

  const handleSaveDraft = (
    draft: Omit<Endpoint, "id" | "createdAt" | "status"> & { id?: string },
    andTest = false,
  ) => {
    if (editing) {
      const merged: Endpoint = { ...editing, ...draft } as Endpoint;
      updateEndpoint(merged);
      toast.success(`Saved ${merged.name}`);
      setSheetOpen(false);
      if (andTest) testFire(merged);
    } else {
      const created: Endpoint = {
        ...(draft as Omit<Endpoint, "id" | "createdAt" | "status">),
        id: `wh_${Math.random().toString(36).slice(2, 9)}`,
        status: "active",
        createdAt: Date.now(),
      };
      setEndpoints((prev) => [created, ...prev]);
      toast.success(`Created ${created.name}`);
      setSheetOpen(false);
      if (andTest) testFire(created);
    }
  };

  const retryDelivery = (d: Delivery) => {
    const ep = endpoints.find((e) => e.id === d.endpointId);
    if (!ep) return;
    const next = simulateDelivery(ep, d.event, d.payload);
    appendDelivery(next);
    if (next.status === "success") toast.success(`Retry succeeded · ${next.httpStatus}`);
    else toast.error(`Retry failed · ${next.httpStatus}`);
  };

  /* Bulk toolbar actions */
  const selectedEndpoints = endpoints.filter((e) => selectedIds.has(e.id));

  const bulkPause = (pause: boolean) => {
    selectedEndpoints.forEach((ep) =>
      updateEndpoint({ ...ep, status: pause ? "paused" : "active" }),
    );
    toast.info(`${selectedEndpoints.length} endpoint(s) ${pause ? "paused" : "resumed"}`);
  };
  const bulkRotate = () => {
    selectedEndpoints.forEach(rotateOne);
  };
  const bulkDelete = () => {
    selectedEndpoints.forEach(deleteEndpoint);
    setSelectedIds(new Set());
  };
  const rotateAll = () => {
    endpoints.forEach(rotateOne);
  };

  return (
    <AppShell>
      <div className="flex h-full min-h-0 flex-col">
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
          <DeliveryLogPane
            endpoints={endpoints}
            deliveries={deliveries}
            onRetry={retryDelivery}
          />
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
        onAppendDelivery={appendDelivery}
        onRotate={rotateOne}
        onRetry={retryDelivery}
      />

      <EventCatalogDialog open={catalogOpen} onOpenChange={setCatalogOpen} />
    </AppShell>
  );
}
