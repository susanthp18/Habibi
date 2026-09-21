import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiPost } from "./config";

export type OperatorInvite = {
  id: string;
  email: string;
  roleId: string;
  roleName: string;
  status: string;
  invitedByUserId: string | null;
  invitedByName: string | null;
  sentAt: string | null;
  acceptedAt: string | null;
  lastError: string | null;
};

export type OperatorInvites = { invites: OperatorInvite[] };
export type OperatorInviteWrite = { invite: OperatorInvite };

export function useInvites() {
  return useQuery({
    queryKey: ["invites"],
    queryFn: async () => apiGet<OperatorInvites>("/invites"),
  });
}

export function useCreateInvite() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "caller" },
    mutationFn: async (body: { email: string; roleId: string }) =>
      apiPost<OperatorInviteWrite>("/invites", body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["invites"] });
      void qc.invalidateQueries({ queryKey: ["users"] });
    },
  });
}

export function useResendInvite() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "caller" },
    mutationFn: async (inviteId: string) =>
      apiPost<OperatorInviteWrite>(`/invites/${inviteId}/resend`, {}),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["invites"] }),
  });
}

export function useRevokeInvite() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "caller" },
    mutationFn: async (inviteId: string) =>
      apiPost<OperatorInviteWrite>(`/invites/${inviteId}/revoke`, {}),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["invites"] }),
  });
}
