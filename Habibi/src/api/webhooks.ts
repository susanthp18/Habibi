// Webhooks & Event Subscriptions — CRM egress endpoints.
// /webhook-endpoints CRUD, deliveries, the event catalogue and test-fire.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { Delivery, Endpoint, EventDef, EventKey } from "@/api/types/webhooks";
import { apiDelete, apiGet, apiPatch, apiPost } from "./config";

/** What the sheet sends; the server mints the secret and its vault ref. */
export type WebhookDraft = Omit<
  Endpoint,
  "id" | "createdAt" | "status" | "secret" | "secretRef"
> & {
  id?: string;
  status?: Endpoint["status"];
};

export async function fetchWebhookEndpoints(): Promise<Endpoint[]> {
  return apiGet<Endpoint[]>("/webhook-endpoints");
}

export async function fetchWebhookDeliveries(endpointId?: string): Promise<Delivery[]> {
  const q = endpointId ? `?endpointId=${encodeURIComponent(endpointId)}` : "";
  return apiGet<Delivery[]>(`/webhook-deliveries${q}`);
}

export async function fetchEventCatalog(): Promise<EventDef[]> {
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
  await apiDelete(`/webhook-endpoints/${ep.id}`);
}

export async function rotateWebhookSecret(ep: Endpoint): Promise<EndpointWithOnce> {
  return apiPost<EndpointWithOnce>(`/webhook-endpoints/${ep.id}/rotate-secret`, {});
}

export async function testFireWebhook(ep: Endpoint, event?: EventKey): Promise<Delivery> {
  const q = event ? `?event=${encodeURIComponent(event)}` : "";
  return apiPost<Delivery>(`/webhook-endpoints/${ep.id}/test${q}`, {});
}

export async function retryWebhookDelivery(d: Delivery): Promise<Delivery> {
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
    create: useMutation({
      meta: { errors: "caller" },
      mutationFn: createWebhookEndpoint,
      onSuccess: invalidate,
    }),
    update: useMutation({
      meta: { errors: "caller" },
      mutationFn: updateWebhookEndpoint,
      onSuccess: invalidate,
    }),
    remove: useMutation({
      meta: { errors: "caller" },
      mutationFn: deleteWebhookEndpoint,
      onSuccess: invalidate,
    }),
    rotate: useMutation({
      meta: { errors: "caller" },
      mutationFn: rotateWebhookSecret,
      onSuccess: invalidate,
    }),
    testFire: useMutation({
      meta: { errors: "toast" },
      mutationFn: ({ ep, event }: { ep: Endpoint; event?: EventKey }) => testFireWebhook(ep, event),
      onSuccess: invalidate,
    }),
    retry: useMutation({
      meta: { errors: "caller" },
      mutationFn: retryWebhookDelivery,
      onSuccess: invalidate,
    }),
  };
}
