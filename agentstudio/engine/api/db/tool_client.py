"""Database client for managing tools."""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import List, Optional

from loguru import logger
from sqlalchemy import func, select, update
from sqlalchemy.orm import selectinload

from api.db.base_client import BaseDBClient
from api.db.models import (
    ToolModel, ToolRevisionModel, WorkflowDefinitionModel, WorkflowModel,
    WorkflowToolBindingModel,
)
from api.enums import ToolCategory, ToolStatus
from api.services.tool_revisions import snapshot_digest, snapshot_tool


class ToolClient(BaseDBClient):
    """Client for managing tools (organization-scoped, UUID-referenced)."""

    async def create_tool(
        self,
        organization_id: int,
        user_id: int,
        name: str,
        definition: dict,
        category: str = ToolCategory.HTTP_API.value,
        description: Optional[str] = None,
        icon: Optional[str] = None,
        icon_color: Optional[str] = None,
    ) -> ToolModel:
        """Create a new tool.

        Args:
            organization_id: ID of the organization
            user_id: ID of the user creating the tool
            name: Display name for the tool
            definition: JSON definition of the tool
            category: Tool category (http_api, native, integration)
            description: Optional description
            icon: Optional icon identifier
            icon_color: Optional hex color code

        Returns:
            The created ToolModel with auto-generated UUID
        """
        async with self.async_session() as session:
            tool = ToolModel(
                organization_id=organization_id,
                created_by=user_id,
                name=name,
                description=description,
                category=category,
                icon=icon,
                icon_color=icon_color,
                definition=definition,
                status=ToolStatus.ACTIVE.value,
            )

            session.add(tool)
            await session.flush()
            snapshot = snapshot_tool(tool)
            session.add(ToolRevisionModel(
                tool_id=tool.id, organization_id=organization_id, revision=1,
                snapshot=snapshot, digest=snapshot_digest(snapshot), state="draft",
                authored_by=user_id,
            ))
            await session.commit()
            await session.refresh(tool)

            logger.info(
                f"Created tool '{name}' ({tool.tool_uuid}) "
                f"for organization {organization_id}"
            )
            return tool

    async def get_tools_for_organization(
        self,
        organization_id: int,
        status: Optional[str] = None,
        category: Optional[str] = None,
    ) -> List[ToolModel]:
        """Get all tools for an organization.

        Args:
            organization_id: ID of the organization
            status: Optional filter by status (active, archived, draft)
            category: Optional filter by category (http_api, native, integration)

        Returns:
            List of ToolModel instances
        """
        async with self.async_session() as session:
            query = select(ToolModel).where(
                ToolModel.organization_id == organization_id
            )

            if status:
                # Support comma-separated status values (e.g., "active,archived")
                status_list = [s.strip() for s in status.split(",")]
                if len(status_list) > 1:
                    query = query.where(ToolModel.status.in_(status_list))
                else:
                    query = query.where(ToolModel.status == status)
            else:
                # By default, exclude archived tools
                query = query.where(ToolModel.status != ToolStatus.ARCHIVED.value)

            if category:
                query = query.where(ToolModel.category == category)

            query = query.order_by(ToolModel.name)

            result = await session.execute(query)
            return list(result.scalars().all())

    async def get_tool_by_uuid(
        self,
        tool_uuid: str,
        organization_id: int,
        include_archived: bool = False,
    ) -> Optional[ToolModel]:
        """Get a tool by its UUID, scoped to organization.

        Args:
            tool_uuid: The unique tool UUID
            organization_id: ID of the organization (for authorization)
            include_archived: If True, include archived tools

        Returns:
            ToolModel if found and authorized, None otherwise
        """
        async with self.async_session() as session:
            query = (
                select(ToolModel)
                .where(
                    ToolModel.tool_uuid == tool_uuid,
                    ToolModel.organization_id == organization_id,
                )
                .options(selectinload(ToolModel.created_by_user))
            )

            if not include_archived:
                query = query.where(ToolModel.status != ToolStatus.ARCHIVED.value)

            result = await session.execute(query)
            return result.scalar_one_or_none()

    async def update_tool(
        self,
        tool_uuid: str,
        organization_id: int,
        name: Optional[str] = None,
        description: Optional[str] = None,
        definition: Optional[dict] = None,
        icon: Optional[str] = None,
        icon_color: Optional[str] = None,
        status: Optional[str] = None,
        authored_by: Optional[int] = None,
        expected_revision: Optional[int] = None,
    ) -> Optional[ToolModel]:
        """Update a tool by UUID.

        Args:
            tool_uuid: The unique tool UUID
            organization_id: ID of the organization (for authorization)
            name: New name (if provided)
            description: New description (if provided)
            definition: New definition (if provided)
            icon: New icon (if provided)
            icon_color: New icon color (if provided)
            status: New status (if provided)

        Returns:
            Updated ToolModel if found, None otherwise
        """
        async with self.async_session() as session:
            # First check if tool exists and belongs to organization
            result = await session.execute(select(ToolModel).where(
                ToolModel.tool_uuid == tool_uuid,
                ToolModel.organization_id == organization_id,
            ).with_for_update())
            tool = result.scalar_one_or_none()
            if not tool:
                return None

            latest = await session.scalar(select(func.max(ToolRevisionModel.revision)).where(
                ToolRevisionModel.tool_id == tool.id,
                ToolRevisionModel.organization_id == organization_id,
            )) or 0
            if expected_revision is not None and latest != expected_revision:
                raise ValueError("tool_revision_conflict")

            # Build update values
            update_values = {"updated_at": datetime.now(UTC)}
            if name is not None:
                update_values["name"] = name
            if description is not None:
                update_values["description"] = description
            if definition is not None:
                update_values["definition"] = definition
            if icon is not None:
                update_values["icon"] = icon
            if icon_color is not None:
                update_values["icon_color"] = icon_color
            if status is not None:
                update_values["status"] = status

            await session.execute(
                update(ToolModel)
                .where(
                    ToolModel.tool_uuid == tool_uuid,
                    ToolModel.organization_id == organization_id,
                )
                .values(**update_values)
            )
            await session.flush()
            if any(value is not None for value in (name, description, definition)):
                await session.refresh(tool)
                snapshot = snapshot_tool(tool)
                session.add(ToolRevisionModel(
                    tool_id=tool.id, organization_id=organization_id,
                    revision=latest + 1, snapshot=snapshot,
                    digest=snapshot_digest(snapshot), state="draft",
                    authored_by=authored_by or tool.created_by,
                ))
            await session.commit()

            # Fetch updated tool
            result = await session.execute(
                select(ToolModel)
                .where(ToolModel.tool_uuid == tool_uuid)
                .options(selectinload(ToolModel.created_by_user))
            )
            updated_tool = result.scalar_one()

            logger.info(f"Updated tool {tool_uuid} for organization {organization_id}")
            return updated_tool

    async def get_tool_revisions(self, tool_uuid: str, organization_id: int) -> list[ToolRevisionModel]:
        async with self.async_session() as session:
            result = await session.execute(select(ToolRevisionModel)
                .join(ToolModel, ToolRevisionModel.tool_id == ToolModel.id)
                .where(ToolModel.tool_uuid == tool_uuid, ToolModel.organization_id == organization_id)
                .order_by(ToolRevisionModel.revision.desc()))
            return list(result.scalars().all())

    async def get_tool_revision_usage(self, tool_uuid: str, organization_id: int) -> dict[int, int]:
        async with self.async_session() as session:
            result = await session.execute(select(
                ToolRevisionModel.revision, func.count(WorkflowToolBindingModel.workflow_definition_id)
            ).join(ToolModel, ToolRevisionModel.tool_id == ToolModel.id)
             .outerjoin(WorkflowToolBindingModel,
                        WorkflowToolBindingModel.tool_revision_id == ToolRevisionModel.id)
             .where(ToolModel.tool_uuid == tool_uuid,
                    ToolModel.organization_id == organization_id)
             .group_by(ToolRevisionModel.revision))
            return {revision: count for revision, count in result.all()}

    async def review_tool_revision(
        self, tool_uuid: str, revision: int, organization_id: int,
        *, actor_id: int, state: str, policy: dict | None = None,
    ) -> ToolRevisionModel | None:
        async with self.async_session() as session:
            tool = await session.scalar(select(ToolModel).where(
                ToolModel.tool_uuid == tool_uuid,
                ToolModel.organization_id == organization_id,
            ).with_for_update())
            if tool is None:
                return None
            result = await session.execute(select(ToolRevisionModel)
                .where(ToolRevisionModel.tool_id == tool.id,
                       ToolRevisionModel.organization_id == organization_id,
                       ToolRevisionModel.revision == revision)
                .with_for_update())
            row = result.scalar_one_or_none()
            if row is None:
                return None
            latest = await session.scalar(select(func.max(ToolRevisionModel.revision)).where(
                ToolRevisionModel.tool_id == tool.id,
                ToolRevisionModel.organization_id == organization_id,
            ))
            if state in {"submitted", "approved"} and revision != latest:
                raise ValueError("tool_revision_conflict")
            if state == "submitted" and row.state == "draft":
                row.state = state
                row.policy = policy or {}
            elif state in {"approved", "rejected"} and row.state == "submitted":
                if row.authored_by == actor_id:
                    raise ValueError("tool_author_cannot_review")
                row.state = state
                row.reviewed_by = actor_id
                row.reviewed_at = datetime.now(UTC)
            elif state == "revoked" and row.state in {"approved", "legacy"}:
                row.state = state
                row.reviewed_by = actor_id
                row.revoked_at = datetime.now(UTC)
            else:
                raise ValueError("invalid_tool_revision_transition")
            await session.commit()
            await session.refresh(row)
            return row

    async def get_bound_tool_revisions(
        self, workflow_definition_id: int, organization_id: int, node_id: str,
        tool_uuids: list[str],
    ) -> list[tuple[ToolRevisionModel, str, str]]:
        if not tool_uuids:
            return []
        async with self.async_session() as session:
            result = await session.execute(select(
                ToolRevisionModel, WorkflowToolBindingModel.tool_uuid,
                WorkflowToolBindingModel.digest,
            )
                .join(WorkflowToolBindingModel, WorkflowToolBindingModel.tool_revision_id == ToolRevisionModel.id)
                .where(WorkflowToolBindingModel.workflow_definition_id == workflow_definition_id,
                       WorkflowToolBindingModel.organization_id == organization_id,
                       WorkflowToolBindingModel.node_id == node_id,
                       WorkflowToolBindingModel.tool_uuid.in_(tool_uuids),
                       ToolRevisionModel.organization_id == organization_id))
            return list(result.all())

    async def get_workflow_tool_manifest(
        self, workflow_id: int, definition_id: int, organization_id: int,
    ) -> list[dict]:
        async with self.async_session() as session:
            result = await session.execute(select(WorkflowToolBindingModel, ToolRevisionModel)
                .join(ToolRevisionModel, WorkflowToolBindingModel.tool_revision_id == ToolRevisionModel.id)
                .join(WorkflowDefinitionModel,
                      WorkflowToolBindingModel.workflow_definition_id == WorkflowDefinitionModel.id)
                .join(WorkflowModel, WorkflowDefinitionModel.workflow_id == WorkflowModel.id)
                .where(WorkflowModel.id == workflow_id,
                       WorkflowModel.organization_id == organization_id,
                       WorkflowDefinitionModel.id == definition_id,
                       WorkflowToolBindingModel.organization_id == organization_id,
                       ToolRevisionModel.organization_id == organization_id))
            return [{"nodeId": binding.node_id, "toolUuid": binding.tool_uuid,
                     "revisionId": revision.id, "revision": revision.revision,
                     "digest": binding.digest, "state": revision.state,
                     "snapshot": revision.snapshot, "policy": revision.policy}
                    for binding, revision in result.all()]

    async def get_runtime_tools(
        self, tool_uuids: list[str], organization_id: int,
        *, definition_id: int | None, node_id: str | None,
    ) -> list:
        """Drafts use catalog tools; released calls use only pinned revisions."""
        if not tool_uuids:
            return []
        if definition_id is None:
            # Fail closed, but never quietly: an agent whose run definition was
            # not bound would otherwise just appear to have no tools.
            logger.error(
                "Refusing tools for an agent with no run definition: {}", tool_uuids
            )
            return []
        async with self.async_session() as session:
            result = await session.execute(select(WorkflowDefinitionModel.status)
                .join(WorkflowModel, WorkflowDefinitionModel.workflow_id == WorkflowModel.id)
                .where(WorkflowDefinitionModel.id == definition_id,
                       WorkflowModel.organization_id == organization_id))
            status = result.scalar_one_or_none()
        if status == "draft":
            return await self.get_tools_by_uuids(tool_uuids, organization_id)
        if status not in {"published", "archived"} or not node_id:
            return []
        rows = await self.get_bound_tool_revisions(
            definition_id, organization_id, node_id, tool_uuids,
        )
        tools = []
        for revision, tool_uuid, binding_digest in rows:
            if revision.state not in {"approved", "legacy"}:
                continue
            snapshot = revision.snapshot or {}
            if (binding_digest != revision.digest or
                    (revision.state == "approved" and snapshot_digest(snapshot) != revision.digest)):
                logger.error("Refusing tool {}: released revision digest mismatch", tool_uuid)
                continue
            tools.append(SimpleNamespace(
                tool_uuid=tool_uuid, name=snapshot.get("name"),
                description=snapshot.get("description"),
                category=snapshot.get("category"),
                definition=snapshot.get("definition") or {},
                revision=revision.revision, revision_id=revision.id,
                revision_digest=revision.digest, policy=revision.policy or {},
            ))
        return tools

    async def is_tool_revision_callable(self, revision_id: int, organization_id: int) -> bool:
        async with self.async_session() as session:
            row = await session.scalar(select(ToolRevisionModel.id).where(
                ToolRevisionModel.id == revision_id,
                ToolRevisionModel.organization_id == organization_id,
                ToolRevisionModel.state.in_(["approved", "legacy"]),
            ))
            return row is not None

    async def archive_tool(self, tool_uuid: str, organization_id: int) -> bool:
        """Soft delete a tool by setting its status to archived.

        Args:
            tool_uuid: The unique tool UUID
            organization_id: ID of the organization (for authorization)

        Returns:
            True if tool was archived, False if not found
        """
        async with self.async_session() as session:
            result = await session.execute(
                update(ToolModel)
                .where(
                    ToolModel.tool_uuid == tool_uuid,
                    ToolModel.organization_id == organization_id,
                    ToolModel.status != ToolStatus.ARCHIVED.value,
                )
                .values(
                    status=ToolStatus.ARCHIVED.value,
                    updated_at=datetime.now(UTC),
                )
            )
            await session.commit()

            if result.rowcount > 0:
                logger.info(
                    f"Archived tool {tool_uuid} for organization {organization_id}"
                )
                return True
            return False

    async def unarchive_tool(
        self, tool_uuid: str, organization_id: int
    ) -> Optional[ToolModel]:
        """Restore an archived tool by setting its status to active.

        Args:
            tool_uuid: The unique tool UUID
            organization_id: ID of the organization (for authorization)

        Returns:
            The unarchived ToolModel if found, None otherwise
        """
        async with self.async_session() as session:
            result = await session.execute(
                update(ToolModel)
                .where(
                    ToolModel.tool_uuid == tool_uuid,
                    ToolModel.organization_id == organization_id,
                    ToolModel.status == ToolStatus.ARCHIVED.value,
                )
                .values(
                    status=ToolStatus.ACTIVE.value,
                    updated_at=datetime.now(UTC),
                )
            )
            await session.commit()

            if result.rowcount > 0:
                logger.info(
                    f"Unarchived tool {tool_uuid} for organization {organization_id}"
                )
                # Fetch and return the updated tool
                result = await session.execute(
                    select(ToolModel).where(ToolModel.tool_uuid == tool_uuid)
                )
                return result.scalar_one_or_none()
            return None

    async def validate_tool_uuid(self, tool_uuid: str, organization_id: int) -> bool:
        """Check if a tool UUID exists and belongs to the organization.

        This is useful for workflow validation to ensure referenced tools exist.

        Args:
            tool_uuid: The tool UUID to validate
            organization_id: ID of the organization

        Returns:
            True if valid, False otherwise
        """
        tool = await self.get_tool_by_uuid(tool_uuid, organization_id)
        return tool is not None

    async def get_tools_by_uuids(
        self,
        tool_uuids: List[str],
        organization_id: int,
    ) -> List[ToolModel]:
        """Get multiple tools by their UUIDs.

        Args:
            tool_uuids: List of tool UUIDs to fetch
            organization_id: ID of the organization (for authorization)

        Returns:
            List of ToolModel instances (only active tools)
        """
        if not tool_uuids:
            return []

        async with self.async_session() as session:
            query = select(ToolModel).where(
                ToolModel.tool_uuid.in_(tool_uuids),
                ToolModel.organization_id == organization_id,
                ToolModel.status == ToolStatus.ACTIVE.value,
            )

            result = await session.execute(query)
            return list(result.scalars().all())
