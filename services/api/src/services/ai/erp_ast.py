from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ...cerpModule import CERPClientError
from ..cerp_service import CerpService
from .chat_planner import ERPQueryAST, ERPPredicate


_FIELD_KEYS: Dict[str, Tuple[str, ...]] = {
    "sku": ("no", "sku", "code", "id", "invn002"),
    "name": ("name", "product_name", "name_ch", "name_en", "invn005"),
    "brand": ("canonical_brand", "raw_brand", "brand", "invn006"),
    "category": ("category", "type", "invn802", "invn030"),
    "specification": (
        "specification", "spec", "spec1", "model", "model_name", "model_year", "invn807", "invn051", "size"
    ),
}


class ERPQueryExecutor:
    """Validates and executes an LLM plan without taking semantic routing ownership."""

    def __init__(self, cerp_service: Optional[CerpService] = None) -> None:
        self._cerp = cerp_service or CerpService()

    async def execute(self, ast: ERPQueryAST, *, language: str = "zh-TW") -> Dict[str, Any]:
        timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        queries = self._queries(ast)
        if not queries:
            return self._empty(ast, timestamp, "invalid_ast", language)
        try:
            results = await asyncio.gather(
                *(
                    self._cerp.search_products(
                        query,
                        limit=50,
                        page_size=50,
                        raise_on_error=True,
                    )
                    for query in queries
                ),
                return_exceptions=True,
            )
        except CERPClientError:
            return self._empty(ast, timestamp, "error", language)

        candidates: List[Dict[str, Any]] = []
        seen = set()
        provider_error = False
        for result in results:
            if isinstance(result, Exception):
                provider_error = True
                continue
            for product in result or []:
                if not isinstance(product, dict):
                    continue
                sku = self._field(product, "sku")
                if not sku or sku.casefold() in seen:
                    continue
                seen.add(sku.casefold())
                candidates.append(product)
                if len(candidates) >= 200:
                    break
            if len(candidates) >= 200:
                break
        if not candidates:
            return self._empty(ast, timestamp, "error" if provider_error else "no_matches", language)

        ranked: List[Tuple[float, Dict[str, Any], List[str]]] = []
        for product in candidates:
            accepted, predicate_matches = self._apply_predicates(product, ast.predicates)
            if not accepted:
                continue
            score, matches = self._score(product, ast)
            matches.extend(predicate_matches)
            if score <= 0 and ast.search_terms:
                continue
            ranked.append((score, product, list(dict.fromkeys(matches))))
        ranked.sort(key=lambda row: (-row[0], self._field(row[1], "sku")))
        selected = ranked[: ast.limit]
        if not selected:
            return self._empty(ast, timestamp, "no_matches", language)

        products: List[Dict[str, Any]] = []
        proofs: List[Dict[str, Any]] = []
        for _, product, matches in selected:
            contract, row_proofs = self._contract(product, ast, matches, timestamp, language)
            products.append(contract)
            proofs.extend(row_proofs)
        status = "used"
        total_stock = sum(self._stock(row[1]) for row in ranked)
        brands = sorted({self._field(row[1], "brand") for row in ranked if self._field(row[1], "brand")})
        lookup = {
            "operation": self._legacy_operation(ast.operation),
            "query": " | ".join(queries),
            "status": status,
            "matched_product_count": len(ranked),
            "timestamp": timestamp,
            "data_quality_status": "complete",
        }
        if ast.operation == "inventory":
            lookup["total_stock"] = total_stock
            proofs.append(
                {
                    "id": "ERP:QUERY#total_stock",
                    "field": "total_stock",
                    "value": total_stock,
                    "matched_product_count": len(ranked),
                    "timestamp": timestamp,
                }
            )
        if ast.operation == "catalog" and "brand" in ast.projections:
            missing = sum(1 for _, product, _ in ranked if not self._field(product, "brand"))
            lookup.update(
                {
                    "brands": [{"brand": item} for item in brands],
                    "brand_missing_count": missing,
                    "data_quality_status": "brand_missing" if missing and not brands else ("partial_brand_missing" if missing else "complete"),
                    "status": "brand_missing" if missing and not brands else "used",
                }
            )
            proofs.append(
                {
                    "id": "ERP:QUERY#brand_catalog",
                    "field": "brands",
                    "value": brands,
                    "brand_missing_count": missing,
                    "matched_product_count": len(ranked),
                    "timestamp": timestamp,
                }
            )
        locale = "en" if str(language).lower().startswith("en") else "ja" if str(language).lower().startswith("ja") else "zh"
        if ast.operation == "inventory":
            summary = {
                "zh": f"YS ERP 找到 {len(ranked)} 筆符合條件的商品，目前總庫存為 {total_stock} 件。",
                "en": f"YS ERP found {len(ranked)} matching products with {total_stock} units in total stock.",
                "ja": f"YS ERP で条件に合う商品が {len(ranked)} 件見つかり、総在庫は {total_stock} 点です。",
            }[locale]
        elif lookup.get("status") == "brand_missing":
            summary = {
                "zh": "YS ERP 找到符合條件的商品，但未提供可信品牌資料。",
                "en": "YS ERP found matching products, but no trusted brand data is available.",
                "ja": "YS ERP で商品は見つかりましたが、信頼できるブランド情報がありません。",
            }[locale]
        else:
            summary = {
                "zh": f"YS ERP 找到 {len(ranked)} 筆符合條件的商品。",
                "en": f"YS ERP found {len(ranked)} matching products.",
                "ja": f"YS ERP で条件に合う商品が {len(ranked)} 件見つかりました。",
            }[locale]
        return {
            "text": summary,
            "product_results": products,
            "row_proofs": proofs,
            "erp_lookup": lookup,
            "erp_query": {
                "ast_version": ast.version,
                "operation": ast.operation,
                "applied_terms": queries,
                "applied_filters": [item.model_dump(mode="json") for item in ast.predicates],
                "status": lookup["status"],
                "row_proof_count": len(proofs),
                "timestamp": timestamp,
            },
        }

    @staticmethod
    def _queries(ast: ERPQueryAST) -> List[str]:
        values: List[str] = []
        seen = set()
        for item in [*(term.value for term in ast.search_terms), *ast.semantic_terms]:
            value = re.sub(r"\s+", " ", str(item or "")).strip()[:160]
            if value and value.casefold() not in seen:
                seen.add(value.casefold())
                values.append(value)
        return values[:8]

    def _score(self, product: Dict[str, Any], ast: ERPQueryAST) -> Tuple[float, List[str]]:
        score = 0.0
        matches: List[str] = []
        for index, term in enumerate(ast.search_terms):
            values = [self._field(product, field) for field in term.fields]
            similarity = max((self._similarity(term.value, value) for value in values if value), default=0.0)
            threshold = 1.0 if term.match == "exact" else 0.34
            if similarity >= threshold:
                score += similarity * (5.0 if index == 0 else 3.0)
                matches.append(f"term:{index}")
        for index, value in enumerate(ast.semantic_terms):
            similarity = max(
                self._similarity(value, self._field(product, field))
                for field in ("name", "brand", "category", "specification")
            )
            if similarity >= 0.34:
                score += similarity * 2.0
                matches.append(f"semantic:{index}")
        stock = self._stock(product)
        price = self._price(product)
        for rule in ast.ranking:
            if rule.criterion == "stock" and stock > 0:
                score += rule.weight * min(stock / 100.0, 1.0)
                matches.append("in_stock")
            elif rule.criterion == "price" and price is not None:
                score += rule.weight * (1.0 / max(price, 1.0))
            elif rule.criterion in {"semantic_match", "category_match", "feature_match"} and score > 0:
                score += rule.weight
        return score, matches

    def _apply_predicates(
        self,
        product: Dict[str, Any],
        predicates: Sequence[ERPPredicate],
    ) -> Tuple[bool, List[str]]:
        matches: List[str] = []
        for index, predicate in enumerate(predicates):
            if predicate.field == "stock":
                actual: Any = self._stock(product)
            elif predicate.field == "price":
                actual = self._price(product)
            else:
                actual = self._field(product, predicate.field)
            expected = predicate.value
            passed = self._predicate_passed(actual, predicate.operator, expected)
            if not passed:
                return False, []
            matches.append(f"predicate:{index}")
        return True, matches

    @classmethod
    def _predicate_passed(cls, actual: Any, operator: str, expected: Any) -> bool:
        if operator in {"gte", "lte"}:
            try:
                left = float(actual)
                right = float(expected)
            except (TypeError, ValueError):
                return False
            return left >= right if operator == "gte" else left <= right
        if operator == "exclude":
            return cls._normalize(expected) not in cls._normalize(actual)
        if operator == "eq":
            return cls._normalize(actual) == cls._normalize(expected)
        return cls._similarity(expected, actual) >= 0.34

    def _contract(
        self,
        product: Dict[str, Any],
        ast: ERPQueryAST,
        matches: Sequence[str],
        timestamp: str,
        language: str,
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        sku = self._field(product, "sku")
        values: Dict[str, Any] = {
            "sku": sku,
            "name": self._field(product, "name"),
            "brand": self._field(product, "brand"),
            "category": self._field(product, "category"),
            "specification": self._field(product, "specification"),
            "price": self._price(product),
            "stock": self._stock(product),
        }
        proofs = [
            {
                "id": f"ERP:{sku}#{field}",
                "sku": sku,
                "field": field,
                "value": values[field],
                "timestamp": timestamp,
            }
            for field in ast.projections
            if field in values and values[field] not in (None, "")
        ]
        query_label = "、".join(self._queries(ast)[:3])
        has_stock_filter = any(item.field == "stock" for item in ast.predicates)
        has_price_filter = any(item.field == "price" for item in ast.predicates)
        if str(language).lower().startswith("en"):
            reason = self._reason_en(
                ast.operation,
                query_label,
                values,
                has_stock_filter=has_stock_filter,
                has_price_filter=has_price_filter,
            )
        elif str(language).lower().startswith("ja"):
            reason = self._reason_ja(
                ast.operation,
                query_label,
                values,
                has_stock_filter=has_stock_filter,
                has_price_filter=has_price_filter,
            )
        else:
            reason = self._reason_zh(
                ast.operation,
                query_label,
                values,
                has_stock_filter=has_stock_filter,
                has_price_filter=has_price_filter,
            )
        return (
            {
                **values,
                "recommendation_reason": reason,
                "matched_requirements": list(matches),
                "source_timestamp": timestamp,
            },
            proofs,
        )

    @staticmethod
    def _reason_zh(
        operation: str,
        query_label: str,
        values: Dict[str, Any],
        *,
        has_stock_filter: bool,
        has_price_filter: bool,
    ) -> str:
        if operation == "inventory":
            return f"ERP 商品資料符合「{query_label}」，目前庫存為 {values['stock']} 件。"
        if operation == "catalog":
            return f"ERP 商品名稱或分類符合「{query_label}」，品牌與規格以 ERP 原始欄位為準。"
        parts = [f"ERP 商品資料符合本次的「{query_label}」需求"]
        if values.get("specification"):
            parts.append(f"規格為「{values['specification']}」")
        if has_stock_filter and values.get("stock", 0) > 0:
            parts.append("目前有庫存")
        if has_price_filter and values.get("price") is not None:
            parts.append("價格符合使用者提供的條件")
        return "，".join(parts) + "。"

    @staticmethod
    def _reason_en(
        operation: str,
        query_label: str,
        values: Dict[str, Any],
        *,
        has_stock_filter: bool,
        has_price_filter: bool,
    ) -> str:
        if operation == "inventory":
            return f'The ERP product data matches "{query_label}" and shows {values["stock"]} units in stock.'
        if operation == "catalog":
            return f'The ERP product name or category matches "{query_label}"; brand and specification come from ERP fields.'
        parts = [f'The ERP product data matches the "{query_label}" requirements']
        if values.get("specification"):
            parts.append(f'specification: {values["specification"]}')
        if has_stock_filter and values.get("stock", 0) > 0:
            parts.append("currently in stock")
        if has_price_filter and values.get("price") is not None:
            parts.append("price matches the user-provided condition")
        return "; ".join(parts) + "."

    @staticmethod
    def _reason_ja(
        operation: str,
        query_label: str,
        values: Dict[str, Any],
        *,
        has_stock_filter: bool,
        has_price_filter: bool,
    ) -> str:
        if operation == "inventory":
            return f"ERP 商品データが「{query_label}」に一致し、現在庫は {values['stock']} 点です。"
        if operation == "catalog":
            return f"ERP の商品名または分類が「{query_label}」に一致します。ブランドと仕様は ERP 項目に基づきます。"
        parts = [f"ERP 商品データが今回の「{query_label}」要件に一致します"]
        if values.get("specification"):
            parts.append(f"仕様は「{values['specification']}」です")
        if has_stock_filter and values.get("stock", 0) > 0:
            parts.append("現在庫があります")
        if has_price_filter and values.get("price") is not None:
            parts.append("価格はユーザー指定条件に合います")
        return "、".join(parts) + "。"

    @staticmethod
    def _empty(ast: ERPQueryAST, timestamp: str, status: str, language: str) -> Dict[str, Any]:
        text = {
            "zh": "YS ERP 目前沒有符合條件的商品資料。" if status == "no_matches" else "YS ERP 查詢目前無法完成。",
            "en": "YS ERP has no products matching the query." if status == "no_matches" else "The YS ERP query could not be completed.",
            "ja": "YS ERP に条件に合う商品はありません。" if status == "no_matches" else "YS ERP の照会を完了できませんでした。",
        }["en" if str(language).lower().startswith("en") else "ja" if str(language).lower().startswith("ja") else "zh"]
        timestamp_value = timestamp
        return {
            "text": text,
            "product_results": [],
            "row_proofs": [],
            "erp_lookup": {
                "operation": ERPQueryExecutor._legacy_operation(ast.operation),
                "query": " | ".join(ERPQueryExecutor._queries(ast)),
                "status": status,
                "matched_product_count": 0,
                "timestamp": timestamp_value,
                "data_quality_status": status,
            },
            "erp_query": {
                "ast_version": ast.version,
                "operation": ast.operation,
                "applied_terms": ERPQueryExecutor._queries(ast),
                "applied_filters": [item.model_dump(mode="json") for item in ast.predicates],
                "status": status,
                "row_proof_count": 0,
                "timestamp": timestamp_value,
            },
        }

    @staticmethod
    def _legacy_operation(operation: str) -> str:
        return {
            "inventory": "inventory_lookup",
            "catalog": "brand_catalog",
        }.get(operation, "product_lookup")

    @staticmethod
    def _field(product: Dict[str, Any], field: str) -> str:
        for key in _FIELD_KEYS[field]:
            value = str(product.get(key) or "").strip()
            if value:
                return value
        return ""

    @staticmethod
    def _stock(product: Dict[str, Any]) -> int:
        for key in ("stock", "stock_qty", "total_stock"):
            try:
                if product.get(key) not in (None, ""):
                    return max(int(float(str(product[key]).replace(",", ""))), 0)
            except (TypeError, ValueError):
                continue
        return 0

    @staticmethod
    def _price(product: Dict[str, Any]) -> Optional[float]:
        for key in ("price", "list_price"):
            try:
                if product.get(key) not in (None, ""):
                    return float(str(product[key]).replace(",", ""))
            except (TypeError, ValueError):
                continue
        return None

    @staticmethod
    def _normalize(value: Any) -> str:
        return re.sub(r"[^A-Za-z0-9\u4e00-\u9fff]+", "", str(value or "")).casefold()

    @classmethod
    def _similarity(cls, left: Any, right: Any) -> float:
        a = cls._normalize(left)
        b = cls._normalize(right)
        if not a or not b:
            return 0.0
        if a in b or b in a:
            return 1.0
        return SequenceMatcher(None, a, b).ratio()
