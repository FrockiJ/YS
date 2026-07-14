from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class DomainProfile:
    """Tenant/domain profile exposed to AI and UI-facing metadata layers."""

    id: str
    name: str
    display_name: str
    description: str = ""
    default_tone: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModuleDefinition:
    id: str
    name: str
    layer: str
    category: str
    description: str
    backend_routes: tuple[str, ...] = ()
    frontend_routes: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


class DomainProfileProvider(Protocol):
    def get_profile(self) -> DomainProfile:
        ...


class KnowledgeProvider(Protocol):
    id: str

    async def search(self, query: str, *, limit: int = 10, context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        ...


class BusinessConnector(Protocol):
    id: str
    kind: str

    async def health(self) -> dict[str, Any]:
        ...


class BehaviorProfileProvider(Protocol):
    def get_behavior_profiles(self) -> dict[str, dict[str, Any]]:
        ...


@dataclass(frozen=True)
class ExtensionBundle:
    domain_profile_provider: DomainProfileProvider | None = None
    knowledge_providers: tuple[KnowledgeProvider, ...] = ()
    business_connectors: tuple[BusinessConnector, ...] = ()
    behavior_profile_provider: BehaviorProfileProvider | None = None
