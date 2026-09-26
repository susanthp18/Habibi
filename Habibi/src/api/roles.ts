import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPatch } from "./config";

export type RolesCatalog = {
  permissions: { id: string; module: string; action: string; description: string }[];
  agentPublishRoles: string[];
  grants: { role: string; permission_id: string; role_id?: string }[];
  roles?: { id: string; name: string; permissionIds: string[] }[];
};

export function useRolesCatalog() {
  return useQuery({
    queryKey: ["roles"],
    queryFn: async () => apiGet<RolesCatalog>("/roles"),
  });
}

export function usePatchRolePermissions() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "caller" },
    mutationFn: async (body: { roleId: string; permissionIds: string[] }) =>
      apiPatch(`/roles/${body.roleId}/permissions`, { permissionIds: body.permissionIds }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["roles"] }),
  });
}
