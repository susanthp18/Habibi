from __future__ import annotations

from api.services.integrations.base import IntegrationPackageSpec
from api.services.integrations.registry import register_package

from .routes import router
from .runtime import create_runtime_sessions

PACKAGE = register_package(
    IntegrationPackageSpec(
        name="supervisor",
        routers=(router,),
        create_runtime_sessions=create_runtime_sessions,
    )
)

__all__ = ["PACKAGE"]
