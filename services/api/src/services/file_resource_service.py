import re
from pathlib import Path
from typing import Optional
from uuid import UUID

from sqlalchemy import Select, and_, desc, false, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.file_resource import FileResource

_CERP_CODE_FAMILY_RE = re.compile(r"^(?P<prefix>.+)-(?P<suffix>\d{3})$")
_SCOPED_RESOURCE_TYPES = {"image", "document"}
_ALLOWED_VISIBILITIES = {"private", "public"}


def normalize_role_name(value: Optional[str]) -> str:
    return str(value or "").strip()


def normalize_visibility(value: Optional[str], default: str = "public") -> str:
    normalized_default = str(default or "public").strip().lower() or "public"
    if normalized_default not in _ALLOWED_VISIBILITIES:
        normalized_default = "public"
    normalized = str(value or "").strip().lower()
    if normalized in _ALLOWED_VISIBILITIES:
        return normalized
    return normalized_default


def is_scoped_file_resource_type(resource_type: Optional[str]) -> bool:
    return str(resource_type or "").strip().lower() in _SCOPED_RESOURCE_TYPES


def is_file_resource_accessible(
    resource_type: Optional[str],
    visibility: Optional[str],
    department_role: Optional[str],
    user_role: Optional[str],
) -> bool:
    if not is_scoped_file_resource_type(resource_type):
        return True
    normalized_visibility = normalize_visibility(visibility, default="public")
    if normalized_visibility == "public":
        return True
    normalized_department = normalize_role_name(department_role)
    normalized_user_role = normalize_role_name(user_role)
    return bool(normalized_department and normalized_user_role and normalized_department == normalized_user_role)


def normalize_cerp_code(value: Optional[str]) -> str:
    return str(value or "").strip().upper()


def extract_cerp_code_family(value: Optional[str]) -> str:
    normalized = normalize_cerp_code(value)
    if not normalized:
        return ""
    match = _CERP_CODE_FAMILY_RE.match(normalized)
    if not match:
        return normalized
    return match.group("prefix")


def derive_display_name(display_name: Optional[str], filename: Optional[str], fallback_name: Optional[str] = None) -> str:
    explicit = str(display_name or "").strip()
    if explicit:
        return explicit
    fallback = str(fallback_name or "").strip()
    if fallback:
        return fallback
    stem = Path(str(filename or "").strip()).stem
    return stem or "Untitled product label"


async def resolve_wine_label_resource(
    session: AsyncSession,
    cerp_code_full: Optional[str],
) -> Optional[FileResource]:
    normalized_code = normalize_cerp_code(cerp_code_full)
    if not normalized_code:
        return None

    exact_stmt = (
        select(FileResource)
        .where(
            FileResource.resource_type == "wine_label",
            FileResource.cerp_code_full == normalized_code,
        )
        .order_by(desc(FileResource.updated_at), desc(FileResource.created_at))
        .limit(1)
    )
    exact_result = await session.execute(exact_stmt)
    exact_match = exact_result.scalar_one_or_none()
    if exact_match:
        return exact_match

    family_code = extract_cerp_code_family(normalized_code)
    if not family_code:
        return None

    family_stmt = (
        select(FileResource)
        .where(
            FileResource.resource_type == "wine_label",
            FileResource.cerp_code_family == family_code,
        )
        .order_by(desc(FileResource.updated_at), desc(FileResource.created_at))
        .limit(1)
    )
    family_result = await session.execute(family_stmt)
    return family_result.scalar_one_or_none()


def build_file_resource_search_stmt(
    *,
    resource_type: str,
    keyword: str,
    user_role: Optional[str] = None,
) -> Select:
    stmt = select(FileResource).where(FileResource.resource_type == resource_type)
    if is_scoped_file_resource_type(resource_type):
        normalized_user_role = normalize_role_name(user_role)
        private_clause = false()
        if normalized_user_role:
            private_clause = and_(
                FileResource.visibility == "private",
                FileResource.department_role == normalized_user_role,
            )
        stmt = stmt.where(
            or_(
                FileResource.visibility == "public",
                private_clause,
            )
        )
    if keyword:
        pattern = f"%{keyword}%"
        stmt = stmt.where(
            or_(
                FileResource.display_name.ilike(pattern),
                FileResource.cerp_code_full.ilike(pattern),
                FileResource.cerp_code_family.ilike(pattern),
                FileResource.producer.ilike(pattern),
                FileResource.department_role.ilike(pattern),
                FileResource.attachment_filename.ilike(pattern),
            )
        )
    return stmt
