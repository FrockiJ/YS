from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Iterable, List, Mapping, Optional, Union

from sqlalchemy import select

from ..core.database import SessionLocal
from ..models.fake_cerp_product import FakeCerpProduct
from ..services.fake_cerp_pricing import resolve_fake_vip_price


class FakeCERPClient:
    """Local CERP-compatible client backed by fake_cerp_products."""

    @staticmethod
    def _normalize_paramchar(value: Optional[Mapping[str, Any]]) -> Dict[str, List[str]]:
        normalized: Dict[str, List[str]] = {}
        for key, raw in (value or {}).items():
            if raw is None:
                continue
            values = raw if isinstance(raw, list) else [raw]
            normalized[key] = [str(item).strip() for item in values if str(item or "").strip()]
        return normalized

    @staticmethod
    def _number(value: Any) -> float:
        try:
            return float(str(value or "0").replace(",", ""))
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _warehouse_row(product: FakeCerpProduct) -> Dict[str, Any]:
        return {
            "inv1002": "FAKE",
            "name002": "Fake Warehouse",
            "inv1015": int(product.stock or 0),
            "inv1016": 0,
        }

    @staticmethod
    def _brand_value(product: FakeCerpProduct) -> str:
        raw_row = product.raw_row or {}
        return str(raw_row.get("brand") or raw_row.get("supplier") or "").strip()

    @classmethod
    def _row(cls, product: FakeCerpProduct, *, include_warehouses: bool) -> Dict[str, Any]:
        amount = Decimal(product.amount or 0)
        vip_amount = resolve_fake_vip_price(amount)
        brand = cls._brand_value(product)
        raw_row = product.raw_row or {}
        photo_url = (
            raw_row.get("photo_url")
            or raw_row.get("photo")
            or raw_row.get("image_url")
            or ""
        )
        row = {
            "invn002": product.code,
            "invn005": product.name,
            "invn006": brand,
            "invn008": raw_row.get("barcode") or "",
            "invn013": float(amount),
            "invn015": float(vip_amount),
            "invn017": float(vip_amount),
            "invn030": raw_row.get("category") or "",
            "invn045": int(product.stock or 0),
            "invn051": product.spec1 or "",
            "invn077": product.name,
            "invn801": raw_row.get("color") or "",
            "invn802": raw_row.get("class") or raw_row.get("category") or "",
            "invn803": raw_row.get("material") or "",
            "invn804": raw_row.get("feature") or "",
            "invn805": raw_row.get("type") or "",
            "invn806": raw_row.get("size") or "",
            "invn807": raw_row.get("model_year") or product.spec1 or "",
            "brand": brand,
            "supplier": brand,
            "product_name": product.name,
            "model_year": raw_row.get("model_year") or product.spec1 or "",
            "category": raw_row.get("category") or "",
            "type": raw_row.get("type") or "",
            "material": raw_row.get("material") or "",
            "size": raw_row.get("size") or "",
            "color": raw_row.get("color") or "",
            "photo_url": photo_url,
            "spec": product.spec1 or "",
            "spec1": product.spec1 or "",
            "stock": int(product.stock or 0),
            "stock_qty": int(product.stock or 0),
            "total_stock": int(product.stock or 0),
            "amount": float(amount),
            "price": float(amount),
            "list_price": float(amount),
            "vip_price": float(vip_amount),
            "quote_price": float(vip_amount),
            "display_quote_price": float(vip_amount),
            "fake_cerp": True,
        }
        if include_warehouses:
            row["wd4inv1as"] = [cls._warehouse_row(product)]
        return row

    @classmethod
    def _matches_paramchar(cls, product: FakeCerpProduct, paramchar: Dict[str, List[str]]) -> bool:
        if not paramchar:
            return True
        raw_row = product.raw_row or {}
        haystacks = {
            "invn002": [product.code],
            "invn005": [product.name],
            "invn006": [
                str(raw_row.get("brand") or ""),
                str(raw_row.get("supplier") or ""),
            ],
            "invn008": [str(raw_row.get("barcode") or "")],
            "invn030": [str(raw_row.get("category") or "")],
            "invn051": [str(product.spec1 or "")],
        }
        for key, needles in paramchar.items():
            values = haystacks.get(key)
            if not values:
                continue
            lowered_values = [value.lower() for value in values if value]
            if not lowered_values:
                return False
            if not any(
                needle.lower() in value
                for needle in needles
                for value in lowered_values
            ):
                return False
        return True

    @classmethod
    def _filter_products(
        cls,
        products: Iterable[FakeCerpProduct],
        *,
        paramchar1: Optional[Mapping[str, Any]] = None,
        invn002b: Optional[str] = None,
        invn002e: Optional[str] = None,
        invn008b: Optional[str] = None,
        invn008e: Optional[str] = None,
        invn013b: Optional[Union[int, float]] = None,
        invn013e: Optional[Union[int, float]] = None,
    ) -> List[FakeCerpProduct]:
        paramchar = cls._normalize_paramchar(paramchar1)
        code_start = str(invn002b or "").strip().upper()
        code_end = str(invn002e or "").strip().upper()
        barcode_start = str(invn008b or "").strip()
        barcode_end = str(invn008e or "").strip()
        price_min = cls._number(invn013b) if invn013b is not None else None
        price_max = cls._number(invn013e) if invn013e is not None else None
        filtered: List[FakeCerpProduct] = []
        for product in products:
            code = str(product.code or "").upper()
            if code_start and code != code_start and code_start not in code:
                continue
            if code_end and code != code_end and code_end not in code:
                continue
            raw_row = product.raw_row or {}
            barcode = str(raw_row.get("barcode") or "")
            if barcode_start and barcode != barcode_start:
                continue
            if barcode_end and barcode != barcode_end:
                continue
            amount = cls._number(product.amount)
            if price_min is not None and amount < price_min:
                continue
            if price_max is not None and amount > price_max:
                continue
            if not cls._matches_paramchar(product, paramchar):
                continue
            filtered.append(product)
        return filtered

    @staticmethod
    def _paginate(items: List[Dict[str, Any]], page: Optional[int], perpage: Optional[int]) -> List[Dict[str, Any]]:
        limit = max(int(perpage or len(items) or 1), 1)
        current = max(int(page or 1), 1)
        start = (current - 1) * limit
        return items[start:start + limit]

    @staticmethod
    def _response(rows: List[Dict[str, Any]], *, total: int) -> Dict[str, Any]:
        warehouse_rows = [entry for row in rows for entry in (row.get("wd4inv1as") or [])]
        return {
            "status": "200",
            "data": {
                "wd4invnas": rows,
                "wd4inv1as": warehouse_rows,
                "count": len(rows),
                "totals": total,
            },
            "errors": [],
        }

    async def _all_products(self) -> List[FakeCerpProduct]:
        async with SessionLocal() as session:
            result = await session.execute(select(FakeCerpProduct).order_by(FakeCerpProduct.code.asc()))
            return list(result.scalars().all())

    async def export_products(
        self,
        *,
        custid: Optional[str] = None,
        supplier: Optional[str] = None,
        compid: Optional[str] = None,
        exprange: Optional[int] = None,
        lasttime: Optional[str] = None,
        paramchar1: Optional[Mapping[str, Any]] = None,
        invn002b: Optional[str] = None,
        invn002e: Optional[str] = None,
        invn053b: Optional[Union[int, float]] = None,
        invn053e: Optional[Union[int, float]] = None,
        invn013b: Optional[Union[int, float]] = None,
        invn013e: Optional[Union[int, float]] = None,
        page: Optional[int] = None,
        perpage: Optional[int] = None,
    ) -> Dict[str, Any]:
        products = self._filter_products(
            await self._all_products(),
            paramchar1=paramchar1,
            invn002b=invn002b,
            invn002e=invn002e,
            invn013b=invn013b,
            invn013e=invn013e,
        )
        rows = [self._row(product, include_warehouses=False) for product in products]
        return self._response(self._paginate(rows, page, perpage), total=len(rows))

    async def export_products_info(
        self,
        *,
        custid: Optional[str] = None,
        supplier: Optional[str] = None,
        compid: Optional[str] = None,
        exprange: Optional[int] = None,
        lasttime: Optional[str] = None,
        paramchar1: Optional[Mapping[str, Any]] = None,
        invn002b: Optional[str] = None,
        invn002e: Optional[str] = None,
        invn030b: Optional[str] = None,
        invn030e: Optional[str] = None,
        invn008b: Optional[str] = None,
        invn008e: Optional[str] = None,
        invn053b: Optional[Union[int, float]] = None,
        invn053e: Optional[Union[int, float]] = None,
        invn013b: Optional[Union[int, float]] = None,
        invn013e: Optional[Union[int, float]] = None,
        page: Optional[int] = None,
        perpage: Optional[int] = None,
    ) -> Dict[str, Any]:
        paramchar = self._normalize_paramchar(paramchar1)
        if invn030b:
            paramchar.setdefault("invn030", []).append(invn030b)
        if invn030e:
            paramchar.setdefault("invn030", []).append(invn030e)
        products = self._filter_products(
            await self._all_products(),
            paramchar1=paramchar,
            invn002b=invn002b,
            invn002e=invn002e,
            invn008b=invn008b,
            invn008e=invn008e,
            invn013b=invn013b,
            invn013e=invn013e,
        )
        rows = [self._row(product, include_warehouses=True) for product in products]
        return self._response(self._paginate(rows, page, perpage), total=len(rows))

    async def export_warehouses(
        self,
        *,
        custid: Optional[str] = None,
        supplier: Optional[str] = None,
        compid: Optional[str] = None,
        exprange: Optional[int] = None,
        lasttime: Optional[str] = None,
        paramchar1: Optional[Mapping[str, Any]] = None,
        inv1002b: Optional[str] = None,
        inv1002e: Optional[str] = None,
        inv1003b: Optional[str] = None,
        inv1003e: Optional[str] = None,
        page: Optional[int] = None,
        perpage: Optional[int] = None,
    ) -> Dict[str, Any]:
        products = await self._all_products()
        rows = [self._warehouse_row(product) for product in products if int(product.stock or 0) > 0]
        paginated_rows = self._paginate(rows, page, perpage)
        return {
            "status": "200",
            "data": {
                "wd4inv1as": paginated_rows,
                "count": len(paginated_rows),
                "totals": len(rows),
            },
            "errors": [],
        }
