from __future__ import annotations

import os
from typing import Any

from ..domain_modules.loader import get_domain_module_definitions, load_domain_profile_data
from .extensions import DomainProfile, ModuleDefinition
from .store_profile import get_store_profile


CORE_MODULE_IDS = {
    "core.auth",
    "core.admin",
    "core.chat",
    "core.projects",
    "core.files",
    "core.feedback",
    "core.extract",
    "core.knowledge",
    "core.search",
    "core.upload",
    "core.console",
}


CORE_MODULE_DEFINITIONS: tuple[ModuleDefinition, ...] = (
    ModuleDefinition(
        id="core.auth",
        name="Auth and password flow",
        layer="core",
        category="platform",
        description="Authentication, account session, password setup/reset, and current user profile.",
        backend_routes=("auth",),
        frontend_routes=("home", "reset-password", "setup-password"),
    ),
    ModuleDefinition(
        id="core.admin",
        name="Admin and RBAC",
        layer="core",
        category="platform",
        description="Users, roles, permissions, protected super admin account, and settings access.",
        backend_routes=("admin",),
        frontend_routes=("account", "settings"),
        permissions=(
            "admin.users.read",
            "admin.users.write",
            "admin.roles.manage",
            "admin.permissions.manage",
            "admin.settings.access",
        ),
    ),
    ModuleDefinition(
        id="core.chat",
        name="Chat workspace",
        layer="mixed",
        category="ai",
        description="Conversation history, chat orchestration, pinned/folder workflows, and domain hook handoff.",
        backend_routes=("chat",),
        frontend_routes=("home",),
        permissions=("admin.chat.access",),
    ),
    ModuleDefinition(
        id="core.projects",
        name="Projects",
        layer="core",
        category="workspace",
        description="Project folders, visibility, invitations, and conversation grouping.",
        backend_routes=("projects",),
        frontend_routes=("projects",),
        permissions=("admin.projects.access",),
    ),
    ModuleDefinition(
        id="core.files",
        name="File resources",
        layer="mixed",
        category="workspace",
        description="File resource storage and access control with legacy domain metadata fields.",
        backend_routes=("file_resources",),
        frontend_routes=("file-resources",),
        permissions=("admin.files.access",),
    ),
    ModuleDefinition(
        id="core.extract",
        name="Knowledge extraction",
        layer="core",
        category="ai",
        description="Document extraction jobs and RAG ingestion primitives.",
        backend_routes=("extract",),
    ),
    ModuleDefinition(
        id="core.knowledge",
        name="Knowledge management",
        layer="core",
        category="ai",
        description="Settings-managed RAG tables, company profile, and approved external site ingestion.",
        backend_routes=("knowledge",),
        frontend_routes=("settings",),
        permissions=("admin.settings.access",),
    ),
    ModuleDefinition(
        id="core.search",
        name="Search",
        layer="core",
        category="ai",
        description="Generic search endpoint used by AI retrieval flows.",
        backend_routes=("search",),
    ),
    ModuleDefinition(
        id="core.feedback",
        name="Feedback",
        layer="core",
        category="quality",
        description="Search and answer feedback capture for evaluation.",
        backend_routes=("feedback",),
    ),
    ModuleDefinition(
        id="core.upload",
        name="Upload",
        layer="core",
        category="workspace",
        description="Shared upload endpoint.",
        backend_routes=("upload",),
    ),
    ModuleDefinition(
        id="core.console",
        name="Console",
        layer="core",
        category="operations",
        description="Internal console assets and monitoring endpoints.",
        backend_routes=("console",),
    ),
)


def get_module_definitions() -> tuple[ModuleDefinition, ...]:
    return CORE_MODULE_DEFINITIONS + get_domain_module_definitions()


MODULE_DEFINITIONS = get_module_definitions()


def _split_env_list(value: str | None) -> set[str]:
    return {part.strip() for part in str(value or "").replace(";", ",").split(",") if part.strip()}


def _configured_enabled_ids(module_definitions: tuple[ModuleDefinition, ...]) -> set[str] | None:
    values = _split_env_list(os.getenv("YS_ENABLED_MODULES") or os.getenv("YS_CORE_ENABLED_MODULES"))
    if not values:
        return None
    modules_by_id = {module.id: module for module in module_definitions}
    expanded: set[str] = set()
    for value in values:
        if value == "core":
            expanded.update(CORE_MODULE_IDS)
        elif value == "domain":
            expanded.update(module.id for module in module_definitions if module.layer == "domain")
        elif value in modules_by_id:
            expanded.add(value)
    return expanded | CORE_MODULE_IDS


def get_enabled_module_ids() -> set[str]:
    module_definitions = get_module_definitions()
    enabled = _configured_enabled_ids(module_definitions)
    if enabled is None:
        enabled = {module.id for module in module_definitions}
    disabled = _split_env_list(os.getenv("YS_DISABLED_MODULES") or os.getenv("YS_CORE_DISABLED_MODULES"))
    expanded_disabled: set[str] = set()
    for value in disabled:
        if value == "domain":
            expanded_disabled.update(module.id for module in module_definitions if module.layer == "domain")
        elif value not in CORE_MODULE_IDS:
            expanded_disabled.add(value)
    enabled = enabled - expanded_disabled
    changed = True
    while changed:
        changed = False
        for module in module_definitions:
            if module.id not in enabled:
                continue
            if any(dependency not in enabled for dependency in module.dependencies):
                enabled.remove(module.id)
                changed = True
    return enabled


def is_module_enabled(module_id: str | None) -> bool:
    if not module_id:
        return True
    if module_id in CORE_MODULE_IDS:
        return True
    return module_id in get_enabled_module_ids()


def get_enabled_modules() -> list[ModuleDefinition]:
    enabled = get_enabled_module_ids()
    return [module for module in get_module_definitions() if module.id in enabled]


def _module_to_payload(module: ModuleDefinition, enabled: set[str]) -> dict[str, Any]:
    return {
        "id": module.id,
        "name": module.name,
        "layer": module.layer,
        "category": module.category,
        "description": module.description,
        "backend_routes": list(module.backend_routes),
        "frontend_routes": list(module.frontend_routes),
        "permissions": list(module.permissions),
        "dependencies": list(module.dependencies),
        "enabled": module.id in enabled,
        "metadata": module.metadata,
    }


def get_module_manifest() -> dict[str, Any]:
    module_definitions = get_module_definitions()
    enabled = get_enabled_module_ids()
    return {
        "modules": [_module_to_payload(module, enabled) for module in module_definitions],
        "enabled_module_ids": sorted(enabled),
        "core_module_ids": sorted(CORE_MODULE_IDS),
        "domain_module_ids": sorted(module.id for module in module_definitions if module.layer == "domain"),
        "domain_modules": [
            module.metadata.get("domain_module")
            for module in module_definitions
            if module.layer == "domain" and module.metadata.get("domain_module")
        ],
    }


def get_default_domain_profile() -> DomainProfile:
    profile = load_domain_profile_data() or get_store_profile()
    if not isinstance(profile, dict):
        profile = {}
    name = str(profile.get("name") or profile.get("brand") or "YS").strip() or "YS"
    description = str(profile.get("description") or profile.get("summary") or "").strip()
    return DomainProfile(
        id=str(profile.get("id") or "ys-default"),
        name=name,
        display_name=str(profile.get("display_name") or name),
        description=description,
        default_tone=str(profile.get("default_tone") or ""),
        metadata={
            key: value
            for key, value in profile.items()
            if key not in {"id", "name", "display_name", "description", "summary", "default_tone"}
        },
    )
