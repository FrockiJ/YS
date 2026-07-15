from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.auth import require_permissions
from ..core.config import UPLOAD_STORAGE_PATH
from ..core.models import Role
from ..core.database import SessionLocal
from ..models.file_resource import FileResource
from ..services.cerp_service import CerpService
from ..services.file_resource_service import (
    build_file_resource_search_stmt,
    derive_display_name,
    extract_cerp_code_family,
    is_file_resource_accessible,
    normalize_role_name,
    normalize_visibility,
    normalize_cerp_code,
    resolve_product_label_resource,
)

router = APIRouter(prefix="/file-resources", tags=["FileResources"])
require_file_resource_access = require_permissions("admin.files.access")

_RESOURCE_TYPE_PRODUCT_LABEL = "product_label"
_RESOURCE_TYPE_IMAGE = "image"
_RESOURCE_TYPE_DOCUMENT = "document"
_SUPPORTED_RESOURCE_TYPES = {
    _RESOURCE_TYPE_PRODUCT_LABEL,
    _RESOURCE_TYPE_IMAGE,
    _RESOURCE_TYPE_DOCUMENT,
}
_ALLOWED_PRODUCT_LABEL_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
_ALLOWED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
_ALLOWED_DOCUMENT_SUFFIXES = {
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".csv",
    ".ppt",
    ".pptx",
    ".txt",
}
_SORT_UPLOADED_DESC = "uploaded_desc"
_SORT_UPLOADED_ASC = "uploaded_asc"
_SORT_DISPLAY_NAME_ASC = "display_name_asc"
_SORT_DISPLAY_NAME_DESC = "display_name_desc"
_SORT_BRAND_ASC = "brand_asc"
_SORT_BRAND_DESC = "brand_desc"
_SORT_CERP_CODE_ASC = "cerp_code_full_asc"
_SORT_CERP_CODE_DESC = "cerp_code_full_desc"
_SORT_DEPARTMENT_ASC = "department_role_asc"
_SORT_DEPARTMENT_DESC = "department_role_desc"
_SORT_FILE_TYPE_ASC = "attachment_mime_asc"
_SORT_FILE_TYPE_DESC = "attachment_mime_desc"
_SORT_VISIBILITY_ASC = "visibility_asc"
_SORT_VISIBILITY_DESC = "visibility_desc"
_GROUP_BY_BRAND = "brand"
_GROUP_BY_DEPARTMENT = "department_role"

_ALLOWED_SORTS_BY_RESOURCE_TYPE = {
    _RESOURCE_TYPE_PRODUCT_LABEL: {
        _SORT_UPLOADED_DESC,
        _SORT_UPLOADED_ASC,
        _SORT_DISPLAY_NAME_ASC,
        _SORT_DISPLAY_NAME_DESC,
        _SORT_BRAND_ASC,
        _SORT_BRAND_DESC,
        _SORT_CERP_CODE_ASC,
        _SORT_CERP_CODE_DESC,
    },
    _RESOURCE_TYPE_IMAGE: {
        _SORT_UPLOADED_DESC,
        _SORT_UPLOADED_ASC,
        _SORT_DISPLAY_NAME_ASC,
        _SORT_DISPLAY_NAME_DESC,
        _SORT_DEPARTMENT_ASC,
        _SORT_DEPARTMENT_DESC,
        _SORT_FILE_TYPE_ASC,
        _SORT_FILE_TYPE_DESC,
        _SORT_VISIBILITY_ASC,
        _SORT_VISIBILITY_DESC,
    },
    _RESOURCE_TYPE_DOCUMENT: {
        _SORT_UPLOADED_DESC,
        _SORT_UPLOADED_ASC,
        _SORT_DISPLAY_NAME_ASC,
        _SORT_DISPLAY_NAME_DESC,
        _SORT_DEPARTMENT_ASC,
        _SORT_DEPARTMENT_DESC,
        _SORT_FILE_TYPE_ASC,
        _SORT_FILE_TYPE_DESC,
        _SORT_VISIBILITY_ASC,
        _SORT_VISIBILITY_DESC,
    },
}

