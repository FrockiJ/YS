from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ProductNeedProfilePatch(BaseModel):
    """Traceable product context fields; this model never decides routing."""

    activity: Optional[str] = None
    use_case: Optional[str] = None
    location: Optional[str] = None
    duration: Optional[str] = None
    party_size: Optional[int] = Field(default=None, ge=1, le=1000)
    weather: List[str] = Field(default_factory=list)
    budget: Optional[Dict[str, Any]] = None
    categories: List[str] = Field(default_factory=list)
    required_features: List[str] = Field(default_factory=list)
    excluded_features: List[str] = Field(default_factory=list)
    preferred_brands: List[str] = Field(default_factory=list)
    owned_gear: List[str] = Field(default_factory=list)
    quantity: Optional[int] = Field(default=None, ge=1, le=1000)


def merge_need_profile_patch(
    profile: Dict[str, Any],
    patch: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Merge planner/context data without adding aliases or deciding intent."""
    merged = dict(profile or {})
    list_fields = {
        "weather",
        "categories",
        "required_features",
        "excluded_features",
        "preferred_brands",
        "owned_gear",
    }
    for key, value in (patch or {}).items():
        if key in list_fields:
            existing = list(merged.get(key) or [])
            seen = {str(item).casefold() for item in existing}
            for item in value if isinstance(value, list) else []:
                normalized = str(item or "").strip()
                if normalized and normalized.casefold() not in seen:
                    existing.append(normalized)
                    seen.add(normalized.casefold())
            merged[key] = existing
        elif value not in (None, "", [], {}):
            merged[key] = value
    return merged
