from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence

from ...schemas.ai import Hit


_ERP_FACT_RE = re.compile(
    r"(?:\bSKU\b|\bstock\b|\binventory\b|\bprice\b|庫存|價格|售價|可售|報價|NT\$|TWD\s*\d)",
    re.IGNORECASE,
)


class ClaimValidationService:
    """Prevents ungrounded SKU, price, stock, and sellable-status claims."""

    def validate(
        self,
        *,
        answer_text: str,
        metadata: Dict[str, Any],
        hits: Sequence[Hit] | Sequence[Dict[str, Any]] | None = None,
        prompt_category: Optional[str] = None,
    ) -> Dict[str, Any]:
        del prompt_category
        text = str(answer_text or "")
        claims = [part.strip() for part in re.split(r"(?<=[。！？.!?])\s+|\n+", text) if part.strip()]
        erp_bound = bool(
            (metadata or {}).get("product_results")
            or (metadata or {}).get("erp_snapshot_timestamp")
            or (metadata or {}).get("official_inventory_binding", {}).get("proof_count")
        )
        unsupported: List[str] = []
        if not erp_bound:
            unsupported = [claim for claim in claims if _ERP_FACT_RE.search(claim)]
        trace_ids: List[str] = []
        for index, hit in enumerate(hits or []):
            if isinstance(hit, Hit):
                identifier = hit.id
            elif isinstance(hit, dict):
                identifier = hit.get("id")
            else:
                identifier = None
            trace_ids.append(str(identifier or index))
        return {
            "status": "failed_operational_fact" if unsupported else "passed",
            "supported_claim_count": 0,
            "unsupported_claim_count": len(unsupported),
            "unsupported_claims": unsupported,
            "evidence_trace_ids": trace_ids,
        }
