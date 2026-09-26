"""Roles & access: the permission catalog and each role's resolved grants.

    GET   /roles                          the Roles page (and invites / access requests)
    PATCH /roles/{role_id}/permissions    replace a role's explicit grants
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

import authz
import db
from api_support import ROUTER_DEPENDENCIES, Utf8JSONResponse, _handle_write
from schemas import RolePermissionsPatchRequest, RoleResponse, RolesCatalogResponse

router = APIRouter(default_response_class=Utf8JSONResponse, dependencies=ROUTER_DEPENDENCIES)


@router.get("/roles", response_model=RolesCatalogResponse)
def list_roles_catalog():
    """Roles page. Grants are the resolved set the enforcer will honour."""
    catalog = [
        {"id": pid, "module": module, "action": action, "description": description}
        for pid, module, action, description in authz.PERMISSION_CATALOG
    ]
    rows = db.list_role_grant_rows()
    explicit_by_role: dict[str, list[str]] = {}
    role_meta: dict[str, tuple[str, bool]] = {}
    role_order: list[str] = []
    for row in rows:
        rid = row["role_id"]
        if rid not in role_meta:
            role_meta[rid] = (row["role_name"], row["configured_at"] is not None)
            role_order.append(rid)
            explicit_by_role[rid] = []
        if row["permission_id"]:
            explicit_by_role[rid].append(row["permission_id"])
    roles_out: list[dict[str, Any]] = []
    grants: list[dict[str, Any]] = []
    publishers: set[str] = set()
    for rid in role_order:
        name, configured = role_meta[rid]
        resolved = sorted(
            authz.resolve_role_grants(name, explicit_by_role[rid], configured=configured)
        )
        roles_out.append({"id": rid, "name": name, "permissionIds": resolved})
        for pid in resolved:
            grants.append({"role_id": rid, "role": name, "permission_id": pid})
            if pid == authz.AGENT_PUBLISH:
                publishers.add(name)
    return {
        "permissions": catalog,
        "agentPublishRoles": sorted(publishers),
        "grants": grants,
        "roles": roles_out,
    }


@router.patch("/roles/{role_id}/permissions", response_model=RoleResponse)
def patch_role_permissions(role_id: str, payload: RolePermissionsPatchRequest):
    return _handle_write(db.replace_role_permissions, role_id, list(payload.permissionIds))
