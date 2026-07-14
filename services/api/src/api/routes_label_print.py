from typing import Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel, Field

from ..core.auth import get_current_user_optional
from ..services.label_print_import_service import LabelPrintImportService
from ..services.label_print_service import LabelPrintService


router = APIRouter(tags=["LabelPrint"])

label_print_service = LabelPrintService()
label_print_import_service = LabelPrintImportService(label_print_service=label_print_service)


class LabelPrintAddRequest(BaseModel):
    code: str
    size: str = Field(..., pattern="^(small|medium|large)$")
    product_snapshot: Optional[Dict[str, Any]] = None


class LabelPrintItemPriceUpdateRequest(BaseModel):
    price_override: int = Field(..., ge=1)


def _require_user(user: Optional[dict]) -> dict:
    if not user or not user.get("id"):
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


@router.post("/labels/print-list/items")
async def add_print_item(
    payload: LabelPrintAddRequest,
    include_items: bool = False,
    user: Optional[dict] = Depends(get_current_user_optional),
):
    user = _require_user(user)
    result = await label_print_service.add_item(
        user["id"],
        payload.code,
        payload.size,
        product_snapshot=payload.product_snapshot,
    )
    if result.get("status") == "invalid":
        raise HTTPException(status_code=400, detail="invalid label item")
    total_quantity = await label_print_service.get_total_quantity(user["id"])
    if include_items:
        items = await label_print_service.list_items(user["id"])
        total_quantity = sum(item.get("quantity", 0) for item in items)
        return {"items": items, "total_quantity": total_quantity}
    return {"items": [], "total_quantity": total_quantity}


@router.get("/labels/print-list")
async def list_print_items(
    lang: str = "zh-TW",
    user: Optional[dict] = Depends(get_current_user_optional),
):
    user = _require_user(user)
    items = await label_print_service.list_items(user["id"], lang=lang)
    total_quantity = sum(item.get("quantity", 0) for item in items)
    return {"items": items, "total_quantity": total_quantity}


@router.delete("/labels/print-list/items/{item_id}")
async def delete_print_item(
    item_id: str,
    include_items: bool = False,
    user: Optional[dict] = Depends(get_current_user_optional),
):
    user = _require_user(user)
    removed = await label_print_service.delete_item(user["id"], item_id)
    if not removed:
        raise HTTPException(status_code=404, detail="item not found")
    total_quantity = await label_print_service.get_total_quantity(user["id"])
    if include_items:
        items = await label_print_service.list_items(user["id"])
        total_quantity = sum(item.get("quantity", 0) for item in items)
        return {"items": items, "total_quantity": total_quantity}
    return {"items": [], "total_quantity": total_quantity}


@router.get("/labels/print-list/count")
async def get_print_list_count(
    user: Optional[dict] = Depends(get_current_user_optional),
):
    user = _require_user(user)
    total_quantity = await label_print_service.get_total_quantity(user["id"])
    return {"total_quantity": total_quantity}


@router.patch("/labels/print-list/items/{item_id}")
async def update_print_item_price(
    item_id: str,
    payload: LabelPrintItemPriceUpdateRequest,
    user: Optional[dict] = Depends(get_current_user_optional),
):
    user = _require_user(user)
    record = await label_print_service.update_item_price_override(
        user["id"],
        item_id,
        price_override=payload.price_override,
    )
    if not record:
        raise HTTPException(status_code=404, detail="item not found")
    total_quantity = await label_print_service.get_total_quantity(user["id"])
    return {
        "id": str(record.id),
        "price_override": record.price_override,
        "total_quantity": total_quantity,
    }


@router.post("/labels/print-list/import")
async def import_print_items(
    file: UploadFile = File(...),
    lang: str = Form("zh-TW"),
    user: Optional[dict] = Depends(get_current_user_optional),
):
    user = _require_user(user)
    filename = (file.filename or "").lower()
    if not filename.endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Only .xlsx files are supported")
    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    try:
        result = await label_print_import_service.import_workbook(user["id"], payload, lang=lang)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return result


@router.delete("/labels/print-list")
async def reset_print_list(
    user: Optional[dict] = Depends(get_current_user_optional),
):
    user = _require_user(user)
    await label_print_service.reset_items(user["id"])
    return {"items": [], "total_quantity": 0}
