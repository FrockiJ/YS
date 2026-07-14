from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..services.cerp_service import CerpService
from ..services.label_description_service import LabelDescriptionService


router = APIRouter(tags=["Label"])

cerp_service = CerpService()
label_description_service = LabelDescriptionService()


class LabelDescriptionRegenerateRequest(BaseModel):
    code: str
    lang: str = "zh-TW"
    instruction: str | None = None
    price_override: int | None = Field(default=None, ge=1)


class LabelDescriptionUpdateRequest(BaseModel):
    code: str
    lang: str = "zh-TW"
    description: str
    price_override: int | None = Field(default=None, ge=1)


@router.get("/labels/description")
async def get_label_description(code: str, lang: str = "zh-TW"):
    normalized = (code or "").strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="code is required")

    record = await label_description_service.get_description_record(normalized, lang)
    if record:
        return {
            "code": normalized.upper(),
            "lang": lang,
            "description": record.description,
            "price_override": record.price_override,
        }

    product = await cerp_service.fetch_product_info(normalized, None, inventory_only=False, strict_lookup=True)
    if not product:
        raise HTTPException(status_code=404, detail="product not found")

    description = await label_description_service.ensure_description(product, lang)
    if not description:
        raise HTTPException(status_code=500, detail="description unavailable")

    return {
        "code": normalized.upper(),
        "lang": lang,
        "description": description,
        "price_override": None,
    }


@router.post("/labels/description/regenerate")
async def regenerate_label_description(payload: LabelDescriptionRegenerateRequest):
    normalized = (payload.code or "").strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="code is required")

    product = await cerp_service.fetch_product_info(normalized, None, inventory_only=False, strict_lookup=True)
    if not product:
        raise HTTPException(status_code=404, detail="product not found")

    description = await label_description_service.generate_description(
        product,
        payload.lang,
        instruction=payload.instruction,
        price_override=payload.price_override,
    )
    if not description:
        raise HTTPException(status_code=500, detail="description unavailable")

    return {
        "code": normalized.upper(),
        "lang": payload.lang,
        "description": description,
    }


@router.post("/labels/description/update")
async def update_label_description(payload: LabelDescriptionUpdateRequest):
    normalized = (payload.code or "").strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="code is required")
    if not payload.description or not payload.description.strip():
        raise HTTPException(status_code=400, detail="description is required")

    record = await label_description_service.upsert_description(
        normalized,
        payload.lang,
        payload.description,
        payload.price_override,
    )
    if not record:
        raise HTTPException(status_code=500, detail="description update failed")

    return {
        "code": normalized.upper(),
        "lang": payload.lang,
        "description": record.description,
        "price_override": record.price_override,
    }
