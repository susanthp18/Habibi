import { createFileRoute, notFound } from "@tanstack/react-router";
import { z } from "zod";
import { fetchCustomer } from "@/api/customers";

const TABS = ["overview", "ledger", "emi", "interactions", "promises", "disputes", "documents", "notes"] as const;

const searchSchema = z.object({
  tab: z.enum(TABS).catch("overview"),
});

export const Route = createFileRoute("/customers/$customerId")({
  validateSearch: searchSchema,
  loader: async ({ params }) => {
    const c = await fetchCustomer(params.customerId);
    if (!c) throw notFound();
    return { customer: c };
  },
  head: ({ loaderData }) => ({
    meta: [
      {
        title: loaderData
          ? `${loaderData.customer.name} — Customer 360`
          : "Customer 360",
      },
      {
        name: "description",
        content:
          "AI insights, next-best-action, ledger, EMI, interactions, promises, disputes, and documents for this account.",
      },
    ],
  }),
});