cerp_service = CerpService()


async def get_db():
    async with SessionLocal() as session:
        yield session


def _resolve_upload_root() -> Path:
    base = Path(UPLOAD_STORAGE_PATH or "py/S3")
    if not base.is_absolute():
        base = Path.cwd() / base
    return base.resolve()


def _normalize_resource_type(value: str) -> str:
    normalized = str(value or _RESOURCE_TYPE_PRODUCT_LABEL).strip().lower() or _RESOURCE_TYPE_PRODUCT_LABEL
    if normalized not in _SUPPORTED_RESOURCE_TYPES:
        raise HTTPException(status_code=422, detail="Unsupported file resource type")
    return normalized


def _allowed_suffixes_for_resource_type(resource_type: str) -> set[str]:
    normalized = _normalize_resource_type(resource_type)
    if normalized == _RESOURCE_TYPE_PRODUCT_LABEL:
        return _ALLOWED_PRODUCT_LABEL_SUFFIXES
    if normalized == _RESOURCE_TYPE_IMAGE:
        return _ALLOWED_IMAGE_SUFFIXES
    return _ALLOWED_DOCUMENT_SUFFIXES


def _normalize_sort_tokens(resource_type: str, values: Optional[list[str]]) -> list[str]:
    normalized_resource_type = _normalize_resource_type(resource_type)
    allowed = _ALLOWED_SORTS_BY_RESOURCE_TYPE[normalized_resource_type]
    tokens = [str(item or "").strip().lower() for item in values or [] if str(item or "").strip()]
    if not tokens:
        return [_SORT_UPLOADED_DESC]
    invalid = [token for token in tokens if token not in allowed]
    if invalid:
        raise HTTPException(status_code=422, detail=f"Unsupported sort value: {', '.join(invalid)}")
    return tokens


def _normalize_group_by(resource_type: str, value: Optional[str]) -> Optional[str]:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return None
    if normalized == _GROUP_BY_BRAND and resource_type == _RESOURCE_TYPE_PRODUCT_LABEL:
        return normalized
    if normalized == _GROUP_BY_DEPARTMENT and resource_type in {_RESOURCE_TYPE_IMAGE, _RESOURCE_TYPE_DOCUMENT}:
        return normalized
    raise HTTPException(status_code=422, detail="Unsupported group_by value")


def _text_sort_expression(column):
    return func.lower(func.coalesce(column, ""))


def _visibility_sort_expression():
    return case((FileResource.visibility == "private", 1), else_=0)


def _sort_clause(token: str):
    if token == _SORT_UPLOADED_ASC:
        return FileResource.created_at.asc().nullslast()
    if token == _SORT_UPLOADED_DESC:
        return FileResource.created_at.desc().nullslast()
    if token == _SORT_DISPLAY_NAME_ASC:
        return _text_sort_expression(FileResource.display_name).asc()
    if token == _SORT_DISPLAY_NAME_DESC:
        return _text_sort_expression(FileResource.display_name).desc()
    if token == _SORT_BRAND_ASC:
        return _text_sort_expression(FileResource.brand).asc()
    if token == _SORT_BRAND_DESC:
        return _text_sort_expression(FileResource.brand).desc()
    if token == _SORT_CERP_CODE_ASC:
        return _text_sort_expression(FileResource.cerp_code_full).asc()
    if token == _SORT_CERP_CODE_DESC:
        return _text_sort_expression(FileResource.cerp_code_full).desc()
    if token == _SORT_DEPARTMENT_ASC:
        return _text_sort_expression(FileResource.department_role).asc()
    if token == _SORT_DEPARTMENT_DESC:
        return _text_sort_expression(FileResource.department_role).desc()
    if token == _SORT_FILE_TYPE_ASC:
        return _text_sort_expression(FileResource.attachment_mime).asc()
    if token == _SORT_FILE_TYPE_DESC:
        return _text_sort_expression(FileResource.attachment_mime).desc()
    if token == _SORT_VISIBILITY_ASC:
        return _visibility_sort_expression().asc()
    if token == _SORT_VISIBILITY_DESC:
        return _visibility_sort_expression().desc()
    raise HTTPException(status_code=422, detail=f"Unsupported sort value: {token}")


