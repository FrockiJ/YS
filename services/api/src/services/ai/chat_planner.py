from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Literal, Optional, Sequence

from pydantic import BaseModel, Field, field_validator

from ...pipelines.llm.openai_client import LLMRequestBudget, chat_complete_result
from .product_intent_analysis import ProductNeedProfilePatch


logger = logging.getLogger(__name__)


class ExternalPlan(BaseModel):
    required: bool = False
    query: Optional[str] = None
    reason: Optional[str] = None


class TripPlanPatch(BaseModel):
    """Travel facts selected by the planner, separate from product requirements."""

    activity: Optional[str] = None
    destination_region: Optional[str] = None
    departure_location: Optional[str] = None
    elevation_band: Optional[str] = None
    duration_days: Optional[int] = Field(default=None, ge=1, le=365)
    travel_constraints: List[str] = Field(default_factory=list, max_length=12)
    candidate_destinations: List[str] = Field(default_factory=list, max_length=12)
    selected_destination: Optional[str] = None


class ERPSourceTrace(BaseModel):
    source: Literal["current_message", "conversation", "rag", "llm_inference"]
    reference: str = Field(min_length=1, max_length=500)


class ERPSearchTerm(BaseModel):
    value: str = Field(min_length=1, max_length=160)
    match: Literal["fuzzy", "exact"] = "fuzzy"
    fields: List[
        Literal["sku", "name", "brand", "category", "specification"]
    ] = Field(default_factory=lambda: ["name", "brand", "category", "specification"])
    source_trace: ERPSourceTrace

    @field_validator("fields")
    @classmethod
    def unique_fields(cls, value: List[str]) -> List[str]:
        return list(dict.fromkeys(value))[:5]


class ERPPredicate(BaseModel):
    field: Literal[
        "sku",
        "name",
        "brand",
        "category",
        "specification",
        "price",
        "stock",
    ]
    operator: Literal["eq", "fuzzy", "gte", "lte", "exclude"]
    value: Any
    source_trace: ERPSourceTrace


class ERPRankingRule(BaseModel):
    criterion: Literal[
        "semantic_match",
        "category_match",
        "feature_match",
        "preferred_brand",
        "within_budget",
        "stock",
        "price",
    ]
    direction: Literal["asc", "desc"] = "desc"
    weight: float = Field(default=1.0, ge=0.0, le=10.0)


class ERPQueryAST(BaseModel):
    version: Literal["2"] = "2"
    operation: Literal["inventory", "price", "catalog", "search", "recommendation", "quote"]
    projections: List[
        Literal["sku", "name", "brand", "category", "specification", "price", "stock"]
    ] = Field(default_factory=lambda: ["sku", "name", "brand", "category", "specification"])
    search_terms: List[ERPSearchTerm] = Field(default_factory=list, max_length=8)
    predicates: List[ERPPredicate] = Field(default_factory=list, max_length=16)
    semantic_terms: List[str] = Field(default_factory=list, max_length=8)
    ranking: List[ERPRankingRule] = Field(default_factory=list, max_length=8)
    limit: int = Field(default=6, ge=1, le=6)

    @field_validator("semantic_terms")
    @classmethod
    def normalize_semantic_terms(cls, value: List[str]) -> List[str]:
        result: List[str] = []
        seen = set()
        for item in value:
            normalized = str(item or "").strip()[:160]
            if normalized and normalized.casefold() not in seen:
                seen.add(normalized.casefold())
                result.append(normalized)
        return result[:8]


