from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from ...cerpModule import CERPClientError
from ..cerp_service import CerpService

logger = logging.getLogger(__name__)

_SUPPORTED_OPERATIONS = {"inventory_lookup", "brand_catalog", "product_lookup"}


class ProductFactLookupService:
    """Read product facts from CERP without asking an LLM to invent them."""

    def __init__(self, cerp_service: Optional[CerpService] = None) -> None:
        self._cerp = cerp_service or CerpService()

    async def lookup(self, operation: str, query: str, language: str) -> Dict[str, Any]:
        normalized_operation = str(operation or "").strip()
        # Preserve the caller-provided subject. This service never expands,
        # translates, or infers a new ERP query from generated answer text.
        traceable_query = str(query or "").strip()
        timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        if normalized_operation not in _SUPPORTED_OPERATIONS:
            raise ValueError(f"Unsupported ERP lookup operation: {normalized_operation}")
        if not traceable_query:
            raise ValueError("ERP lookup query must be a non-empty traceable input")

        try:
            candidates = await self._search(traceable_query)
            products = [
                product
                for product in candidates
                if isinstance(product, dict) and self._matches_subject(product, traceable_query)
            ]
            # A traceable subject can span ERP fields, for example a brand plus
            # a category ("bombada釣竿"). If the full phrase does not match a
            # single search field, retry only with literal tokens copied from
            # the same user-provided query and require every token afterwards.
            terms = self._traceable_terms(traceable_query)
            if not products and len(terms) > 1:
                merged = list(candidates)
                seen = {self._sku(product).casefold() for product in merged if self._sku(product)}
                for term in terms:
                    for product in await self._search(term):
                        sku = self._sku(product)
                        if sku and sku.casefold() in seen:
                            continue
                        if sku:
                            seen.add(sku.casefold())
                        merged.append(product)
                candidates = merged
                products = [
                    product
                    for product in candidates
                    if isinstance(product, dict) and self._matches_terms(product, terms)
                ]
        except CERPClientError as exc:
            logger.warning("CERP product fact lookup failed for %r: %s", traceable_query, exc)
            return self._error_result(normalized_operation, traceable_query, language, timestamp)
        except Exception:
            logger.exception("Unexpected CERP product fact lookup failure for %r", traceable_query)
            return self._error_result(normalized_operation, traceable_query, language, timestamp)

        if not products:
            return {
                "text": self._no_matches_text(traceable_query, language),
                "product_results": [],
                "erp_lookup": {
                    "operation": normalized_operation,
                    "query": traceable_query,
                    "status": "no_matches",
                    "matched_product_count": 0,
                    "timestamp": timestamp,
                    "data_quality_status": "not_applicable",
                },
            }

        truncated = len(candidates) >= 200
        if normalized_operation == "brand_catalog":
            return self._brand_catalog(products, traceable_query, language, timestamp, truncated=truncated)
        if normalized_operation == "inventory_lookup":
            return self._inventory_lookup(products, traceable_query, language, timestamp, truncated=truncated)
        return self._product_lookup(products, traceable_query, language, timestamp, truncated=truncated)

    async def _search(self, query: str) -> List[Dict[str, Any]]:
        return await self._cerp.search_products(
            query,
            limit=200,
            page_size=100,
            raise_on_error=True,
        )

    def _inventory_lookup(
        self,
        products: Sequence[Dict[str, Any]],
        query: str,
        language: str,
        timestamp: str,
        *,
        truncated: bool = False,
    ) -> Dict[str, Any]:
        total_stock = sum(self._stock(product) for product in products)
        return {
            "text": self._inventory_text(query, len(products), total_stock, language),
            "product_results": [
                self._to_product_result(product, "inventory_lookup", query, language, timestamp)
                for product in products[:6]
            ],
            "erp_lookup": {
                "operation": "inventory_lookup",
                "query": query,
                "status": "used",
                "matched_product_count": len(products),
                "timestamp": timestamp,
                "total_stock": total_stock,
                "data_quality_status": "complete",
                "truncated": truncated,
            },
        }

    def _brand_catalog(
        self,
        products: Sequence[Dict[str, Any]],
        query: str,
        language: str,
        timestamp: str,
        *,
        truncated: bool = False,
    ) -> Dict[str, Any]:
        grouped: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {"product_count": 0, "in_stock_product_count": 0, "total_stock": 0}
        )
        display_names: Dict[str, str] = {}
        brand_missing_count = 0
        for product in products:
            brand = self._trusted_brand(product)
            if not brand:
                brand_missing_count += 1
                continue
            key = brand.casefold()
            display_names.setdefault(key, brand)
            stock = self._stock(product)
            grouped[key]["product_count"] += 1
            grouped[key]["in_stock_product_count"] += int(stock > 0)
            grouped[key]["total_stock"] += stock

        brands = [
            {"brand": display_names[key], **counts}
            for key, counts in sorted(grouped.items(), key=lambda item: display_names[item[0]].casefold())
        ]
        if not brands:
            status = "brand_missing"
            quality = "brand_missing_truncated" if truncated else "brand_missing"
        elif brand_missing_count:
            status = "used"
            quality = "partial_brand_missing_truncated" if truncated else "partial_brand_missing"
        else:
            status = "used"
            quality = "partial_result_limit" if truncated else "complete"

        return {
            "text": self._brand_text(
                query,
                product_count=len(products),
                brands=brands,
                brand_missing_count=brand_missing_count,
                language=language,
            ),
            "product_results": [
                self._to_product_result(product, "brand_catalog", query, language, timestamp)
                for product in products[:6]
            ],
            "erp_lookup": {
                "operation": "brand_catalog",
                "query": query,
                "status": status,
                "matched_product_count": len(products),
                "timestamp": timestamp,
                "brands": brands,
                "brand_missing_count": brand_missing_count,
                "data_quality_status": quality,
                "truncated": truncated,
            },
        }

    def _product_lookup(
        self,
        products: Sequence[Dict[str, Any]],
        query: str,
        language: str,
        timestamp: str,
        *,
        truncated: bool = False,
    ) -> Dict[str, Any]:
        return {
            "text": self._product_text(query, len(products), language),
            "product_results": [
                self._to_product_result(product, "product_lookup", query, language, timestamp)
                for product in products[:6]
            ],
            "erp_lookup": {
                "operation": "product_lookup",
                "query": query,
                "status": "used",
                "matched_product_count": len(products),
                "timestamp": timestamp,
                "data_quality_status": "partial_result_limit" if truncated else "complete",
                "truncated": truncated,
            },
        }

    def _to_product_result(
        self,
        product: Dict[str, Any],
        operation: str,
        query: str,
        language: str,
        timestamp: str,
    ) -> Dict[str, Any]:
        stock = self._stock(product)
        brand = self._trusted_brand(product)
        return {
            "sku": self._first(product, "no", "sku", "code", "id", "invn002"),
            "name": self._first(product, "name", "product_name", "name_ch", "name_en", "invn005"),
            "brand": brand,
            "category": self._first(product, "category", "type", "invn802", "invn030"),
            "specification": self._first(
                product,
                "specification",
                "spec",
                "spec1",
                "model",
                "model_name",
                "model_year",
                "invn807",
                "invn051",
                "size",
            ),
            "price": product.get("price") if product.get("price") is not None else product.get("list_price"),
            "stock": stock,
            "recommendation_reason": self._reason(product, operation, query, language, stock, brand),
            "matched_requirements": [f"erp_operation:{operation}", "erp_subject_match"],
            "source_timestamp": timestamp,
        }

    def _reason(
        self,
        product: Dict[str, Any],
        operation: str,
        query: str,
        language: str,
        stock: int,
        brand: str,
    ) -> str:
        locale = self._locale(language)
        name = self._first(product, "name", "product_name", "name_ch", "name_en", "invn005")
        sku = self._first(product, "no", "sku", "code", "id", "invn002")
        identity = name or sku
        if locale == "en":
            if operation == "inventory_lookup":
                return f'ERP product {identity} matches "{query}"; current stock is {stock}.'
            if operation == "brand_catalog":
                brand_fact = f"ERP brand: {brand}" if brand else "ERP does not provide a brand for this product"
                return f'This ERP product matches the "{query}" category; {brand_fact}.'
            return f'ERP product {identity} matches the requested subject "{query}".'
        if locale == "ja":
            if operation == "inventory_lookup":
                return f'ERP 商品「{identity}」は「{query}」に一致し、現在の在庫は {stock} 点です。'
            if operation == "brand_catalog":
                brand_fact = f"ERP ブランドは {brand} です" if brand else "ERP にブランド情報がありません"
                return f'この ERP 商品は「{query}」カテゴリに一致し、{brand_fact}。'
            return f'ERP 商品「{identity}」は照会対象「{query}」に一致します。'
        if operation == "inventory_lookup":
            return f'ERP 商品「{identity}」符合「{query}」，目前庫存為 {stock} 件。'
        if operation == "brand_catalog":
            brand_fact = f"ERP 品牌為 {brand}" if brand else "ERP 未提供此商品的品牌資料"
            return f'此 ERP 商品符合「{query}」分類；{brand_fact}。'
        return f'ERP 商品「{identity}」符合查詢主體「{query}」。'

    def _error_result(self, operation: str, query: str, language: str, timestamp: str) -> Dict[str, Any]:
        messages = {
            "zh": "ERP 目前無法連線，因此無法確認即時商品資料。請稍後再試。",
            "en": "ERP is currently unavailable, so live product facts cannot be confirmed. Please try again later.",
            "ja": "現在 ERP に接続できないため、リアルタイムの商品情報を確認できません。後でもう一度お試しください。",
        }
        return {
            "text": messages[self._locale(language)],
            "product_results": [],
            "erp_lookup": {
                "operation": operation,
                "query": query,
                "status": "error",
                "matched_product_count": 0,
                "timestamp": timestamp,
                "data_quality_status": "error",
            },
        }

    @staticmethod
    def _matches_subject(product: Dict[str, Any], query: str) -> bool:
        terms = ProductFactLookupService._traceable_terms(query)
        return ProductFactLookupService._matches_terms(product, terms)

    @staticmethod
    def _matches_terms(product: Dict[str, Any], terms: Sequence[str]) -> bool:
        normalized_terms = [ProductFactLookupService._normalize(term) for term in terms]
        normalized_terms = [term for term in normalized_terms if term]
        if not normalized_terms:
            return False
        fields = (
            "no",
            "sku",
            "code",
            "id",
            "invn002",
            "name",
            "product_name",
            "name_ch",
            "name_en",
            "invn005",
            "brand",
            "invn006",
            "category",
            "type",
            "invn802",
            "invn030",
            "specification",
            "spec",
            "spec1",
            "model",
            "model_name",
            "model_year",
            "invn807",
            "invn051",
            "size",
        )
        normalized_fields = [ProductFactLookupService._normalize(product.get(field)) for field in fields]
        return all(any(term in field for field in normalized_fields) for term in normalized_terms)

    @staticmethod
    def _traceable_terms(query: str) -> List[str]:
        raw_terms = re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]*|[\u4e00-\u9fff]+", str(query or ""))
        ignored = {"the", "a", "an", "of", "for", "does", "do", "have", "has", "is", "there"}
        return [term for term in raw_terms if term.casefold() not in ignored]

    @staticmethod
    def _sku(product: Dict[str, Any]) -> str:
        return ProductFactLookupService._first(product, "no", "sku", "code", "id", "invn002")

    @staticmethod
    def _trusted_brand(product: Dict[str, Any]) -> str:
        # Deliberately omit supplier. Only an explicit canonical/raw brand may
        # appear in a brand catalog answer.
        return ProductFactLookupService._first(product, "canonical_brand", "raw_brand", "brand", "invn006")

    @staticmethod
    def _stock(product: Dict[str, Any]) -> int:
        for key in ("stock", "stock_qty", "total_stock"):
            value = product.get(key)
            if value in (None, ""):
                continue
            try:
                return max(int(float(str(value).replace(",", ""))), 0)
            except (TypeError, ValueError):
                continue
        return 0

    @staticmethod
    def _first(product: Dict[str, Any], *keys: str) -> str:
        for key in keys:
            value = str(product.get(key) or "").strip()
            if value:
                return value
        return ""

    @staticmethod
    def _normalize(value: Any) -> str:
        return re.sub(r"[^A-Za-z0-9\u4e00-\u9fff]+", "", str(value or "")).casefold()

    @staticmethod
    def _locale(language: str) -> str:
        normalized = str(language or "").strip().lower()
        if normalized.startswith("en"):
            return "en"
        if normalized.startswith("ja"):
            return "ja"
        return "zh"

    def _no_matches_text(self, query: str, language: str) -> str:
        return {
            "zh": f'ERP 找不到符合「{query}」的商品。',
            "en": f'ERP has no products matching "{query}".',
            "ja": f'ERP に「{query}」と一致する商品はありません。',
        }[self._locale(language)]

    def _inventory_text(self, query: str, count: int, total: int, language: str) -> str:
        return {
            "zh": f'ERP 找到 {count} 筆符合「{query}」的商品，目前總庫存為 {total} 件。',
            "en": f'ERP found {count} products matching "{query}", with {total} units currently in stock.',
            "ja": f'ERP で「{query}」に一致する商品が {count} 件見つかり、現在の総在庫は {total} 点です。',
        }[self._locale(language)]

    def _brand_text(
        self,
        query: str,
        *,
        product_count: int,
        brands: Sequence[Dict[str, Any]],
        brand_missing_count: int,
        language: str,
    ) -> str:
        locale = self._locale(language)
        if not brands:
            return {
                "zh": f'ERP 找到 {product_count} 筆「{query}」商品，但未提供品牌資料。',
                "en": f'ERP found {product_count} "{query}" products, but it does not provide brand data for them.',
                "ja": f'ERP で「{query}」商品が {product_count} 件見つかりましたが、ブランド情報はありません。',
            }[locale]
        names = "、".join(str(item["brand"]) for item in brands)
        suffix = {
            "zh": f'；另有 {brand_missing_count} 筆商品缺少品牌資料' if brand_missing_count else "",
            "en": f'; {brand_missing_count} products have no brand data' if brand_missing_count else "",
            "ja": f'。ほかに {brand_missing_count} 件はブランド情報がありません' if brand_missing_count else "",
        }[locale]
        return {
            "zh": f'ERP 找到 {product_count} 筆「{query}」商品，可辨識品牌為：{names}{suffix}。',
            "en": f'ERP found {product_count} "{query}" products. Identified brands: {names}{suffix}.',
            "ja": f'ERP で「{query}」商品が {product_count} 件見つかりました。確認できたブランド：{names}{suffix}。',
        }[locale]

    def _product_text(self, query: str, count: int, language: str) -> str:
        return {
            "zh": f'ERP 找到 {count} 筆符合「{query}」的商品。',
            "en": f'ERP found {count} products matching "{query}".',
            "ja": f'ERP で「{query}」に一致する商品が {count} 件見つかりました。',
        }[self._locale(language)]