def _group_by_clause(group_by: Optional[str]):
    if group_by == _GROUP_BY_BRAND:
        return _text_sort_expression(FileResource.brand).asc()
    if group_by == _GROUP_BY_DEPARTMENT:
        return _text_sort_expression(FileResource.department_role).asc()
    return None


def _ensure_uploaded_file_path(raw_path: str, *, resource_type: str) -> Path:
    target = Path(str(raw_path or "").strip()).resolve()
    root = _resolve_upload_root()
    if root != target and root not in target.parents:
        raise HTTPException(status_code=422, detail="Attachment path is outside upload storage")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=422, detail="Uploaded attachment file was not found")
    if target.suffix.lower() not in _allowed_suffixes_for_resource_type(resource_type):
        if resource_type == _RESOURCE_TYPE_PRODUCT_LABEL:
            raise HTTPException(status_code=422, detail="Product label uploads must be image files")
        if resource_type == _RESOURCE_TYPE_IMAGE:
            raise HTTPException(status_code=422, detail="Image uploads must be image files")
        raise HTTPException(status_code=422, detail="Document uploads must use a supported file type")
    return target


async def _ensure_active_role_exists(session: AsyncSession, role_name: Optional[str]) -> str:
    normalized = normalize_role_name(role_name)
    if not normalized:
        raise HTTPException(status_code=422, detail="Department role is required")
    result = await session.execute(
        select(Role).where(Role.name == normalized, Role.is_active.is_(True))
    )
    role = result.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=422, detail="Department role not found")
    return str(role.name).strip()


def _normalize_payload_visibility(value: Optional[str]) -> str:
    return normalize_visibility(value, default="public")


def _ensure_resource_access(resource: FileResource, user: Dict[str, Any]) -> None:
    if is_file_resource_accessible(
        resource.resource_type,
        resource.visibility,
        resource.department_role,
        user.get("role"),
    ):
        return
    raise HTTPException(status_code=404, detail="File resource not found")


class UploadedAttachmentPayload(BaseModel):
    path: str
    filename: str
    mime: str
    size: Optional[int] = None


class ProductLabelCreatePayload(BaseModel):
    display_name: Optional[str] = None
    cerp_code_full: Optional[str] = None
    attachment: UploadedAttachmentPayload


class ProductLabelUpdatePayload(BaseModel):
    display_name: Optional[str] = None
    cerp_code_full: Optional[str] = None
    attachment: Optional[UploadedAttachmentPayload] = None


class SharedFileResourceCreatePayload(BaseModel):
    display_name: Optional[str] = None
    department_role: str
    visibility: str = "public"
    attachment: UploadedAttachmentPayload


class SharedFileResourceUpdatePayload(BaseModel):
    display_name: Optional[str] = None
    department_role: Optional[str] = None
    visibility: Optional[str] = None
    attachment: Optional[UploadedAttachmentPayload] = None


class FileResourceDepartmentListResponse(BaseModel):
    items: list[str] = Field(default_factory=list)


class FileResourceItem(BaseModel):
    id: str
    resource_type: str
    display_name: str
    brand: str = ""
    department_role: Optional[str] = None
    visibility: str = "public"
    attachment_filename: str
    attachment_mime: str
    attachment_size: Optional[int] = None
    cerp_code_full: Optional[str] = None
    cerp_code_family: Optional[str] = None
    created_by_username: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    preview_endpoint: str


