import asyncio

from src.core.module_registry import (
    get_default_domain_profile,
    get_enabled_module_ids,
    get_module_manifest,
    is_module_enabled,
)
from src.core.company_profile import build_system_display_name
from src.api import routes_core


def test_module_registry_enables_current_ys_domain_by_default(monkeypatch):
    monkeypatch.delenv("YS_ENABLED_MODULES", raising=False)
    monkeypatch.delenv("YS_CORE_ENABLED_MODULES", raising=False)
    monkeypatch.delenv("YS_DISABLED_MODULES", raising=False)
    monkeypatch.delenv("YS_CORE_DISABLED_MODULES", raising=False)

    enabled = get_enabled_module_ids()

    assert "core.chat" in enabled
    assert "core.admin" in enabled
    assert "domain.cerp" in enabled
    assert "domain.quote" in enabled
    assert "domain.label" in enabled
    assert "domain.edm" in enabled
    assert is_module_enabled("domain.quote")


def test_module_registry_can_disable_domain_dependencies(monkeypatch):
    monkeypatch.delenv("YS_ENABLED_MODULES", raising=False)
    monkeypatch.delenv("YS_CORE_ENABLED_MODULES", raising=False)
    monkeypatch.setenv("YS_DISABLED_MODULES", "domain.cerp")
    monkeypatch.delenv("YS_CORE_DISABLED_MODULES", raising=False)

    enabled = get_enabled_module_ids()

    assert "core.chat" in enabled
    assert "domain.cerp" not in enabled
    assert "domain.quote" not in enabled
    assert "domain.edm" not in enabled
    assert "domain.label" in enabled


def test_module_manifest_marks_enabled_state(monkeypatch):
    monkeypatch.delenv("YS_ENABLED_MODULES", raising=False)
    monkeypatch.delenv("YS_CORE_ENABLED_MODULES", raising=False)
    monkeypatch.setenv("YS_DISABLED_MODULES", "domain")
    monkeypatch.delenv("YS_CORE_DISABLED_MODULES", raising=False)

    manifest = get_module_manifest()
    modules = {module["id"]: module for module in manifest["modules"]}

    assert modules["core.chat"]["enabled"] is True
    assert modules["domain.label"]["enabled"] is False
    assert modules["domain.quote"]["enabled"] is False
    assert modules["domain.label"]["metadata"]["domain_module"] == "ys_outdoor"


def test_domain_profile_comes_from_default_domain_module(monkeypatch):
    monkeypatch.delenv("YS_DOMAIN_PROFILE_PATH", raising=False)
    monkeypatch.delenv("YS_DOMAIN_MODULE", raising=False)
    monkeypatch.delenv("YS_DOMAIN_MODULES", raising=False)

    profile = get_default_domain_profile()

    assert profile.id == "ys-outdoor"
    assert profile.display_name == "YS"


def test_system_display_name_uses_company_name_or_generic_fallback():
    assert build_system_display_name("玉山戶外") == "玉山戶外系統"
    assert build_system_display_name("") == "企業系統"
    assert build_system_display_name(None) == "企業系統"


def test_core_domain_profile_exposes_company_system_name(monkeypatch):
    async def fake_company_profile():
        return {"company_name": "玉山戶外"}

    monkeypatch.setattr(routes_core, "fetch_company_profile_payload", fake_company_profile)

    payload = asyncio.run(routes_core.read_domain_profile())

    assert payload["company_name"] == "玉山戶外"
    assert payload["system_display_name"] == "玉山戶外系統"
    assert payload["display_name"] == "玉山戶外系統"