class ChatExecutionPlan(BaseModel):
    version: Literal["2"] = "2"
    task_type: Literal[
        "knowledge", "destination", "erp_lookup", "product_recommendation", "mixed"
    ] = "knowledge"
    answer_mode: Literal["knowledge_only", "erp_only", "mixed"] = "knowledge_only"
    rag_queries: List[str] = Field(default_factory=list, max_length=3)
    external: ExternalPlan = Field(default_factory=ExternalPlan)
    erp_ast: Optional[ERPQueryAST] = None
    need_profile_patch: ProductNeedProfilePatch = Field(default_factory=ProductNeedProfilePatch)
    trip_plan_patch: TripPlanPatch = Field(default_factory=TripPlanPatch)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("rag_queries")
    @classmethod
    def normalize_rag_queries(cls, value: List[str]) -> List[str]:
        result: List[str] = []
        seen = set()
        for item in value:
            normalized = re.sub(r"\s+", " ", str(item or "")).strip()[:500]
            if normalized and normalized.casefold() not in seen:
                seen.add(normalized.casefold())
                result.append(normalized)
        return result[:3]

    def audit_metadata(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "task_type": self.task_type,
            "answer_mode": self.answer_mode,
            "confidence": round(float(self.confidence), 3),
            "external_required": bool(self.external.required),
        }

    @property
    def decision(self) -> str:
        if self.erp_ast is not None:
            return "erp_immediate"
        if self.task_type == "product_recommendation":
            return "knowledge_with_product_bridge"
        return "knowledge_only"

    @property
    def source(self) -> str:
        return "llm_planner"

    @property
    def immediate(self) -> bool:
        return self.erp_ast is not None

    @property
    def bridge_eligible(self) -> bool:
        return self.task_type in {"product_recommendation", "mixed"} or self.erp_ast is not None

    @property
    def lookup_operation(self) -> Optional[str]:
        if self.erp_ast is None:
            return None
        return {
            "inventory": "inventory_lookup",
            "catalog": "brand_catalog",
        }.get(self.erp_ast.operation, "product_lookup")

    @property
    def lookup_query(self) -> Optional[str]:
        if self.erp_ast is None or not self.erp_ast.search_terms:
            return None
        return self.erp_ast.search_terms[0].value