class FileResourceListResponse(BaseModel):
    items: list[FileResourceItem] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 10


def _serialize_resource(resource: FileResource) -> FileResourceItem:
    return FileResourceItem(
        id=str(resource.id),
        resource_type=resource.resource_type,
        display_name=resource.display_name,
        brand=resource.brand or "",
        department_role=resource.department_role,
        visibility=normalize_visibility(resource.visibility, default="public"),
        attachment_filename=resource.attachment_filename,
        attachment_mime=resource.attachment_mime,
        attachment_size=resource.attachment_size,
        cerp_code_full=resource.cerp_code_full,
        cerp_code_family=resource.cerp_code_family,
        created_by_username=resource.created_by_username,
        created_at=resource.created_at.isoformat() if resource.created_at else None,
        updated_at=resource.updated_at.isoformat() if resource.updated_at else None,
        preview_endpoint=f"/api/file-resources/{resource.id}/preview",
    )


async def _get_file_resource_or_404(session: AsyncSession, resource_id: UUID) -> FileResource:
    result = await session.execute(select(FileResource).where(FileResource.id == resource_id))
    resource = result.scalar_one_or_none()
    if not resource:
        raise HTTPException(status_code=404, detail="File resource not found")
    return resource


def _require_product_label_create_code(raw_code: Optional[str]) -> str:
    normalized_code = normalize_cerp_code(raw_code)
    if not normalized_code:
        raise HTTPException(status_code=422, detail="cerp_code_full is required for product label creation")
    return normalized_code


async def _resolve_cerp_product(normalized_code: str) -> tuple[Optional[Dict[str, Any]], str, str]:
    if not normalized_code:
        return None, "", ""
    cerp_product = await cerp_service.fetch_product_info(normalized_code, None, strict_lookup=True)
    if not cerp_product:
        raise HTTPException(status_code=422, detail="CERP code not found")
    brand = str(cerp_product.get("brand") or cerp_product.get("supplier") or "").strip()
    fallback_display_name = str(
        cerp_product.get("name_ch") or cerp_product.get("name") or cerp_product.get("name_en") or ""
    ).strip()
    return cerp_product, brand, fallback_display_name


