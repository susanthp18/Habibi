import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiPatch, apiPut } from "./config";

export type DirectoryUser = {
  id: string;
  name: string;
  upn: string | null;
  status: string;
  bootstrapAdmin: boolean;
  lastLoginAt: string | null;
  roleIds: string[];
  roleNames: string[];
};

export type DirectoryUsers = { users: DirectoryUser[] };

export function useDirectoryUsers() {
  return useQuery({
    queryKey: ["users"],
    queryFn: async () => apiGet<DirectoryUsers>("/users"),
  });
}

export function usePutUserRoles() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "caller" },
    mutationFn: async (body: { userId: string; roleIds: string[] }) =>
      apiPut<DirectoryUsers>(`/users/${body.userId}/roles`, { roleIds: body.roleIds }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["users"] }),
  });
}

export function usePatchUserStatus() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "caller" },
    mutationFn: async (body: { userId: string; status: "active" | "inactive" }) =>
      apiPatch<DirectoryUsers>(`/users/${body.userId}`, { status: body.status }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["users"] }),
  });
}
