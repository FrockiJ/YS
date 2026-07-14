from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from ..core.auth import get_current_active_admin_user
from ..core.config import YS_CERP_MODE
from ..cerpModule import CERPClientError, get_cerp_client, is_fake_cerp_mode
from ..services.cerp_service import CerpService
from ..services.fake_cerp_import_service import FakeCerpImportService
from ..services.label_description_service import LabelDescriptionService
from ..utils.cerp_export_lookup import find_export_row_by_code


router = APIRouter(tags=["CERP"])


class CERPRequestBase(BaseModel):
    custid: Optional[str] = None
    supplier: Optional[str] = None
    compid: Optional[str] = None


# Pydantic accepts a single value or list for each parameter key.
ParamCharType = Optional[Dict[str, Union[str, List[str]]]]


class ProductExportRequest(CERPRequestBase):
    exprange: Optional[int] = Field(0, ge=0, le=2)
    lasttime: Optional[datetime] = None
    paramchar1: ParamCharType = None
    invn002b: Optional[str] = None
    invn002e: Optional[str] = None
    producer: Optional[str] = None
    name: Optional[str] = None
    stock_min: Optional[float] = None
    stock_max: Optional[float] = None
    price_min: Optional[float] = None
    price_max: Optional[float] = None
    page: Optional[int] = Field(1, ge=1)
    perpage: Optional[int] = Field(100, ge=1, le=100)


class ProductInfoRequest(CERPRequestBase):
    exprange: Optional[int] = Field(0, ge=0, le=2)
    lasttime: Optional[datetime] = None
    paramchar1: ParamCharType = None
    invn002b: Optional[str] = None
    invn002e: Optional[str] = None
    invn030b: Optional[str] = None
    invn030e: Optional[str] = None
    invn008b: Optional[str] = None
    invn008e: Optional[str] = None
    producer: Optional[str] = None
    name: Optional[str] = None
    stock_min: Optional[float] = None
    stock_max: Optional[float] = None
    price_min: Optional[float] = None
    price_max: Optional[float] = None
    page: Optional[int] = Field(1, ge=1)
    perpage: Optional[int] = Field(100, ge=1, le=100)
    enrich_product_fields: bool = True


class ProductSearchRequest(BaseModel):
    query: str
    limit: Optional[int] = Field(20, ge=1, le=100)
    lang: Optional[str] = "zh-TW"


class WarehouseExportRequest(CERPRequestBase):
    exprange: Optional[int] = Field(0, ge=0, le=2)
    lasttime: Optional[datetime] = None
    paramchar1: ParamCharType = None
    inv1002b: Optional[str] = None
    inv1002e: Optional[str] = None
    inv1003b: Optional[str] = None
    inv1003e: Optional[str] = None
    page: Optional[int] = Field(1, ge=1)
    perpage: Optional[int] = Field(15, ge=1, le=15)


