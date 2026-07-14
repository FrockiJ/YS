from fastapi import APIRouter

from ..core.company_profile import build_system_display_name, fetch_company_profile_payload
from ..core.module_registry import get_default_domain_profile, get_module_manifest

router = APIRouter()


@router.get("/core/modules")
def read_core_modules():
    return get_module_manifest()


@router.get("/core/domain-profile")
async def read_domain_profile():
    profile = get_default_domain_profile()
    try:
        company_profile = await fetch_company_profile_payload()
    except Exception:
        company_profile = {}
    company_name = str(company_profile.get("company_name") or "").strip()
    system_display_name = build_system_display_name(company_name)
    return {
        "id": profile.id,
        "name": profile.name,
        "company_name": company_name,
        "system_display_name": system_display_name,
        "display_name": system_display_name,
        "description": profile.description,
        "default_tone": profile.default_tone,
        "metadata": {
            **profile.metadata,
            "company_profile": company_profile,
            "domain_display_name": profile.display_name,
        },
    }