@router.get("", response_model=FileResourceListResponse)
async def list_file_resources(
    type: str = Query(default="product_label", alias="type"),
    q: str = Query(default="", max_length=200),
    sort: Optional[list[str]] = Query(default=None),
    group_by: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    user: Dict[str, Any] = Depends(require_file_resource_access),
    session: AsyncSession = Depends(get_db),
) -> FileResourceListResponse:
    resource_type = _normalize_resource_type(type)
    keyword = str(q or "").strip()
    normalized_sorts = _normalize_sort_tokens(resource_type, sort)
    normalized_group_by = _normalize_group_by(resource_type, group_by)

    base_stmt = build_file_resource_search_stmt(
        resource_type=resource_type,
        keyword=keyword,
        user_role=user.get("role"),
    )
    count_stmt = select(func.count()).select_from(base_stmt.subquery())
    order_clauses = []
    group_clause = _group_by_clause(normalized_group_by)
    if group_clause is not None:
        order_clauses.append(group_clause)
    order_clauses.extend(_sort_clause(token) for token in normalized_sorts)
    order_clauses.extend(
        [
            FileResource.updated_at.desc().nullslast(),
            FileResource.id.asc(),
        ]
    )
    list_stmt = (
        base_stmt.order_by(*order_clauses)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )

    result = await session.execute(list_stmt)
    count_result = await session.execute(count_stmt)
    items = result.scalars().all()
    total = int(count_result.scalar() or 0)
    return FileResourceListResponse(
        items=[_serialize_resource(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/product-labels", response_model=FileResourceItem, status_code=status.HTTP_201_CREATED)
async def create_product_label_resource(
    payload: ProductLabelCreatePayload,
    user: Dict[str, Any] = Depends(require_file_resource_access),
    session: AsyncSession = Depends(get_db),
) -> FileResourceItem:
    attachment_path = _ensure_uploaded_file_path(
        payload.attachment.path,
        resource_type=_RESOURCE_TYPE_PRODUCT_LABEL,
    )

    normalized_code = _require_product_label_create_code(payload.cerp_code_full)
    _, brand, fallback_display_name = await _resolve_cerp_product(normalized_code)

    resource = FileResource(
        resource_type=_RESOURCE_TYPE_PRODUCT_LABEL,
        display_name=derive_display_name(payload.display_name, payload.attachment.filename, fallback_display_name),
        brand=brand or None,
        visibility="public",
        attachment_path=str(attachment_path),
        attachment_filename=payload.attachment.filename,
        attachment_mime=payload.attachment.mime,
        attachment_size=payload.attachment.size,
        cerp_code_full=normalized_code or None,
        cerp_code_family=extract_cerp_code_family(normalized_code) or None,
        created_by_user_id=user.get("id"),
        created_by_username=str(user.get("username") or "").strip() or None,
    )
    session.add(resource)
    await session.commit()
    await session.refresh(resource)
    return _serialize_resource(resource)


async def _create_shared_file_resource(
    *,
    resource_type: str,
    payload: SharedFileResourceCreatePayload,
    user: Dict[str, Any],
    session: AsyncSession,
) -> FileResourceItem:
    normalized_resource_type = _normalize_resource_type(resource_type)
    attachment_path = _ensure_uploaded_file_path(
        payload.attachment.path,
        resource_type=normalized_resource_type,
    )
    department_role = await _ensure_active_role_exists(session, payload.department_role)
    resource = FileResource(
        resource_type=normalized_resource_type,
        display_name=derive_display_name(payload.display_name, payload.attachment.filename),
        department_role=department_role,
        visibility=_normalize_payload_visibility(payload.visibility),
        attachment_path=str(attachment_path),
        attachment_filename=payload.attachment.filename,
        attachment_mime=payload.attachment.mime,
        attachment_size=payload.attachment.size,
        created_by_user_id=user.get("id"),
        created_by_username=str(user.get("username") or "").strip() or None,
    )
    session.add(resource)
    await session.commit()
    await session.refresh(resource)
    return _serialize_resource(resource)


@router.post("/images", response_model=FileResourceItem, status_code=status.HTTP_201_CREATED)
async def create_image_resource(
    payload: SharedFileResourceCreatePayload,
    user: Dict[str, Any] = Depends(require_file_resource_access),
    session: AsyncSession = Depends(get_db),
) -> FileResourceItem:
    return await _create_shared_file_resource(
        resource_type=_RESOURCE_TYPE_IMAGE,
        payload=payload,
        user=user,
        session=session,
    )


@router.post("/documents", response_model=FileResourceItem, status_code=status.HTTP_201_CREATED)
async def create_document_resource(
    payload: SharedFileResourceCreatePayload,
    user: Dict[str, Any] = Depends(require_file_resource_access),
    session: AsyncSession = Depends(get_db),
) -> FileResourceItem:
    return await _create_shared_file_resource(
        resource_type=_RESOURCE_TYPE_DOCUMENT,
        payload=payload,
        user=user,
        session=session,
    )


@router.get("/departments", response_model=FileResourceDepartmentListResponse)
async def list_file_resource_departments(
    user: Dict[str, Any] = Depends(require_file_resource_access),
    session: AsyncSession = Depends(get_db),
) -> FileResourceDepartmentListResponse:
    result = await session.execute(
        select(Role.name).where(Role.is_active.is_(True)).order_by(Role.name.asc())
    )
    names = [str(name).strip() for name in result.scalars().all() if str(name).strip()]
    return FileResourceDepartmentListResponse(items=names)


@router.patch("/{resource_id}", response_model=FileResourceItem)
async def update_file_resource(
    resource_id: UUID,
    payload: ProductLabelUpdatePayload | SharedFileResourceUpdatePayload,
    user: Dict[str, Any] = Depends(require_file_resource_access),
    session: AsyncSession = Depends(get_db),
) -> FileResourceItem:
    resource = await _get_file_resource_or_404(session, resource_id)
    _ensure_resource_access(resource, user)

    if resource.resource_type != _RESOURCE_TYPE_PRODUCT_LABEL:
        attachment = payload.attachment
        if attachment:
            attachment_path = _ensure_uploaded_file_path(
                attachment.path,
                resource_type=resource.resource_type,
            )
            resource.attachment_path = str(attachment_path)
            resource.attachment_filename = attachment.filename
            resource.attachment_mime = attachment.mime
            resource.attachment_size = attachment.size
        if payload.department_role is not None:
            resource.department_role = await _ensure_active_role_exists(session, payload.department_role)
        if payload.visibility is not None:
            resource.visibility = _normalize_payload_visibility(payload.visibility)
        resource.display_name = derive_display_name(
            payload.display_name,
            resource.attachment_filename,
            resource.display_name,
        )
        await session.commit()
        await session.refresh(resource)
        return _serialize_resource(resource)

    normalized_code = normalize_cerp_code(payload.cerp_code_full or resource.cerp_code_full)
    _, brand, fallback_display_name = await _resolve_cerp_product(normalized_code)

    attachment = payload.attachment
    if attachment:
        attachment_path = _ensure_uploaded_file_path(
            attachment.path,
            resource_type=_RESOURCE_TYPE_PRODUCT_LABEL,
        )
        resource.attachment_path = str(attachment_path)
        resource.attachment_filename = attachment.filename
        resource.attachment_mime = attachment.mime
        resource.attachment_size = attachment.size

    resource.display_name = derive_display_name(
        payload.display_name,
        resource.attachment_filename,
        fallback_display_name or resource.display_name,
    )
    resource.brand = brand or None
    resource.cerp_code_full = normalized_code or None
    resource.cerp_code_family = extract_cerp_code_family(normalized_code) or None

    await session.commit()
    await session.refresh(resource)
    return _serialize_resource(resource)


@router.get("/{resource_id}", response_model=FileResourceItem)
async def get_file_resource(
    resource_id: UUID,
    user: Dict[str, Any] = Depends(require_file_resource_access),
    session: AsyncSession = Depends(get_db),
) -> FileResourceItem:
    resource = await _get_file_resource_or_404(session, resource_id)
    _ensure_resource_access(resource, user)
    return _serialize_resource(resource)


@router.delete("/{resource_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file_resource(
    resource_id: UUID,
    user: Dict[str, Any] = Depends(require_file_resource_access),
    session: AsyncSession = Depends(get_db),
):
    resource = await _get_file_resource_or_404(session, resource_id)
    _ensure_resource_access(resource, user)
    await session.delete(resource)
    await session.commit()


@router.get("/{resource_id}/preview")
async def preview_file_resource(
    resource_id: UUID,
    user: Dict[str, Any] = Depends(require_file_resource_access),
    session: AsyncSession = Depends(get_db),
):
    resource = await _get_file_resource_or_404(session, resource_id)
    _ensure_resource_access(resource, user)
    path = _ensure_uploaded_file_path(resource.attachment_path, resource_type=resource.resource_type)
    return FileResponse(path, media_type=resource.attachment_mime, filename=resource.attachment_filename)


@router.get("/resolve/by-code/{cerp_code}")
async def resolve_product_label_by_code(
    cerp_code: str,
    user: Dict[str, Any] = Depends(require_file_resource_access),
    session: AsyncSession = Depends(get_db),
):
    match = await resolve_product_label_resource(session, cerp_code)
    if not match:
        raise HTTPException(status_code=404, detail="File resource not found")
    return {"ok": True, "item": _serialize_resource(match).model_dump()}
