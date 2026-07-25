// Webhooks & Event Subscriptions — CRM egress endpoints.
// Mock: in-memory seed mutators. Live: /webhook-endpoints CRUD + deliveries.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  EVENT_CATALOG,
  SEED_DELIVERIES,
  SEED_ENDPOINTS,
  rotateSecret as seedRotateSecret,
  simulateDelivery,
  type Delivery,
  type Endpoint,
  type EventDef,
  type EventKey,
} from "@/data/webhooks-seed";
import { apiDelete, apiGet, apiPatch, apiPost, mockDelay, USE_MOCK } from "./config";

let mockEndpoints: Endpoint[] = [...SEED_ENDPOINTS];
let mockDeliveries: Delivery[] = [...SEED_DELIVERIES];

export type WebhookDraft = Omit<Endpoint, "id" | "createdAt" | "status"> & {
  id?: string;
  status?: Endpoint["status"];
};

export async function fetchWebhookEndpoints(): Promise<Endpoint[]> {
  if (USE_MOCK) return mockDelay(mockEndpoints);
  return apiGet<Endpoint[]>("/webhook-endpoints");
}

export async function fetchWebhookDeliveries(endpointId?: string): Promise<Delivery[]> {
  if (USE_MOCK) {
    const list = endpointId
      ? mockDeliveries.filter((d) => d.endpointId === endpointId)
      : mockDeliveries;
    return mockDelay(list);
  }
  const q = endpointId ? `?endpointId=${encodeURIComponent(endpointId)}` : "";
  return apiGet<Delivery[]>(`/webhook-deliveries${q}`);
}

export async function fetchEventCatalog(): Promise<EventDef[]> {
  if (USE_MOCK) return mockDelay(EVENT_CATALOG);
  return apiGet<EventDef[]>("/event-types");
}

export function useWebhookEndpoints() {
  return useQuery({
    queryKey: ["webhook-endpoints"],
    queryFn: fetchWebhookEndpoints,
    staleTime: 10_000,
  });
}

export function useWebhookDeliveries() {
  return useQuery({
    queryKey: ["webhook-deliveries"],
    queryFn: () => fetchWebhookDeliveries(),
    staleTime: 5_000,
  });
}

export function useEventCatalog() {
  return useQuery({
    queryKey: ["event-types"],
    queryFn: fetchEventCatalog,
    staleTime: 60_000,
  });
}

type EndpointWithOnce = Endpoint & { secretOnce?: string };

export async function createWebhookEndpoint(draft: WebhookDraft): Promise<EndpointWithOnce> {
  if (USE_MOCK) {
    const created: Endpoint = {
      ...(draft as Omit<Endpoint, "id" | "createdAt" | "status">),
      id: draft.id ?? `wh_${Math.random().toString(36).slice(2, 9)}`,
      status: "active",
      createdAt: Date.now(),
      secret: draft.secret || seedRotateSecret(draft.algo),
    };
    mockEndpoints = [created, ...mockEndpoints];
    await mockDelay(undefined);
    return { ...created, secretOnce: created.secret };
  }
  return apiPost<EndpointWithOnce>("/webhook-endpoints", {
    name: draft.name,
    url: draft.url,
    target: draft.target,
    events: draft.events,
    algo: draft.algo,
    retry: draft.retry,
    headers: draft.headers,
  });
}

export async function updateWebhookEndpoint(ep: Endpoint): Promise<Endpoint> {
  if (USE_MOCK) {
    mockEndpoints = mockEndpoints.map((e) => (e.id === ep.id ? ep : e));
    await mockDelay(undefined);
    return ep;
  }
  return apiPatch<Endpoint>(`/webhook-endpoints/${ep.id}`, {
    name: ep.name,
    url: ep.url,
    target: ep.target,
    events: ep.events,
    algo: ep.algo,
    retry: ep.retry,
    headers: ep.headers,
    status: ep.status,
  });
}

export async function deleteWebhookEndpoint(ep: Endpoint): Promise<void> {
  if (USE_MOCK) {
    mockEndpoints = mockEndpoints.filter((e) => e.id !== ep.id);
    mockDeliveries = mockDeliveries.filter((d) => d.endpointId !== ep.id);
    await mockDelay(undefined);
    return;
  }
  await apiDelete(`/webhook-endpoints/${ep.id}`);
}

export async function rotateWebhookSecret(ep: Endpoint): Promise<EndpointWithOnce> {
  if (USE_MOCK) {
    const secret = seedRotateSecret(ep.algo);
    const next = { ...ep, secret };
    mockEndpoints = mockEndpoints.map((e) => (e.id === ep.id ? next : e));
    await mockDelay(undefined);
    return { ...next, secretOnce: secret };
  }
  return apiPost<EndpointWithOnce>(`/webhook-endpoints/${ep.id}/rotate-secret`, {});
}

export async function testFireWebhook(ep: Endpoint, event?: EventKey): Promise<Delivery> {
  if (USE_MOCK) {
    const d = simulateDelivery(ep, event ?? ep.events[0] ?? "call.completed");
    mockDeliveries = [d, ...mockDeliveries];
    await mockDelay(undefined);
    return d;
  }
  const q = event ? `?event=${encodeURIComponent(event)}` : "";
  return apiPost<Delivery>(`/webhook-endpoints/${ep.id}/test${q}`, {});
}

export async function retryWebhookDelivery(d: Delivery): Promise<Delivery> {
  if (USE_MOCK) {
    const ep = mockEndpoints.find((e) => e.id === d.endpointId);
    if (!ep) throw new Error("endpoint_not_found");
    const next = simulateDelivery(ep, d.event, d.payload);
    mockDeliveries = [next, ...mockDeliveries];
    await mockDelay(undefined);
    return next;
  }
  return apiPost<Delivery>(`/webhook-deliveries/${d.id}/retry`, {});
}

export function useWebhookMutations() {
  const qc = useQueryClient();
  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ["webhook-endpoints"] });
    void qc.invalidateQueries({ queryKey: ["webhook-deliveries"] });
  };
  return {
    invalidate,
    create: useMutation({ mutationFn: createWebhookEndpoint, onSuccess: invalidate }),
    update: useMutation({ mutationFn: updateWebhookEndpoint, onSuccess: invalidate }),
    remove: useMutation({ mutationFn: deleteWebhookEndpoint, onSuccess: invalidate }),
    rotate: useMutation({ mutationFn: rotateWebhookSecret, onSuccess: invalidate }),
    testFire: useMutation({ mutationFn: ({ ep, event }: { ep: Endpoint; event?: EventKey }) => testFireWebhook(ep, event), onSuccess: invalidate }),
    retry: useMutation({ mutationFn: retryWebhookDelivery, onSuccess: invalidate }),
  };
}