def _normalize_timestamp(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


cerp_client = get_cerp_client()

cerp_service = CerpService()
fake_cerp_import_service = FakeCerpImportService()
label_description_service = LabelDescriptionService()


def _default_cerp_schema() -> Dict[str, Any]:
    fake_mode = is_fake_cerp_mode()
    price_tiers = [
        {"id": "price", "label": "Price", "column": "price"},
        {"id": "vip", "label": "VIP Price", "column": "vip"},
    ]
    if not fake_mode:
        price_tiers.extend(
            [
                {"id": "restaurant", "label": "Restaurant", "column": "restaurant", "optional": True},
                {"id": "dealer", "label": "Dealer", "column": "dealer", "optional": True},
                {"id": "promo", "label": "Promo", "column": "promo", "optional": True},
            ]
        )
    return {
        "id": "ys-outdoor-fake-v1" if fake_mode else "ys-outdoor-live-v1",
        "mode": YS_CERP_MODE,
        "domain": "ys_outdoor",
        "product_kind": "equipment",
        "columns": [
            {"key": "no", "label": "Code", "source_keys": ["no", "code", "id", "invn002"], "type": "text", "width": 110, "default_visible": True, "required": True},
            {"key": "product", "label": "Product", "source_keys": ["product", "product_name", "name", "name_en", "name_ch", "invn077", "invn005", "title"], "type": "text", "width": 220, "default_visible": True, "required": True},
            {"key": "spec", "label": "Spec / Model", "source_keys": ["spec", "spec1", "model", "model_name", "invn051", "invn807"], "type": "text", "width": 130, "default_visible": True},
            {"key": "stock", "label": "Stock", "source_keys": ["stock", "stock_qty", "total_stock", "invn045"], "type": "number", "width": 80, "default_visible": True, "filter": "stock_status", "sort": True},
            {"key": "price", "label": "Price", "source_keys": ["list_price", "price", "amount", "invn013"], "type": "currency", "width": 110, "default_visible": True, "filter": "range", "sort": True},
            {"key": "vip", "label": "VIP Price", "source_keys": ["quote_price", "vip_price", "display_quote_price", "vip", "invn015", "amount", "invn013"], "type": "currency", "width": 110, "default_visible": True, "price_tier": "vip"},
            {"key": "producer", "label": "Brand / Supplier", "source_keys": ["producer", "brand", "supplier", "invn006"], "type": "text", "width": 130, "default_visible": False, "filter": "option"},
            {"key": "vintage", "label": "Model Year", "source_keys": ["model_year", "vintage", "invn807", "invn051"], "type": "text", "width": 100, "default_visible": False, "filter": "option"},
            {"key": "color", "label": "Color", "source_keys": ["color", "invn801"], "type": "text", "width": 90, "default_visible": False, "filter": "option"},
            {"key": "rating", "label": "Rating", "source_keys": ["rating", "invn804"], "type": "text", "width": 100, "default_visible": False, "filter": "range"},
            {"key": "bundle", "label": "Bundle", "source_keys": ["bundle", "promo", "invn048"], "type": "text", "width": 90, "default_visible": False},
        ],
        "default_visible_columns": ["no", "product", "spec", "stock", "price", "vip"],
        "filters": [
            {"id": "keyword", "field": "product", "type": "search", "label": "Keyword"},
            {"id": "stock", "field": "stock", "type": "stock_status", "label": "Stock"},
            {"id": "price", "field": "price", "type": "range", "label": "Price"},
            {"id": "spec", "field": "spec", "type": "option", "label": "Spec / Model"},
            {"id": "producer", "field": "producer", "type": "option", "label": "Brand / Supplier", "optional": True},
        ],
        "sort_fields": ["product", "spec", "stock", "price"],
        "price_tiers": price_tiers,
        "legacy_mappings": {
            "producer": "brand_or_supplier",
            "vintage": "model_year_or_spec",
            "invn002": "code",
            "invn005": "name",
            "invn051": "spec",
            "invn013": "price",
            "invn015": "quote_price",
        },
    }


@router.get("/schema")
async def read_cerp_schema() -> Dict[str, Any]:
    return _default_cerp_schema()


def _assert_status(response: Dict[str, Any]) -> None:
    status = response.get("status")
    if status is None:
        return
    if str(status).strip() != "200":
        raise HTTPException(
            status_code=502,
            detail={"message": "CERP indicated a failure", "status": status, "errors": response.get("errors")},
        )


def _raise_cerp_upstream_error(exc: CERPClientError) -> None:
    message = str(exc)
    status_code = 503 if "Missing CERP credential" in message else 502
    raise HTTPException(
        status_code=status_code,
        detail={"message": "CERP request failed", "error": message},
    )


def _fallback_row_by_code(requested_code: Optional[str]) -> Optional[Dict[str, Any]]:
    if not requested_code:
        return None
    return find_export_row_by_code(requested_code.strip())


def _ensure_code_consistency(response: Dict[str, Any], requested_code: Optional[str], clear_warehouses: bool = False) -> Dict[str, Any]:
    """
    If CERP returns a row whose invn002 does not match the requested code, replace it with the cached export row.
    """
    if not requested_code:
        return response
    data = response.get("data") or {}
    rows = data.get("wd4invnas") or []
    first = rows[0] if rows else None
    returned_code = (first.get("invn002") if isinstance(first, dict) else None) or ""
    if returned_code.strip().upper() == requested_code.strip().upper():
        return response

    fallback = _fallback_row_by_code(requested_code)
    if not fallback:
        return response

    if clear_warehouses:
        fallback = dict(fallback)
        fallback["wd4inv1as"] = []
    data["wd4invnas"] = [fallback]
    data["count"] = 1
    data["totals"] = 1
    response["data"] = data
    return response


def _extract_requested_code(payload: Union["ProductExportRequest", "ProductInfoRequest"]) -> Optional[str]:
    """
    Try to infer the intended product code from the payload (invn002b/e or paramchar1.invn002).
    """
    requested_code = getattr(payload, "invn002b", None) or getattr(payload, "invn002e", None)
    if requested_code:
        return requested_code
    paramchar1 = getattr(payload, "paramchar1", None) or {}
    if isinstance(paramchar1, dict):
        candidate = paramchar1.get("invn002") or paramchar1.get("invn005")
        if isinstance(candidate, list) and candidate:
            return str(candidate[0])
        if isinstance(candidate, str) and candidate.strip():
            return candidate
    return None


def _normalize_paramchar_lists(raw: Optional[Dict[str, Any]]) -> Dict[str, list]:
    """
    Ensure every paramchar value is a list so we can safely append search terms.
    """
    normalized: Dict[str, list] = {}
    if not isinstance(raw, dict):
        return normalized
    for key, value in raw.items():
        if value is None:
            continue
        if isinstance(value, list):
            normalized[key] = value[:]
        else:
            normalized[key] = [value]
    return normalized


def _merge_paramchar_with_search_terms(payload: Union["ProductExportRequest", "ProductInfoRequest"], base: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    paramchar = _normalize_paramchar_lists(base)
    producer = getattr(payload, "producer", None)
    if isinstance(producer, str) and producer.strip():
        paramchar.setdefault("invn006", []).append(producer.strip())
    name = getattr(payload, "name", None)
    if isinstance(name, str) and name.strip():
        paramchar.setdefault("invn005", []).append(name.strip())
    return paramchar


def _should_widen_exprange(payload: Union["ProductExportRequest", "ProductInfoRequest"]) -> bool:
    """
    When using producer/name/stock/price filters, we want CERP to allow a broader search (exprange=0)
    instead of forcing an exact single-row match (exprange=2).
    """
    return any(
        getattr(payload, field, None) not in (None, "", [], {})
        for field in ("producer", "name", "stock_min", "stock_max", "price_min", "price_max")
    )


def _sort_rows_by_stock(rows: list, warehouses_key: str = "wd4inv1as") -> list:
    """
    Sort product rows by CERP available stock from ExportProductsInfo warehouse inv1015 only.
    """
    def stock_value(row: Dict[str, Any]) -> float:
        whs = row.get(warehouses_key) or []
        if whs:
            total = 0.0
            for entry in whs:
                try:
                    total += float(str(entry.get("inv1015") or "0").replace(",", ""))
                except (TypeError, ValueError):
                    continue
            return max(total, 0.0)
        return 0.0

    filtered = [r for r in rows or [] if stock_value(r) > 0]
    if not filtered:
        filtered = rows or []
    return sorted(filtered, key=stock_value, reverse=True)


def _apply_stock_sorting(response: Dict[str, Any], perpage: Optional[int]) -> Dict[str, Any]:
    if not response:
        return response
    data = response.get("data") or {}
    rows = data.get("wd4invnas") or []
    if not rows or len(rows) <= 1:
        return response
    sorted_rows = _sort_rows_by_stock(rows)
    limit = max(1, int(perpage)) if perpage else len(sorted_rows)
    data["wd4invnas"] = sorted_rows[:limit]
    data["count"] = min(data.get("count") or len(sorted_rows), len(sorted_rows))
    data["totals"] = len(sorted_rows)
    response["data"] = data
    return response


def _stock_value_for_row(row: Dict[str, Any]) -> float:
    warehouses = row.get("wd4inv1as") or []
    if warehouses:
        total = 0.0
        for entry in warehouses:
            try:
                total += float(str(entry.get("inv1015") or "0").replace(",", ""))
            except (TypeError, ValueError):
                continue
        return max(total, 0.0)
    return 0.0


def _normalize_products_info_stock_fields(row: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(row)
    stock = max(int(_stock_value_for_row(normalized)), 0)
    normalized["stock_qty"] = stock
    normalized["stock"] = stock
    normalized["total_stock"] = stock
    normalized["warehouses"] = CerpService._map_warehouses(normalized.get("wd4inv1as") or [])
    if "invn045" in normalized:
        normalized["cerp_stock_reference"] = normalized.get("invn045")
    return normalized


def _apply_stock_filtering(
    response: Dict[str, Any],
    stock_min: Optional[float],
    stock_max: Optional[float],
) -> Dict[str, Any]:
    if stock_min is None and stock_max is None:
        return response
    data = response.get("data") or {}
    rows = data.get("wd4invnas") or []
    filtered = []
    for row in rows:
        try:
            stock = _stock_value_for_row(row)
        except (TypeError, ValueError):
            stock = 0.0
        if stock_min is not None and stock < stock_min:
            continue
        if stock_max is not None and stock > stock_max:
            continue
        filtered.append(row)
    data["wd4invnas"] = filtered
    data["count"] = len(filtered)
    data["totals"] = len(filtered)
    response["data"] = data
    return response


async def _enrich_products_info_response(response: Dict[str, Any]) -> Dict[str, Any]:
    data = response.get("data") if isinstance(response, dict) else None
    if not isinstance(data, dict):
        return response
    rows = data.get("wd4invnas") or []
    if not isinstance(rows, list) or not rows:
        return response
    enriched_rows = await cerp_service.enrich_product_rows(rows)
    data["wd4invnas"] = [_normalize_products_info_stock_fields(row) for row in enriched_rows]
    response["data"] = data
    return response


def _ensure_fake_cerp_enabled() -> None:
    if not is_fake_cerp_mode():
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Fake CERP is not enabled.",
                "mode": YS_CERP_MODE,
            },
        )


@router.get("/fake/status")
async def fake_cerp_status(_: dict = Depends(get_current_active_admin_user)) -> Dict[str, Any]:
    _ensure_fake_cerp_enabled()
    status = await fake_cerp_import_service.status()
    return {"mode": YS_CERP_MODE, **status}


@router.post("/fake/import")
async def import_fake_cerp_products(
    file: UploadFile = File(...),
    _: dict = Depends(get_current_active_admin_user),
) -> Dict[str, Any]:
    _ensure_fake_cerp_enabled()
    filename = str(file.filename or "").lower()
    if not filename.endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Only .xlsx files are supported")
    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    try:
        result = await fake_cerp_import_service.import_workbook(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"mode": YS_CERP_MODE, **result}


@router.post("/products")
async def export_products(payload: ProductExportRequest) -> Dict[str, Any]:
    # paramchar1 由呼叫端決定要用哪個欄位查詢；若未提供且有 invn002，就自動補 invn002。
    requested_code = _extract_requested_code(payload)
    effective_paramchar = _merge_paramchar_with_search_terms(payload, payload.paramchar1)
    if not effective_paramchar and requested_code:
        effective_paramchar = {"invn002": [requested_code]}

    # CERP 端要求 exprange=2 才會按照 paramchar 精準回傳單筆；若使用 producer/name/範圍查詢則放寬為 0。
    effective_exprange = (
        payload.exprange
        if payload.exprange is not None
        else (0 if _should_widen_exprange(payload) else 2)
    )

    try:
        response = await cerp_client.export_products(
            custid=payload.custid,
            supplier=payload.supplier,
            compid=payload.compid,
            exprange=effective_exprange,
            lasttime=_normalize_timestamp(payload.lasttime),
            paramchar1=effective_paramchar,
            invn002b=payload.invn002b,
            invn002e=payload.invn002e,
            invn013b=payload.price_min,
            invn013e=payload.price_max,
            page=payload.page,
            perpage=payload.perpage,
        )
    except CERPClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    _assert_status(response)
    requested_code = _extract_requested_code(payload)
    response = _ensure_code_consistency(response, requested_code, clear_warehouses=True)
    # 排序取庫存最多的在前
    return response


@router.post("/products/search")
async def search_products(
    payload: ProductSearchRequest,
    background_tasks: BackgroundTasks,
) -> Dict[str, Any]:
    query = (payload.query or "").strip()
    if not query:
        return {"items": [], "description_status": {}}

    limit = payload.limit or 20
    lang = payload.lang or "zh-TW"
    try:
        items = await cerp_service.search_products(query, limit=limit, raise_on_error=True)
    except CERPClientError as exc:
        _raise_cerp_upstream_error(exc)

    codes = [
        (item.get("no") or item.get("id") or item.get("invn002") or "").strip().upper()
        for item in items
    ]
    existing = await label_description_service.get_existing_descriptions(codes, lang)
    description_status = {
        code: ("ready" if code in existing else "pending")
        for code in codes
        if code
    }

    missing_products = []
    for item in items:
        code = (item.get("no") or item.get("id") or item.get("invn002") or "").strip().upper()
        if code and code not in existing:
            missing_products.append(item)
    if missing_products:
        background_tasks.add_task(
            label_description_service.generate_missing_descriptions,
            missing_products,
            lang,
        )

    return {"items": items, "description_status": description_status}


@router.post("/warehouses")
async def export_warehouses(payload: WarehouseExportRequest) -> Dict[str, Any]:
    try:
        response = await cerp_client.export_warehouses(
            custid=payload.custid,
            supplier=payload.supplier,
            compid=payload.compid,
            exprange=payload.exprange,
            lasttime=_normalize_timestamp(payload.lasttime),
            paramchar1=payload.paramchar1,
            inv1002b=payload.inv1002b,
            inv1002e=payload.inv1002e,
            inv1003b=payload.inv1003b,
            inv1003e=payload.inv1003e,
            page=payload.page,
            perpage=payload.perpage,
    )
    except CERPClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    _assert_status(response)
    return response


@router.post("/products/info")
async def export_products_info(payload: ProductInfoRequest) -> Dict[str, Any]:
    # paramchar1 由呼叫端決定要用哪個欄位查詢；若未提供且有 invn002，就自動補 invn002。
    requested_code = _extract_requested_code(payload)
    effective_paramchar = _merge_paramchar_with_search_terms(payload, payload.paramchar1)
    if not effective_paramchar and requested_code:
        effective_paramchar = {"invn002": [requested_code]}

    # CERP 端要求 exprange=2 才會按照 paramchar 精準回傳單筆；若使用 producer/name/範圍查詢則放寬為 0。
    effective_exprange = (
        payload.exprange
        if payload.exprange is not None
        else (0 if _should_widen_exprange(payload) else 2)
    )

    try:
        response = await cerp_client.export_products_info(
            custid=payload.custid,
            supplier=payload.supplier,
            compid=payload.compid,
            exprange=effective_exprange,
            lasttime=_normalize_timestamp(payload.lasttime),
            paramchar1=effective_paramchar,
            invn002b=payload.invn002b,
            invn002e=payload.invn002e,
            invn030b=payload.invn030b,
            invn030e=payload.invn030e,
            invn008b=payload.invn008b,
            invn008e=payload.invn008e,
            invn013b=payload.price_min,
            invn013e=payload.price_max,
            page=payload.page,
            perpage=payload.perpage,
        )
    except CERPClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    _assert_status(response)
    response = _ensure_code_consistency(response, requested_code, clear_warehouses=False)
    if payload.enrich_product_fields:
        response = await _enrich_products_info_response(response)
    response = _apply_stock_filtering(response, payload.stock_min, payload.stock_max)
    # 排序取庫存最多的在前
    response = _apply_stock_sorting(response, payload.perpage)
    return response
