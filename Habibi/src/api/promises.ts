// -----------------------------------------------------------------------------
// Promise-to-Pay & Payment Plans — data access seam.
//   fetchPromises()      → pipeline list   (GET /promises)
//   fetchPaymentPlans()  → plans table     (GET /payment-plans)
//   createPromise / movePromise / reschedulePromise / createPlan → writes
//
// Mock branch preserves the in-memory seed behaviour exactly; the live branch
// maps to the Phase 3A write endpoints and relies on query invalidation for the
// refreshed list (POST/PATCH return the Customer-360 promise shape, not the
// richer screen shape, so the route refetches rather than using the response).
// -----------------------------------------------------------------------------

import { useQuery } from "@tanstack/react-query";

import type { CreateInput } from "@/components/promises/PromiseSheet";
import type { PlanInput } from "@/components/promises/PlanBuilderSheet";
import {
  buildSchedule,
  createPlan as createSeedPlan,
  createPromise as createSeedPromise,
  movePromise as moveSeedPromise,
  plans as seedPlans,
  promises as seedPromises,
  reschedulePromise as rescheduleSeedPromise,
  type PaymentPlan,
  type Promise as Ptp,
  type PromiseStatus,
} from "@/data/promises-seed";
import { apiGet, apiPatch, apiPost, mockDelay, USE_MOCK } from "./config";
import { resolveActor } from "./staff";

export async function fetchPromises(): Promise<Ptp[]> {
  if (USE_MOCK) return mockDelay(seedPromises);
  return apiGet<Ptp[]>("/promises");
}

export async function fetchPaymentPlans(): Promise<PaymentPlan[]> {
  if (USE_MOCK) return mockDelay(seedPlans);
  return apiGet<PaymentPlan[]>("/payment-plans");
}

export function usePromises() {
  return useQuery({ queryKey: ["promises"], queryFn: fetchPromises, staleTime: 15_000 });
}

export function usePaymentPlans() {
  return useQuery({ queryKey: ["payment-plans"], queryFn: fetchPaymentPlans, staleTime: 15_000 });
}

export async function createPromise(input: CreateInput): Promise<{ id: string }> {
  if (USE_MOCK) return createSeedPromise(input);
  // The owner triplet is authoritative (see DATA_MODEL.md): `source` is derived
  // from owner_kind on read, so resolving the chosen owner sets both.
  const actor = await resolveActor(input.owner);
  return apiPost<{ id: string }>("/promises", {
    customerId: input.customerId,
    amount: input.amount,
    promisedDate: input.promisedDate,
    channel: input.channel,
    reminderStatus: input.reminder,
    ownerUserId: actor.kind === "human" ? actor.id : undefined,
    ownerBotId: actor.kind === "bot" ? actor.id : undefined,
  });
}

export async function movePromise(p: Ptp, status: PromiseStatus, opts?: { paidAmount?: number }): Promise<void> {
  if (USE_MOCK) {
    moveSeedPromise(p.id, status, opts);
    return;
  }
  await apiPatch(`/promises/${p.id}`, { status, paidAmount: opts?.paidAmount });
}

export async function reschedulePromise(p: Ptp, newDate: string): Promise<void> {
  if (USE_MOCK) {
    rescheduleSeedPromise(p.id, newDate);
    return;
  }
  await apiPatch(`/promises/${p.id}`, { promisedDate: newDate });
}

export async function createPlan(input: PlanInput): Promise<{ id: string }> {
  if (USE_MOCK) return createSeedPlan(input);
  const schedule = buildSchedule({
    total: input.total,
    installments: input.installments,
    startDate: input.startDate,
    cadence: input.cadence,
  });
  return apiPost<{ id: string }>("/payment-plans", {
    customerId: input.customerId,
    totalAmount: input.total,
    installments: schedule.map((s) => ({ dueDate: s.dueDate, amount: s.amount })),
  });
}
