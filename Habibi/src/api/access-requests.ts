import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiPost } from "./config";

export type AccessRequest = {
  id: string;
  userId: string;
  userName: string;
  userEmail: string | null;
  pagePath: string;
  permission: string | null;
  permissionLabel: string | null;
  reason: string;
  status: string;
  grantedRoleId: string | null;
  grantedRoleName: string | null;
  requestedAt: string | null;
  reviewedAt: string | null;
  reviewedByUserId: string | null;
  reviewedByName: string | null;
  lastError: string | null;
};

export type AccessRequests = { requests: AccessRequest[] };
export type AccessRequestWrite = { request: AccessRequest };

export function useAccessRequests(enabled = true) {
  return useQuery({
    queryKey: ["access-requests"],
    queryFn: async () => apiGet<AccessRequests>("/access-requests"),
    enabled,
  });
}

export function useCreateAccessRequest() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "caller" },
    mutationFn: async (body: { pagePath: string; reason: string; permission?: string | null }) =>
      apiPost<AccessRequestWrite>("/access-requests", body),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["access-requests"] }),
  });
}

export function useApproveAccessRequest() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "caller" },
    mutationFn: async (body: { requestId: string; roleId: string }) =>
      apiPost<AccessRequestWrite>(`/access-requests/${body.requestId}/approve`, {
        roleId: body.roleId,
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["access-requests"] });
      void qc.invalidateQueries({ queryKey: ["users"] });
      void qc.invalidateQueries({ queryKey: ["me"] });
    },
  });
}

export function useDenyAccessRequest() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "caller" },
    mutationFn: async (requestId: string) =>
      apiPost<AccessRequestWrite>(`/access-requests/${requestId}/deny`, {}),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["access-requests"] }),
  });
}
