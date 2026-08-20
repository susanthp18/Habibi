import { apiPost, USE_MOCK } from "./config";

export async function applyAuthority(input: {
  decisionId: string;
  amount?: number | null;
  disputeId?: string | null;
}): Promise<{ ledgerId: string; disputeId?: string | null; amount: number }> {
  if (USE_MOCK) {
    throw new Error("Live goodwill apply is not available in mock mode");
  }
  return apiPost("/authority/apply", {
    decisionId: input.decisionId,
    amount: input.amount ?? undefined,
    disputeId: input.disputeId ?? undefined,
  });
}
