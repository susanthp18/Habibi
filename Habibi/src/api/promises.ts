// -----------------------------------------------------------------------------
// Promise-to-Pay & Payment Plans — data access seam.
//   fetchPromises()      → pipeline list   (GET /promises)
//   fetchPaymentPlans()  → plans table     (GET /payment-plans)
//   createPromise / movePromise / reschedulePromise / createPlan → writes
//
// Writes map to the Phase 3A endpoints and rely on query invalidation for the
// refreshed list (POST/PATCH return the Customer-360 promise shape, not the
// richer screen shape, so the route refetches rather than using the response).
// -----------------------------------------------------------------------------

import { useQuery } from "@tanstack/react-query";
import { z } from "zod";

import type {
  CreateInput,
  CustomerOption,
  PaymentPlan,
  PlanInput,
  Promise as Ptp,
  PromiseStatus,
} from "@/api/types/promises";
import { buildSchedule } from "@/lib/promises";
import type { Customer } from "@/api/types/customer360";
import { apiGet, apiPatch, apiPost } from "./config";
import { ptpPromiseSchema } from "./customers";
import { resolveActor, type Staff } from "./staff";

// -----------------------------------------------------------------------------
// Wire schemas — field-for-field with backend/schemas.py. No route in
// routers/payments.py that these hit sets response_model_exclude_unset, so a
// `| None = None` field is `.nullable()`, never `.optional()`.
// -----------------------------------------------------------------------------

/** PromiseListResponse — GET /promises. */
const promiseListSchema = z.object({
  id: z.string(),
  customerId: z.string(),
  customerName: z.string(),
  accountTail: z.string(),
  amount: z.number(),
  promisedDate: z.string(),
  createdAt: z.string(),
  channel: z.enum(["voice", "whatsapp", "chat", "email", "sms"]),
  source: z.enum(["bot", "agent", "self"]),
  owner: z.string(),
  reminderStatus: z.enum(["off", "queued", "scheduled", "sent", "acknowledged", "failed"]),
  status: z.enum(["upcoming", "due_today", "kept", "broken", "partial"]),
  paidAmount: z.number().nullable(),
  notes: z.string().nullable(),
  planId: z.string().nullable(),
  events: z.array(
    z.object({
      at: z.string(),
      label: z.string(),
      tone: z.enum(["info", "success", "warn", "danger"]).nullable(),
    }),
  ),
  confirmChannel: z.enum(["whatsapp", "sms"]).nullable(),
  confirmStatus: z.string().nullable(),
  paymentIntentStatus: z.string().nullable(),
  paymentIntentId: z.string().nullable(),
  payLinkSent: z.boolean(),
  phoneLast4: z.string().nullable(),
});

/** PaymentPlanResponse — GET /payment-plans. */
const paymentPlanSchema = z.object({
  id: z.string(),
  customerId: z.string(),
  customerName: z.string(),
  accountTail: z.string(),
  total: z.number(),
  cadence: z.enum(["weekly", "biweekly", "monthly"]),
  startDate: z.string(),
  installments: z.array(
    z.object({
      index: z.number(),
      dueDate: z.string(),
      amount: z.number(),
      paid: z.boolean(),
      paidOn: z.string().nullable(),
    }),
  ),
  owner: z.string(),
  status: z.enum(["on_track", "slipped", "completed"]),
  createdAt: z.string(),
});

/** PromiseResendConfirmResponse — the promise row plus the underscore keys the builder emits. */
const promiseResendConfirmSchema = ptpPromiseSchema.extend({
  _fulfillment: z.object({
    promiseId: z.string(),
    intentId: z.string().nullable(),
    confirmChannel: z.string().nullable(),
    phoneLast4: z.string().nullable(),
    payLinkSent: z.boolean(),
    suppressed: z.boolean(),
    suppressionReason: z.string().nullable(),
  }),
  _spoken: z.string().nullable(),
});

/** PaymentPlanCreateResponse — POST /payment-plans. */
const paymentPlanCreateSchema = z.object({ id: z.string(), promise: ptpPromiseSchema });

export async function fetchPromises(): Promise<Ptp[]> {
  return apiGet<Ptp[]>("/promises", { schema: z.array(promiseListSchema) });
}

export async function fetchPaymentPlans(): Promise<PaymentPlan[]> {
  return apiGet<PaymentPlan[]>("/payment-plans", { schema: z.array(paymentPlanSchema) });
}

export function usePromises() {
  return useQuery({ queryKey: ["promises"], queryFn: fetchPromises, staleTime: 15_000 });
}

export function usePaymentPlans() {
  return useQuery({ queryKey: ["payment-plans"], queryFn: fetchPaymentPlans, staleTime: 15_000 });
}

export function promiseSheetCustomers(customers: Customer[]): CustomerOption[] {
  return customers.map((c) => ({
    id: c.id,
    name: c.name,
    accountId: c.accountId,
    outstanding: c.outstanding,
  }));
}

/** The /staff roster unioned with the owners already on the board. */
export function promiseOwnerOptions(staff: Staff[], existing: string[]): string[] {
  const set = new Set(existing);
  staff.forEach((s) => set.add(s.name));
  return Array.from(set).sort();
}

/**
 * The one PTP writer: the board and the 360 both post through here. The key
 * is the caller's (one per form, rotated on success) so a double-click lands
 * one promise -- the backend honours it and this used to send none.
 */
export async function createPromise(
  input: CreateInput,
  idempotencyKey: string,
): Promise<{ id: string }> {
  // The owner triplet is authoritative (see DATA_MODEL.md): `source` is derived
  // from owner_kind on read, so resolving the chosen owner sets both. No owner
  // means the acting user, which the server fills in.
  const actor = input.owner ? await resolveActor(input.owner) : null;
  return apiPost<{ id: string }>(
    "/promises",
    {
      customerId: input.customerId,
      accountId: input.accountId,
      amount: input.amount,
      promisedDate: input.promisedDate,
      channel: input.channel,
      reminderStatus: input.reminder,
      ownerUserId: actor?.kind === "human" ? actor.id : undefined,
      ownerBotId: actor?.kind === "bot" ? actor.id : undefined,
    },
    { schema: ptpPromiseSchema, headers: { "Idempotency-Key": idempotencyKey } },
  );
}

export async function movePromise(
  p: Ptp,
  status: PromiseStatus,
  opts?: { paidAmount?: number },
): Promise<void> {
  await apiPatch(
    `/promises/${p.id}`,
    { status, paidAmount: opts?.paidAmount },
    { schema: ptpPromiseSchema },
  );
}

export async function resendPromiseConfirm(p: Ptp): Promise<void> {
  await apiPost(`/promises/${p.id}/resend-confirm`, {}, { schema: promiseResendConfirmSchema });
}

export async function reschedulePromise(p: Ptp, newDate: string): Promise<void> {
  await apiPatch(`/promises/${p.id}`, { promisedDate: newDate }, { schema: ptpPromiseSchema });
}

export async function createPlan(input: PlanInput): Promise<{ id: string }> {
  const schedule = buildSchedule({
    total: input.total,
    installments: input.installments,
    startDate: input.startDate,
    cadence: input.cadence,
  });
  return apiPost<{ id: string }>(
    "/payment-plans",
    {
      customerId: input.customerId,
      totalAmount: input.total,
      installments: schedule.map((s) => ({ dueDate: s.dueDate, amount: s.amount })),
    },
    { schema: paymentPlanCreateSchema },
  );
}