class ChatPlanningService:
    """One semantic planning call. Runtime routing is owned by the returned schema."""

    async def plan(
        self,
        message: str,
        *,
        history: Optional[Sequence[Dict[str, Any]]] = None,
        context_state: Optional[Dict[str, Any]] = None,
        budget: Optional[LLMRequestBudget] = None,
    ) -> ChatExecutionPlan:
        recent: List[Dict[str, str]] = []
        for item in list(history or [])[-12:]:
            if not isinstance(item, dict):
                continue
            content = str(item.get("content") or "").strip()
            if content:
                recent.append(
                    {
                        "role": str(item.get("role") or "user"),
                        "content": content[:400],
                    }
                )
        context = self._compact_context(context_state)
        payload = {
            "message": str(message or ""),
            "recent_history": recent,
            "context_state": context,
        }
        system = (
            "You are the sole semantic planner for YS-AI. Analyze the current prompt and return only "
            "ChatExecutionPlan v2 JSON. The server handles authorization, retrieval, field allowlists, "
            "row proofs, and source traces; do not answer the user in this call. "
            "Use knowledge for stable advice, methods, explanations, or planning. Use destination for place "
            "or campsite planning. Set external.required only when the requested fact is genuinely current or "
            "externally verifiable, such as live weather, road state, law/regulation, current operation, current "
            "availability, or an explicit verification request. Words such as current, recommend, or campsite "
            "alone are never sufficient. Stable knowledge with no RAG will be answered from model knowledge. "
            "ERP is the only source for actual YS products, SKU, price, stock, brand catalog, sellability, and quote. "
            "Use mixed when the prompt needs both professional guidance and ERP results. "
            "When ERP is needed, produce an ERP AST. Search terms may be semantic expansions inferred from the "
            "activity/use case, but mark them llm_inference and explain the inference in source_trace.reference. "
            "User facts such as budget, quantity, preferred/excluded brand must trace to the current message or "
            "conversation. Do not invent product rows, SKU, price, stock, brand, or availability. "
            "For destination or mixed tasks, populate trip_plan_patch with every explicit or inherited travel "
            "fact that is useful across turns: activity, destination_region, departure_location, elevation_band, "
            "duration_days, travel_constraints, candidate_destinations, and selected_destination. Keep departure "
            "and destination distinct. For product recommendation or mixed tasks, populate need_profile_patch "
            "from the current message and conversation context; inferred use-case/features may be included, but "
            "ERP predicates for user constraints still require a source trace. "
            "Do not depend on fixed wording or benchmark examples. Return valid schema JSON only."
        )
        result = await chat_complete_result(
            system=system,
            user=json.dumps(payload, ensure_ascii=False),
            history=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
            temperature=0.1,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "ys_chat_execution_plan_v2",
                    "strict": False,
                    "schema": ChatExecutionPlan.model_json_schema(),
                },
            },
            max_completion_tokens=1000,
            budget=budget,
            role="planner",
            allow_model_fallback=False,
        )
        plan = ChatExecutionPlan.model_validate(self._coerce_raw(self._parse_json(result.content)))
        return self._normalize_plan(plan, str(message or ""))

    @staticmethod
    def fallback(message: str) -> ChatExecutionPlan:
        query = re.sub(r"\s+", " ", str(message or "")).strip()
        return ChatExecutionPlan(
            task_type="knowledge",
            answer_mode="knowledge_only",
            rag_queries=[query] if query else [],
            external=ExternalPlan(required=False),
            confidence=0.0,
        )

    @staticmethod
    def _parse_json(value: str) -> Dict[str, Any]:
        text = str(value or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("Chat execution plan must be an object")
        return parsed

    @staticmethod
    def _coerce_raw(value: Dict[str, Any]) -> Dict[str, Any]:
        normalized = dict(value)
        normalized["rag_queries"] = list(normalized.get("rag_queries") or [])[:3]
        ast = normalized.get("erp_ast")
        if isinstance(ast, dict):
            ast = dict(ast)
            try:
                ast["limit"] = max(1, min(int(ast.get("limit") or 6), 6))
            except (TypeError, ValueError):
                ast["limit"] = 6
            ast["search_terms"] = list(ast.get("search_terms") or [])[:8]
            ast["semantic_terms"] = list(ast.get("semantic_terms") or [])[:8]
            ast["predicates"] = list(ast.get("predicates") or [])[:16]
            ast["ranking"] = list(ast.get("ranking") or [])[:8]
            normalized["erp_ast"] = ast
        return normalized

    @staticmethod
    def _compact_context(value: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        allowed = ("trip_plan", "product_need_profile", "erp_lookup", "source_message_id")
        compact = {key: value[key] for key in allowed if value.get(key) not in (None, "", [], {})}
        serialized = json.dumps(compact, ensure_ascii=False)
        if len(serialized) <= 4000:
            return compact
        return {"summary": serialized[:4000]}

    @staticmethod
    def _normalize_plan(plan: ChatExecutionPlan, message: str) -> ChatExecutionPlan:
        if not plan.rag_queries and plan.answer_mode != "erp_only":
            plan.rag_queries = [message]
        if plan.answer_mode == "erp_only":
            plan.external = ExternalPlan(required=False)
        elif plan.external.query or plan.external.reason:
            # A provider query/reason is itself structured planner intent. Keep
            # the plan consistent without inspecting user wording or adding a
            # server-side subject route.
            plan.external.required = True
            if not plan.external.query:
                plan.external.query = message
        if plan.erp_ast is None and plan.answer_mode in {"erp_only", "mixed"}:
            plan.answer_mode = "knowledge_only"
            plan.task_type = "knowledge"
        if plan.erp_ast is not None and plan.answer_mode == "knowledge_only":
            plan.answer_mode = "mixed" if plan.rag_queries else "erp_only"
            plan.task_type = "mixed" if plan.answer_mode == "mixed" else "erp_lookup"
        if plan.erp_ast is not None:
            required = {
                "inventory": ("sku", "name", "stock"),
                "price": ("sku", "name", "price"),
                "catalog": ("sku", "name", "brand", "category"),
                "search": ("sku", "name", "brand", "category", "specification"),
                "recommendation": ("sku", "name", "brand", "category", "specification", "price", "stock"),
                "quote": ("sku", "name", "specification", "price", "stock"),
            }[plan.erp_ast.operation]
            plan.erp_ast.projections = list(
                dict.fromkeys([*required, *plan.erp_ast.projections])
            )
        return plan
