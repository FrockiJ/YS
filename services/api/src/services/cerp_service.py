import asyncio
import logging
import re
from typing import Any, Dict, List, Optional

from ..cerpModule import CERPClient, CERPClientError, get_cerp_client
from ..core.config import (
    CERP_API_KEY_ID,
    CERP_BASE_URL,
    CERP_DEFAULT_COMP_ID,
    CERP_DEFAULT_CUST_ID,
    CERP_DEFAULT_SUPPLIER,
    CERP_TOKEN_REFRESH_BUFFER_SECONDS,
    CERP_TOKEN_TTL_SECONDS,
)
from ..utils.cerp_export_lookup import (
    find_export_row_by_barcode,
    find_export_row_by_code,
    find_best_matching_product,
    search_export_rows,
)
from ..utils.webphoto import lookup_product_photo

logger = logging.getLogger(__name__)

_PRODUCT_SEARCH_FIELDS = ("invn005", "invn006", "invn030", "invn051", "invn807")

_STORE_WAREHOUSE_KEYWORDS = ("精品", "門市", "門店", "店面", "retail", "boutique", "shop", "store")


class CerpService:
    """
    Lightweight wrapper around the CERP HTTP APIs for product lookup.
    Uses httpx.AsyncClient under the hood via CERPClient.
    """

    def __init__(self, client: Optional[CERPClient] = None) -> None:
        self._client = client or get_cerp_client()

    async def search_products(
        self,
        keyword: str,
        *,
        limit: int = 100,
        page_size: int = 50,
        desired_quantity: int = 1,
        raise_on_error: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Search CERP products by SKU, name, brand, category, or specification.
        """
        query = (keyword or "").strip()
        if not query:
            return []

        requested_limit = max(int(limit or 1), 1)
        # Fetch a full CERP page for ranking, but never let that internal page size
        # leak through the public API's explicit result limit.
        fetch_limit = max(requested_limit, page_size, 1)
        rows_by_code: Dict[str, Dict[str, Any]] = {}

        try:
            if self._is_code_query(query):
                rows_by_code.update(
                    await self._collect_rows_by_code(
                        query,
                        max_results=fetch_limit,
                        page_size=page_size,
                        max_pages=3,
                    )
                )
            rows_by_code.update(
                await self._collect_rows_by_keyword(
                    query,
                    max_results=fetch_limit,
                    page_size=page_size,
                    max_pages=3,
                )
            )
            if not rows_by_code:
                tokens = self._extract_query_tokens(query)
                for token in tokens[:3]:
                    if token == query:
                        continue
                    if self._is_code_query(token):
                        rows_by_code.update(
                            await self._collect_rows_by_code(
                                token,
                                max_results=fetch_limit,
                                page_size=page_size,
                                max_pages=2,
                            )
                        )
                    rows_by_code.update(
                        await self._collect_rows_by_keyword(
                            token,
                            max_results=fetch_limit,
                            page_size=page_size,
                            max_pages=2,
                        )
                    )
                    if len(rows_by_code) >= fetch_limit:
                        break
        except CERPClientError as exc:
            logger.warning("與 CERP 連線失敗, 請與系統管理者聯繫 (Connection failed: %s)", exc)
            if raise_on_error:
                raise

        if raise_on_error and rows_by_code:
            live_rows = await self._require_live_stock_for_rows(list(rows_by_code.values()))
            rows_by_code = {
                self._normalize_code(row.get("invn002")): row
                for row in live_rows
                if self._normalize_code(row.get("invn002"))
            }

        if query and self._is_code_query(query):
            exact_code = self._normalize_code(query)
            exact_row = rows_by_code.get(exact_code) or find_export_row_by_code(query) or find_export_row_by_barcode(query)
            if exact_row:
                exact_rows = await self._backfill_export_rows_with_live_stock(
                    [exact_row],
                    raise_on_error=raise_on_error,
                )
                exact_row = exact_rows[0] if exact_rows else exact_row
                mapped = self._map_row(exact_row, desired_quantity)
                if mapped:
                    return [mapped]

        products: List[Dict[str, Any]] = []
        scored_products: List[tuple[float, int, Dict[str, Any]]] = []
        for row in rows_by_code.values():
            mapped = self._map_row(row, desired_quantity)
            if not mapped:
                continue
            score = self._score_keyword(row, query) if query else 0.0
            if score <= 0:
                continue
            stock_qty = mapped.get("stock_qty", 0) or 0
            scored_products.append((score, stock_qty, mapped))

        if scored_products:
            scored_products.sort(key=lambda item: (item[0], item[1]), reverse=True)
            products = [item[2] for item in scored_products[:requested_limit]]

        if len(products) < requested_limit and query:
            fallback_rows = search_export_rows(query, limit=max(requested_limit * 2, fetch_limit))
            fallback_rows = await self._backfill_export_rows_with_live_stock(
                fallback_rows,
                raise_on_error=raise_on_error,
            )
            for row in fallback_rows:
                # Treat local export rows as candidates only. A returned row must
                # still contain the exact query subject in a searchable field.
                if self._score_keyword(row, query) <= 0:
                    continue
                code = self._normalize_code(row.get("invn002"))
                if not code:
                    continue
                if any(self._normalize_code(p.get("no")) == code for p in products):
                    continue
                mapped = self._map_row(row, desired_quantity)
                if not mapped:
                    continue
                products.append(mapped)
                if len(products) >= requested_limit:
                    break

        if products:
            return products[:requested_limit]
        return []

    async def _collect_rows_by_keyword(
        self,
        keyword: str,
        *,
        max_results: int,
        page_size: int,
        max_pages: int,
    ) -> Dict[str, Dict[str, Any]]:
        perpage = max(min(page_size, max_results), 1)
        page = 1
        rows_by_code: Dict[str, Dict[str, Any]] = {}
        while len(rows_by_code) < max_results and page <= max(1, max_pages):
            calls = []
            for field in _PRODUCT_SEARCH_FIELDS:
                paramchar = {field: [keyword]}
                calls.extend(
                    (
                        self._client.export_products(
                            custid=None,
                            supplier=None,
                            compid=None,
                            exprange=0,
                            paramchar1=paramchar,
                            perpage=perpage,
                            page=page,
                        ),
                        self._client.export_products_info(
                            custid=None,
                            supplier=None,
                            compid=None,
                            exprange=0,
                            paramchar1=paramchar,
                            perpage=perpage,
                            page=page,
                        ),
                    )
                )
            responses = await asyncio.gather(*calls)
            merged_rows: List[Dict[str, Any]] = []
            for index in range(0, len(responses), 2):
                merged_rows += self._merge_rows(responses[index], responses[index + 1])
            merged_rows = await self.enrich_product_rows(merged_rows, include_product_fields=False)
            if not merged_rows:
                break
            for row in merged_rows:
                code = self._normalize_code(row.get("invn002"))
                if not code:
                    continue
                rows_by_code[code] = row
            if len(rows_by_code) >= max_results:
                break
            if len(merged_rows) < perpage:
                break
            page += 1
        return rows_by_code

    async def _collect_rows_by_code(
        self,
        keyword: str,
        *,
        max_results: int,
        page_size: int,
        max_pages: int,
    ) -> Dict[str, Dict[str, Any]]:
        perpage = max(min(page_size, max_results), 1)
        page = 1
        rows_by_code: Dict[str, Dict[str, Any]] = {}
        code_paramchar = {"invn002": [keyword]}
        while len(rows_by_code) < max_results and page <= max(1, max_pages):
            products_response, info_response = await asyncio.gather(
                self._client.export_products(
                    custid=None,
                    supplier=None,
                    compid=None,
                    exprange=0,
                    paramchar1=code_paramchar,
                    perpage=perpage,
                    page=page,
                ),
                self._client.export_products_info(
                    custid=None,
                    supplier=None,
                    compid=None,
                    exprange=0,
                    paramchar1=code_paramchar,
                    perpage=perpage,
                    page=page,
                ),
            )
            merged_rows = await self.enrich_product_rows(
                self._merge_rows(products_response, info_response),
                include_product_fields=False,
            )
            if not merged_rows:
                break
            for row in merged_rows:
                code = self._normalize_code(row.get("invn002"))
                if not code:
                    continue
                rows_by_code[code] = row
            if len(rows_by_code) >= max_results:
                break
            if len(merged_rows) < perpage:
                break
            page += 1
        return rows_by_code

    def _merge_rows(self, products_response: Dict[str, Any], info_response: Dict[str, Any]) -> List[Dict[str, Any]]:
        rows: Dict[str, Dict[str, Any]] = {}
        for row in self._extract_rows(products_response):
            code = self._normalize_code(row.get("invn002"))
            if not code:
                continue
            rows[code] = dict(row)
        warehouse_rows = self._extract_warehouse_rows(info_response)
        warehouses_by_code = self._group_warehouses_by_code(warehouse_rows)
        for row in self._extract_rows(info_response):
            code = self._normalize_code(row.get("invn002"))
            if not code:
                continue
            existing = rows.get(code, {})
            merged = dict(existing)
            for key, value in row.items():
                if value not in (None, "", [], {}):
                    merged[key] = value
            merged["_cerp_stock_checked"] = True
            if warehouses_by_code.get(code):
                existing_wh = merged.get("wd4inv1as") or []
                if not isinstance(existing_wh, list):
                    existing_wh = []
                merged["wd4inv1as"] = existing_wh + warehouses_by_code[code]
            rows[code] = merged
        for code, row in rows.items():
            if not row.get("wd4inv1as") and warehouses_by_code.get(code):
                row["wd4inv1as"] = warehouses_by_code[code]
                row["_cerp_stock_checked"] = True
        return list(rows.values())

    @staticmethod
    def _extract_rows(response: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not isinstance(response, dict):
            return []
        data = response.get("data") or {}
        rows = data.get("wd4invnas") or []
        return rows if isinstance(rows, list) else []

    @staticmethod
    def _extract_warehouse_rows(response: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not isinstance(response, dict):
            return []
        data = response.get("data") or {}
        rows = data.get("wd4inv1as") or []
        return rows if isinstance(rows, list) else []

    def _group_warehouses_by_code(self, rows: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for entry in rows or []:
            code = self._normalize_code(
                entry.get("inv1003") or entry.get("invn002") or entry.get("invn008")
            )
            if not code:
                continue
            grouped.setdefault(code, []).append(entry)
        return grouped

    async def enrich_product_rows(
        self,
        rows: List[Dict[str, Any]],
        *,
        include_product_fields: bool = True,
    ) -> List[Dict[str, Any]]:
        if not rows:
            return []
        merged_rows = [dict(row) for row in rows if isinstance(row, dict)]
        codes = [self._normalize_code(row.get("invn002")) for row in merged_rows]
        codes = [code for code in dict.fromkeys(codes) if code]
        if not codes:
            return merged_rows

        product_rows_by_code: Dict[str, Dict[str, Any]] = {}
        if include_product_fields:
            product_rows_by_code = await self._fetch_product_rows_by_codes(codes)

        enriched: List[Dict[str, Any]] = []
        for row in merged_rows:
            code = self._normalize_code(row.get("invn002"))
            product_row = product_rows_by_code.get(code)
            merged = self._merge_product_rows(product_row, row) or dict(row)
            enriched.append(merged)
        return enriched

    async def _fetch_info_rows_by_codes(
        self,
        codes: List[str],
        *,
        raise_on_error: bool = False,
    ) -> Dict[str, Dict[str, Any]]:
        rows_by_code: Dict[str, Dict[str, Any]] = {}
        for chunk in self._chunk_values(codes, 100):
            try:
                response = await self._client.export_products_info(
                    custid=None,
                    supplier=None,
                    compid=None,
                    exprange=2,
                    paramchar1={"invn002": chunk},
                    perpage=min(max(len(chunk), 1), 100),
                )
            except CERPClientError:
                if raise_on_error:
                    raise
                continue
            for row in self._merge_rows({}, response):
                code = self._normalize_code(row.get("invn002"))
                if code:
                    row["_cerp_stock_checked"] = True
                    rows_by_code[code] = row
        return rows_by_code

    async def _backfill_export_rows_with_live_stock(
        self,
        rows: List[Dict[str, Any]],
        *,
        raise_on_error: bool = False,
    ) -> List[Dict[str, Any]]:
        export_rows = [dict(row) for row in rows if isinstance(row, dict)]
        codes = [self._normalize_code(row.get("invn002")) for row in export_rows]
        codes = [code for code in dict.fromkeys(codes) if code]
        if not codes:
            return export_rows
        info_rows_by_code = await self._fetch_info_rows_by_codes(codes, raise_on_error=raise_on_error)
        if raise_on_error:
            missing = [code for code in codes if code not in info_rows_by_code]
            if missing:
                raise CERPClientError(
                    f"CERP stock lookup returned no ExportProductsInfo rows for: {', '.join(missing[:5])}"
                )
        backfilled: List[Dict[str, Any]] = []
        for row in export_rows:
            code = self._normalize_code(row.get("invn002"))
            info_row = info_rows_by_code.get(code)
            if info_row:
                backfilled.append(self._merge_product_rows(row, info_row) or dict(info_row))
            else:
                backfilled.append(row)
        return backfilled

    async def _require_live_stock_for_rows(
        self,
        rows: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        ready_rows: List[Dict[str, Any]] = []
        rows_requiring_precise_stock: List[Dict[str, Any]] = []
        for row in rows:
            warehouses = row.get("wd4inv1as")
            if isinstance(warehouses, list) and warehouses:
                ready_rows.append(row)
            else:
                rows_requiring_precise_stock.append(row)
        if not rows_requiring_precise_stock:
            return rows
        backfilled = await self._backfill_export_rows_with_live_stock(
            rows_requiring_precise_stock,
            raise_on_error=True,
        )
        return ready_rows + backfilled

    async def _fetch_product_rows_by_codes(self, codes: List[str]) -> Dict[str, Dict[str, Any]]:
        rows_by_code: Dict[str, Dict[str, Any]] = {}
        for chunk in self._chunk_values(codes, 100):
            try:
                response = await self._client.export_products(
                    custid=None,
                    supplier=None,
                    compid=None,
                    exprange=2,
                    paramchar1={"invn002": chunk},
                    perpage=min(max(len(chunk), 1), 100),
                )
            except CERPClientError:
                continue
            for row in self._extract_rows(response):
                code = self._normalize_code(row.get("invn002"))
                if code:
                    rows_by_code[code] = row
        return rows_by_code

    @staticmethod
    def _chunk_values(values: List[str], size: int) -> List[List[str]]:
        return [values[index : index + size] for index in range(0, len(values), size)]

    @staticmethod
    def _normalize_code(code: Optional[str]) -> str:
        return code.strip().upper() if isinstance(code, str) else ""

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        if isinstance(value, str):
            cleaned = value.replace(",", "").strip()
            if not cleaned:
                return None
            try:
                return float(cleaned)
            except ValueError:
                return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _resolve_stock_qty(self, row: Dict[str, Any]) -> int:
        warehouse_rows = row.get("wd4inv1as") or []
        if warehouse_rows:
            total = 0.0
            for entry in warehouse_rows:
                qty = self._safe_float(entry.get("inv1015"))
                if qty is not None:
                    total += qty
            return max(int(total), 0)

        return 0

    @staticmethod
    def _warehouse_stock_value(row: Dict[str, Any]) -> float:
        warehouse_rows = row.get("wd4inv1as") or []
        if warehouse_rows:
            total = 0.0
            for entry in warehouse_rows:
                try:
                    total += float(str(entry.get("inv1015") or "0").replace(",", ""))
                except (TypeError, ValueError):
                    continue
            return max(total, 0.0)
        return 0.0

    @staticmethod
    def _normalize_text(value: Any) -> str:
        if not isinstance(value, str):
            return ""
        return re.sub(r"[^A-Za-z0-9\u4e00-\u9fff]+", "", value).lower()

    @staticmethod
    def _extract_tokens(value: str) -> List[str]:
        if not value:
            return []
        return [tok.lower() for tok in re.findall(r"[A-Za-z0-9]+", value)]

    def _extract_query_tokens(self, value: str) -> List[str]:
        if not value:
            return []
        tokens = [
            match.group(0).lower()
            for match in re.finditer(r"[A-Za-z0-9]+", value)
            if self._is_search_token_significant(match.group(0), value=value, start=match.start(), end=match.end())
        ]
        if tokens:
            return list(dict.fromkeys(tokens))
        # Fallback for CJK or mixed text: split on whitespace and punctuation
        cleaned = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]+", " ", value).strip()
        parts = [part for part in cleaned.split() if part and self._is_search_token_significant(part)]
        return list(dict.fromkeys(parts))

    @staticmethod
    def _is_search_token_significant(
        token: str,
        *,
        value: Optional[str] = None,
        start: Optional[int] = None,
        end: Optional[int] = None,
    ) -> bool:
        normalized = str(token or "").strip().lower()
        if not normalized:
            return False
        # Natural language list markers such as "1) 2) 3)" should not match CERP
        # product codes, model numbers, or prices.
        if normalized.isdigit() and len(normalized) < 4:
            if value is not None and start is not None and end is not None:
                previous_char = value[start - 1] if start > 0 else ""
                next_char = value[end] if end < len(value) else ""
                if previous_char == "-" or next_char == "-":
                    return True
            return False
        return True

    @staticmethod
    def _is_code_query(value: str) -> bool:
        if not value:
            return False
        cleaned = value.strip()
        if not re.match(r"^[A-Za-z0-9-]{4,}$", cleaned):
            return False
        return bool(re.search(r"\d", cleaned))

    def _score_keyword(self, row: Dict[str, Any], keyword: str) -> float:
        tokens = self._extract_query_tokens(keyword)
        fields = [
            row.get("invn006"),  # brand
            row.get("invn005"),  # product name
            row.get("invn077"),  # alt name
            row.get("invn002"),  # code
            row.get("invn008"),  # barcode
            row.get("invn030"),  # category/location
            row.get("invn051"),  # specification
            row.get("invn801"),  # color
            row.get("invn804"),  # feature
            row.get("invn805"),  # product type
        ]
        normalized_fields = [self._normalize_text(val) for val in fields if val]
        combined = "".join(normalized_fields)
        if not combined:
            return 0.0

        norm_kw = self._normalize_text(keyword)
        score = 0.0
        if norm_kw and norm_kw in combined:
            score += 3.0
        if tokens:
            matches = sum(1 for tok in tokens if tok in combined)
            if matches == 0:
                return 0.0
            score += float(matches)
        return score

    def _map_row(self, row: Dict[str, Any], default_quantity: int = 1) -> Optional[Dict[str, Any]]:
        code = self._normalize_code(row.get("invn002"))
        if not code:
            return None

        standard_price = self._safe_float(row.get("invn013"))
        vip_price = self._safe_float(row.get("invn015"))
        fb_price = self._safe_float(row.get("invn017"))
        wholesale_price = self._safe_float(row.get("invn808"))
        if wholesale_price is None:
            wholesale_price = self._safe_float(row.get("invn080"))
        margin = self._calculate_margin(standard_price, wholesale_price)
        margin_rate = self._calculate_margin_rate(standard_price, wholesale_price)
        stock_qty = self._resolve_stock_qty(row)
        raw_warehouses = row.get("wd4inv1as") or []
        warehouses = self._map_warehouses(raw_warehouses)
        store_stock = self._extract_store_stock(raw_warehouses)

        name_primary = row.get("invn005") or ""
        name_alt = row.get("invn077") or ""
        name_en = name_alt or name_primary
        name_ch = name_primary or name_alt
        specification = row.get("invn807") or row.get("invn051") or ""
        material = row.get("material") or row.get("invn803") or ""
        product_type = row.get("type") or row.get("invn805") or ""
        product_class = row.get("category") or row.get("invn802") or row.get("invn030") or ""
        brand = row.get("brand") or row.get("invn006") or ""

        return {
            "id": code,
            "no": code,
            "name_en": name_en,
            "name_ch": name_ch,
            "name": name_ch or name_en,
            "specification": specification,
            "brand": brand,
            "supplier": row.get("supplier") or brand,
            "price": standard_price,
            "list_price": standard_price,
            "region": row.get("invn030") or "",
            "category": product_class,
            "photo_url": row.get("photo_url") or row.get("photo") or row.get("image_url") or "",
            "vip_price": vip_price,
            "fb_price": fb_price,
            "wholesale_price": wholesale_price,
            "cost": wholesale_price,
            "margin": margin,
            "margin_rate": margin_rate,
            "display_quote_price": wholesale_price,
            "stock_qty": stock_qty,
            "stock": stock_qty,
            "total_stock": stock_qty,
            "store_stock": store_stock,
            "stock_source_type": "store_stock" if store_stock > 0 else "overall_stock",
            "stock_source_label": "Store stock" if store_stock > 0 else "Overall stock",
            "cerp_stock_reference": row.get("invn045"),
            "wd4inv1as": raw_warehouses,
            "warehouses": warehouses,
            "color": row.get("invn801") or "",
            "feature": row.get("invn804") or "",
            "type": product_type,
            "material": material,
            "size": row.get("size") or row.get("invn806") or "",
            "spec": row.get("spec") or row.get("spec1") or specification,
            "bundle": row.get("invn048") or "",
            "promo": row.get("invn048") or "",
            "capacity_ml": self._safe_float(row.get("invn806")),
            "quantity": max(int(default_quantity or 1), 1),
        }

    @staticmethod
    def _is_blank_value(value: Any) -> bool:
        if value is None:
            return True
        if isinstance(value, str) and not value.strip():
            return True
        if isinstance(value, (list, dict)) and not value:
            return True
        return False

    @classmethod
    def _calculate_margin(cls, price: Any, cost: Any) -> Optional[float]:
        price_value = cls._safe_float(price)
        cost_value = cls._safe_float(cost)
        if price_value is None or cost_value is None:
            return None
        return round(price_value - cost_value, 4)

    @classmethod
    def _calculate_margin_rate(cls, price: Any, cost: Any) -> Optional[float]:
        price_value = cls._safe_float(price)
        cost_value = cls._safe_float(cost)
        if price_value is None or cost_value is None or price_value == 0:
            return None
        return round((price_value - cost_value) / price_value, 6)

    @staticmethod
    def safe_float(value: Any) -> float:
        if isinstance(value, str):
            cleaned = value.replace(",", "").strip()
            if not cleaned:
                return 0.0
            try:
                return float(cleaned)
            except ValueError:
                return 0.0
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @classmethod
    def safe_int(cls, value: Any) -> int:
        return int(round(cls.safe_float(value)))

    @classmethod
    def _map_warehouses(cls, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        mapped = []
        for entry in rows or []:
            mapped.append(
                {
                    "warehouse_code": entry.get("inv1002") or "",
                    "location": "",
                    "quantity": cls.safe_int(entry.get("inv1015")),
                    "reserved": cls.safe_int(entry.get("inv1016")),
                    "lot": entry.get("inv1017") or "",
                    "note": entry.get("inv1049") or "",
                }
            )
        return mapped

    @classmethod
    def _extract_stock(cls, row: Dict[str, Any], warehouses: List[Dict[str, Any]]) -> int:
        if warehouses:
            stock_value = sum(cls.safe_float(entry.get("inv1015")) for entry in warehouses)
            return max(int(round(stock_value)), 0)
        return 0

    @classmethod
    def _extract_store_stock(cls, warehouses: List[Dict[str, Any]]) -> int:
        total = 0.0
        for entry in warehouses or []:
            if not isinstance(entry, dict):
                continue
            haystack = " ".join(
                str(entry.get(key) or "").strip().lower()
                for key in ("name002", "warehouse_name", "warehouseName", "location", "name", "note", "inv1049", "inv1002", "warehouse_code", "code")
            )
            if not any(keyword in haystack for keyword in _STORE_WAREHOUSE_KEYWORDS):
                continue
            total += cls.safe_float(entry.get("inv1015") or entry.get("quantity") or entry.get("stock_qty"))
        return max(int(round(total)), 0)

    @classmethod
    def _merge_product_rows(
        cls,
        product_row: Optional[Dict[str, Any]],
        info_row: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        if not product_row and not info_row:
            return None
        merged: Dict[str, Any] = {}
        for source in (info_row, product_row):
            if not source:
                continue
            for key, value in source.items():
                if cls._is_blank_value(value):
                    continue
                merged[key] = value
        return merged or None

    async def _refetch_precise_product_row(
        self, code: str, barcode: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        if not code:
            return None
        paramchar: Dict[str, Any] = {"invn002": [code], "invn005": [code]}
        if barcode:
            paramchar["invn008"] = [barcode]
        try:
            response = await self._client.export_products(
                custid=None,
                supplier=None,
                compid=None,
                exprange=2,
                paramchar1=paramchar,
                perpage=1,
            )
        except CERPClientError:
            return None
        data = response.get("data") or {}
        rows = data.get("wd4invnas") or []
        return rows[0] if rows else None

    async def fetch_product_info(
        self,
        code: Optional[str],
        barcode: Optional[str],
        *,
        inventory_only: bool = False,
        strict_lookup: bool = False,
    ) -> Optional[Dict[str, Any]]:
        if not code and not barcode:
            return None

        def _build_filters() -> Dict[str, Any]:
            payload: Dict[str, Any] = {}
            paramchar: Dict[str, Any] = {}
            if code:
                paramchar["invn002"] = [code]
            if barcode:
                payload["invn008b"] = barcode
                payload["invn008e"] = barcode
                paramchar["invn008"] = [barcode]
            if paramchar:
                payload["paramchar1"] = paramchar
            return payload

        info_rows: List[Dict[str, Any]] = []
        warehouse_rows: List[Dict[str, Any]] = []
        info_payload = _build_filters()
        try:
            info_response = await self._client.export_products_info(
                custid=None,
                supplier=None,
                compid=None,
                exprange=2,
                **info_payload,
                perpage=1,
            )
        except CERPClientError as exc:
            logger.warning(
                "CERP products_info request failed for code=%s barcode=%s, falling back to local export: %s",
                code,
                barcode,
                exc,
            )
        else:
            info_data = info_response.get("data") or {}
            info_rows = info_data.get("wd4invnas") or []
            warehouse_rows = info_data.get("wd4inv1as") or []

        info_row = info_rows[0] if info_rows else None

        product_row: Optional[Dict[str, Any]] = None
        if not inventory_only:
            product_payload = _build_filters()
            try:
                product_response = await self._client.export_products(
                    custid=None,
                    supplier=None,
                    compid=None,
                    exprange=2,
                    **product_payload,
                    perpage=1,
                )
            except CERPClientError as exc:
                logger.warning(
                    "CERP products request failed for code=%s barcode=%s, falling back to local export: %s",
                    code,
                    barcode,
                    exc,
                )
                product_row = None
            else:
                product_data = product_response.get("data") or {}
                product_rows = product_data.get("wd4invnas") or []
                product_row = product_rows[0] if product_rows else None

        merged_row = self._merge_product_rows(product_row, info_row)
        if not merged_row:
            fallback_row: Optional[Dict[str, Any]] = None
            if code:
                fallback_row = find_export_row_by_code(code)
            if not fallback_row and barcode:
                fallback_row = find_export_row_by_barcode(barcode)
            if fallback_row:
                merged_row = fallback_row
                warehouse_rows = []
            else:
                return None
        if code:
            merged_code = (merged_row.get("invn002") or "").strip().upper()
            requested_code = code.strip().upper()
            if merged_code != requested_code:
                fallback = find_export_row_by_code(requested_code)
                if fallback:
                    merged_row = fallback
                    warehouse_rows = []
                else:
                    precise_row = await self._refetch_precise_product_row(requested_code, barcode)
                    if precise_row:
                        merged_row = self._merge_product_rows(precise_row, info_row)
                        warehouse_rows = precise_row.get("wd4inv1as") or warehouse_rows
                    else:
                        return None
        if strict_lookup and merged_row:
            merged_code = (merged_row.get("invn002") or "").strip().upper()
            requested_code = (code or "").strip().upper()
            if requested_code and merged_code != requested_code:
                strict_fallback = find_export_row_by_code(requested_code)
                if strict_fallback:
                    merged_row = strict_fallback
                    merged_code = requested_code
        warehouses = warehouse_rows or merged_row.get("wd4inv1as") or []
        product = self.map_row_to_product(merged_row, warehouses)
        if product and not product.get("photo_url"):
            photo_url = await lookup_product_photo(
                merged_row.get("invn002") or "",
                merged_row.get("invn008"),
            )
            if photo_url:
                product["photo_url"] = photo_url
        return product

    @classmethod
    def map_row_to_product(
        cls, row: Dict[str, Any], warehouses: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        warehouse_rows = warehouses or row.get("wd4inv1as") or []
        stock = cls._extract_stock(row, warehouse_rows)
        store_stock = cls._extract_store_stock(warehouse_rows)
        mapped_warehouses = cls._map_warehouses(warehouse_rows)
        standard_price = cls._safe_float(row.get("invn013"))
        vip_price = cls._safe_float(row.get("invn015"))
        fb_price = cls._safe_float(row.get("invn017"))
        wholesale_price = cls._safe_float(row.get("invn808"))
        if wholesale_price is None:
            wholesale_price = cls._safe_float(row.get("invn080"))
        margin = cls._calculate_margin(standard_price, wholesale_price)
        margin_rate = cls._calculate_margin_rate(standard_price, wholesale_price)
        feature = row.get("invn804") or ""
        color = row.get("invn801") or ""
        bundle = row.get("invn048") or ""
        product_class = row.get("category") or row.get("invn802") or row.get("invn030") or ""
        material = row.get("material") or row.get("invn803") or ""
        product_type = row.get("type") or row.get("invn805") or ""
        specification = row.get("invn807") or row.get("invn051") or ""
        brand = row.get("brand") or row.get("invn006") or ""
        name_primary = row.get("invn005") or ""
        name_alt = row.get("invn077") or ""
        has_bundle = bool(str(bundle).strip())
        return {
            "no": row.get("invn002"),
            "barcode": row.get("invn008"),
            "specification": specification,
            "brand": brand,
            "supplier": row.get("supplier") or brand,
            "name": name_primary or name_alt,
            "name_en": name_alt or name_primary,
            "name_ch": name_primary or name_alt,
            "region": row.get("invn030") or "",
            "category": product_class,
            "photo_url": row.get("photo_url") or row.get("photo") or row.get("image_url") or "",
            "color": color,
            "feature": feature,
            "type": product_type,
            "material": material,
            "size": row.get("size") or row.get("invn806") or "",
            "spec": row.get("spec") or row.get("spec1") or specification,
            "stock": stock,
            "stock_qty": stock,
            "total_stock": stock,
            "store_stock": store_stock,
            "stock_source_type": "store_stock" if store_stock > 0 else "overall_stock",
            "stock_source_label": "Store stock" if store_stock > 0 else "Overall stock",
            "cerp_stock_reference": row.get("invn045"),
            "wd4inv1as": warehouse_rows,
            "warehouses": mapped_warehouses,
            "price": standard_price,
            "list_price": standard_price,
            "vip_price": vip_price,
            "fb_price": fb_price,
            "wholesale_price": wholesale_price,
            "cost": wholesale_price,
            "margin": margin,
            "margin_rate": margin_rate,
            "display_quote_price": wholesale_price,
            "bundle": bundle,
            "promo": bundle,
            "gift": has_bundle,
            "capacity_ml": cls._safe_float(row.get("invn806")),
            "photo_placeholder": "Photo placeholder (attach later)",
        }

    async def fetch_top_stock_products(
        self,
        limit: int = 10,
        brand: Optional[str] = None,
        allow_zero_stock: bool = False,
        raise_on_error: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Fetch products with stock > 0 and return top-N by stock.
        """
        perpage = min(100, max(limit * 3, 100))
        rows: List[Dict[str, Any]] = []

        try:
            info_response = await self._client.export_products_info(
                custid=None,
                supplier=None,
                compid=None,
                exprange=0,
                perpage=perpage,
                paramchar1={"invn006": [brand]} if brand else None,
            )
            info_data = info_response.get("data") or {}
            rows = info_data.get("wd4invnas") or []
        except CERPClientError:
            if raise_on_error:
                raise
            rows = []

        if allow_zero_stock and not rows:
            try:
                info_response = await self._client.export_products_info(
                    custid=None,
                    supplier=None,
                    compid=None,
                    exprange=0,
                    perpage=perpage,
                    paramchar1={"invn006": [brand]} if brand else None,
                )
                info_data = info_response.get("data") or {}
                rows = info_data.get("wd4invnas") or []
            except CERPClientError:
                if raise_on_error:
                    raise
                rows = []

        if not rows and not raise_on_error:
            try:
                product_response = await self._client.export_products(
                    custid=None,
                    supplier=None,
                    compid=None,
                    exprange=0,
                    perpage=perpage,
                    paramchar1={"invn006": [brand]} if brand else None,
                )
                product_data = product_response.get("data") or {}
                rows = product_data.get("wd4invnas") or []
            except CERPClientError:
                rows = []

        if allow_zero_stock and not rows and not raise_on_error:
            try:
                product_response = await self._client.export_products(
                    custid=None,
                    supplier=None,
                    compid=None,
                    exprange=0,
                    perpage=perpage,
                    paramchar1={"invn006": [brand]} if brand else None,
                )
                product_data = product_response.get("data") or {}
                rows = product_data.get("wd4invnas") or []
            except CERPClientError:
                rows = []

        rows = await self.enrich_product_rows(rows)
        positive_rows = [row for row in rows if self._stock_value(row) > 0]
        if not positive_rows:
            positive_rows = rows
        sorted_rows = sorted(positive_rows, key=self._stock_value, reverse=True)
        top_rows = sorted_rows[:limit]
        products: List[Dict[str, Any]] = []
        seen_codes = set()
        for row in top_rows:
            warehouses = row.get("wd4inv1as") or []
            product = self.map_row_to_product(row, warehouses)
            code = (product or {}).get("no")
            if code and code in seen_codes:
                continue
            if product and (product.get("stock") or 0) > 0:
                products.append(product)
                if code:
                    seen_codes.add(code)
        if not products:
            for row in top_rows:
                warehouses = row.get("wd4inv1as") or []
                product = self.map_row_to_product(row, warehouses)
                code = (product or {}).get("no")
                if code and code in seen_codes:
                    continue
                if product:
                    products.append(product)
                    if code:
                        seen_codes.add(code)
        return products

    @staticmethod
    def _stock_value(row: Dict[str, Any]) -> float:
        whs = row.get("wd4inv1as") or []
        if whs:
            total = 0.0
            for entry in whs:
                try:
                    total += float(str(entry.get("inv1015") or "0").replace(",", ""))
                except (TypeError, ValueError):
                    continue
            return max(total, 0.0)
        return 0.0

    @staticmethod
    def format_currency(value: Any) -> Optional[str]:
        try:
            amount = float(value)
        except (TypeError, ValueError):
            return None
        return f"${amount:,.0f}"

    @staticmethod
    def format_warehouse_summary(product: Dict[str, Any]) -> str:
        entries = []
        for warehouse in (product.get("warehouses") or [])[:3]:
            code = warehouse.get("warehouse_code") or warehouse.get("location") or "warehouse"
            details = []
            qty = warehouse.get("quantity")
            if qty is not None:
                details.append(f"qty {qty}")
            reserved = warehouse.get("reserved")
            if reserved is not None:
                details.append(f"reserved {reserved}")
            if not details:
                continue
            entries.append(f"{code} ({', '.join(details)})")
        return "; ".join(entries)

    def describe_product(self, product: Dict[str, Any]) -> str:
        if not product:
            return ""
        segments = []
        code = product.get("no")
        name = product.get("name")
        brand = product.get("brand")
        specification = product.get("specification") or product.get("spec")
        if code and name:
            segments.append(f"{code} - {name}")
        elif name:
            segments.append(name)
        elif code:
            segments.append(code)
        if brand:
            segments.append(f"Brand: {brand}")
        if specification:
            segments.append(f"Specification: {specification}")
        feature = product.get("feature")
        if feature:
            segments.append(f"Feature: {feature}")
        color = product.get("color")
        if color:
            segments.append(f"Color: {color}")
        price_parts = []
        for label, value in (
            ("Standard price", product.get("price")),
            ("VIP price", product.get("vip_price")),
            ("F&B price", product.get("fb_price")),
        ):
            formatted = self.format_currency(value)
            if formatted:
                price_parts.append(f"{label} {formatted}")
        if price_parts:
            segments.append(" / ".join(price_parts))
        stock = product.get("stock")
        if stock is not None:
            segments.append(f"Stock on hand: {stock}")
        promo = product.get("promo")
        if promo:
            segments.append(f"Promo: {promo}")
        if product.get("gift"):
            segments.append("Gift: includes 1+1")
        warehouse_summary = self.format_warehouse_summary(product)
        if warehouse_summary:
            segments.append(f"Warehouses: {warehouse_summary}")
        barcode = product.get("barcode")
        if barcode:
            segments.append(f"Barcode: {barcode}")
        return " / ".join(segments)
