from __future__ import annotations

import importlib
import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..core.extensions import ModuleDefinition


DEFAULT_DOMAIN_MODULE = "ys_outdoor"


def _split_env_list(value: str | None) -> list[str]:
    return [part.strip() for part in str(value or "").replace(";", ",").split(",") if part.strip()]


def get_configured_domain_module_names() -> list[str]:
    configured = _split_env_list(os.getenv("YS_DOMAIN_MODULES") or os.getenv("YS_DOMAIN_MODULE"))
    return configured or [DEFAULT_DOMAIN_MODULE]


@lru_cache(maxsize=16)
def _load_manifest(module_name: str):
    normalized = str(module_name or "").strip()
    if not normalized:
        raise ValueError("Domain module name cannot be empty")
    return importlib.import_module(f".{normalized}.manifest", package=__package__)


def get_domain_module_manifests() -> list[Any]:
    manifests: list[Any] = []
    for module_name in get_configured_domain_module_names():
        try:
            manifests.append(_load_manifest(module_name))
        except ModuleNotFoundError as exc:
            raise RuntimeError(f"Domain module '{module_name}' could not be loaded") from exc
    return manifests


def get_domain_module_definitions() -> tuple[ModuleDefinition, ...]:
    definitions: list[ModuleDefinition] = []
    for manifest in get_domain_module_manifests():
        for module in getattr(manifest, "MODULE_DEFINITIONS", ()):
            if not isinstance(module, ModuleDefinition):
                raise TypeError(f"Invalid module definition in {manifest.__name__}: {module!r}")
            definitions.append(module)
    return tuple(definitions)


def _read_json_file(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Domain profile must be a JSON object: {path}")
    return payload


def load_domain_profile_data() -> dict[str, Any]:
    configured_path = str(os.getenv("YS_DOMAIN_PROFILE_PATH") or "").strip()
    if configured_path:
        return _read_json_file(Path(configured_path))

    for manifest in get_domain_module_manifests():
        profile_path = str(getattr(manifest, "DOMAIN_PROFILE_PATH", "") or "").strip()
        if profile_path:
            path = Path(profile_path)
            if not path.is_absolute():
                path = Path(getattr(manifest, "__file__", ".")).resolve().parent / path
            if path.exists():
                return _read_json_file(path)
        profile = getattr(manifest, "DOMAIN_PROFILE", None)
        if isinstance(profile, dict):
            return dict(profile)
    return {}


def get_chat_domain_hooks():
    for manifest in get_domain_module_manifests():
        factory = getattr(manifest, "get_chat_hooks", None)
        if callable(factory):
            hooks = factory()
            if hooks is not None:
                return hooks
    return None
