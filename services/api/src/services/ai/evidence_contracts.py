from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from ...schemas.ai import Hit


_CERP_CATEGORIES = {
    "quote_recommendation",
    "inventory_lookup",
    "cerp_business_lookup",
    "product_recommendation",
}


def evidence_type_for_prompt_category(prompt_category: Optional[str]) -> str:
    return "cerp_snapshot" if str(prompt_category or "").strip() in _CERP_CATEGORIES else "grounded_answer"


def build_cerp_evidence_contract(
    *,
    cerp_products: Sequence[Dict[str, Any]],
    prompt_category: str = "quote_recommendation",
    source_policy: str = "internal_only",
    route_policy: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    products = [dict(item) for item in cerp_products or [] if isinstance(item, dict)]
    items: List[Dict[str, Any]] = []
    for product in products:
        sku = str(product.get("sku") or product.get("no") or product.get("id") or "").strip()
        if not sku:
            continue
        items.append(
            {
                "id": sku,
                "source_trace": f"ERP:{sku}",
                "source_family": "erp_snapshot",
                "excerpt": " | ".join(
                    part
                    for part in (
                        str(product.get("name") or product.get("name_ch") or "").strip(),
                        f"brand={product.get('brand')}" if product.get("brand") else "",
                        f"price={product.get('price')}" if product.get("price") is not None else "",
                        f"stock={product.get('stock')}" if product.get("stock") is not None else "",
                    )
                    if part
                ),
            }
        )
    return {
        "evidence_type": "cerp_snapshot",
        "prompt_category": prompt_category,
        "source_policy": source_policy,
        "status": "pass" if items else "fail_closed",
        "fail_closed_reason": None if items else "erp_no_results",
        "route_policy": dict(route_policy or {}),
        "answer_plan": {"items": items},
        "accepted_count": len(items),
        "rejected_count": max(len(products) - len(items), 0),
    }


def apply_evidence_contract(
    *,
    selected_hits: Sequence[Hit],
    cerp_products: Sequence[Dict[str, Any]],
    prompt_category: str,
    source_policy: str,
    route_policy: Optional[Dict[str, Any]] = None,
    **_: Any,
) -> Tuple[List[Hit], Dict[str, Any]]:
    if evidence_type_for_prompt_category(prompt_category) == "cerp_snapshot":
        return list(selected_hits or []), build_cerp_evidence_contract(
            cerp_products=cerp_products,
            prompt_category=prompt_category,
            source_policy=source_policy,
            route_policy=route_policy,
        )
    hits = list(selected_hits or [])
    return hits, {
        "evidence_type": "grounded_answer",
        "status": "pass" if hits else "no_relevant_hits",
        "source_policy": source_policy,
        "answer_plan": {
            "items": [
                {
                    "id": hit.id,
                    "source_trace": (hit.meta or {}).get("source_trace") or hit.id,
                    "excerpt": str(hit.summary or hit.text or "")[:700],
                }
                for hit in hits[:6]
            ]
        },
    }


def answer_plan_summary(plan: Dict[str, Any]) -> str:
    items = (plan.get("answer_plan") or {}).get("items") if isinstance(plan, dict) else []
    lines = ["Use only the evidence items below for exact factual claims."]
    for index, item in enumerate(items or [], start=1):
        lines.append(f"{index}. {item.get('source_trace') or item.get('id')}: {item.get('excerpt') or ''}")
    return "\n".join(lines)
