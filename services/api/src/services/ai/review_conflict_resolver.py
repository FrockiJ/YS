from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ...core import db
from .burghound_issue_resolver import BurghoundIssueEvidence, BurghoundIssueResolver


_VINTAGE_RE = re.compile(r"\b((?:19|20)\d{2})\b")


@dataclass
class ReviewConflictEvidence:
    vinous_row: Dict[str, Any]
    burghound: BurghoundIssueEvidence

    def to_hit_dicts(self) -> List[Dict[str, Any]]:
        return [self._vinous_hit(), self._burghound_hit()]

    def _vinous_hit(self) -> Dict[str, Any]:
        row = self.vinous_row
        source_file = str(row.get("source_file") or "Vinous").strip()
        source_row = str(row.get("source_row") or row.get("id") or "").strip()
        producer = str(row.get("producer") or "").strip()
        wine_name = str(row.get("wine_name") or row.get("full_wine_name") or "").strip()
        vintage = str(row.get("vintage") or "").strip()
        score = str(row.get("score_raw") or row.get("score_numeric") or "").strip()
        reviewer = str(row.get("reviewer") or "Vinous").strip()
        record_key = f"{source_file}:row:{source_row or row.get('id')}"
        source_trace = f"vinous | {source_file} | row:{source_row or row.get('id')} | record:{record_key}"
        text = " | ".join(
            part
            for part in [
                f"{producer} {wine_name} {vintage}".strip(),
                "Vinous",
                reviewer,
                f"score {score}" if score else "",
                source_trace,
                str(row.get("tasting_note") or "")[:900],
            ]
            if part
        )
        return {
            "id": f"review_conflict:vinous:{row.get('id')}",
            "document_id": None,
            "chunk_idx": None,
            "text": text,
            "summary": text[:600],
            "keywords": ["vinous", "burghound", "review conflict", producer, wine_name, vintage],
            "meta": {
                "source_family": "licensed_review_dataset",
                "source_name": "Vinous",
                "source_site": "vinous",
                "evidence_kind": "licensed_review_row",
                "reviewer": reviewer,
                "producer": producer,
                "wine_name": wine_name,
                "full_wine_name": str(row.get("full_wine_name") or wine_name).strip(),
                "vintage": vintage,
                "score": score,
                "score_raw": score,
                "row_id": source_row,
                "record_key": record_key,
                "source_trace": source_trace,
                "allowed_use": "rag_citation",
                "conflict_group": "burghound_vs_vinous",
            },
            "kg": {},
            "score": 99.0,
            "source_type": "rag",
        }

    def _burghound_hit(self) -> Dict[str, Any]:
        hit = self.burghound.to_hit_dict()
        meta = hit.setdefault("meta", {})
        meta["conflict_group"] = "burghound_vs_vinous"
        meta["evidence_kind"] = "licensed_review_issue"
        hit["score"] = max(float(hit.get("score") or 0.0), 99.0)
        return hit


class ReviewConflictResolver:
    """Find auditable same-vintage review disagreement examples across licensed sources."""

    @staticmethod
    def should_handle(query: str) -> bool:
        lowered = str(query or "").casefold()
        return (
            "burghound" in lowered
            and "vinous" in lowered
            and any(token in lowered for token in ("disagree", "conflict", "compare", "more", "rely"))
        )

    async def resolve(self, query: str) -> Optional[ReviewConflictEvidence]:
        if not self.should_handle(query):
            return None
        vintage = self._vintage(query) or "2021"
        rows = await self._vinous_candidates(vintage)
        resolver = BurghoundIssueResolver()
        for row in rows:
            producer = str(row.get("producer") or "").strip()
            wine_name = str(row.get("wine_name") or row.get("full_wine_name") or "").strip()
            if not producer or not wine_name:
                continue
            burghound = await resolver.resolve(f"Burghound review {producer} {wine_name} {vintage}")
            if not burghound:
                continue
            if self._scores_differ(row.get("score_raw") or row.get("score_numeric"), burghound.score):
                return ReviewConflictEvidence(vinous_row=dict(row), burghound=burghound)
        return None

    @staticmethod
    def _vintage(query: str) -> Optional[str]:
        match = _VINTAGE_RE.search(str(query or ""))
        return match.group(1) if match else None

    @staticmethod
    def _score_numbers(value: Any) -> List[float]:
        return [float(item) for item in re.findall(r"\d+(?:\.\d+)?", str(value or ""))]

    @classmethod
    def _scores_differ(cls, left: Any, right: Any) -> bool:
        left_numbers = cls._score_numbers(left)
        right_numbers = cls._score_numbers(right)
        if not left_numbers or not right_numbers:
            return True
        return (min(left_numbers), max(left_numbers)) != (min(right_numbers), max(right_numbers))

    async def _vinous_candidates(self, vintage: str) -> List[Dict[str, Any]]:
        conn = await db.get_conn()
        try:
            rows = await conn.fetch(
                """
                SELECT
                    id,
                    source_site,
                    source_file,
                    source_row,
                    producer,
                    wine_name,
                    full_wine_name,
                    vintage,
                    region,
                    appellation,
                    score_raw,
                    score_numeric,
                    reviewer,
                    drinking_window,
                    published_date,
                    tasting_date,
                    tasting_note
                FROM rap_records
                WHERE source_site = 'vinous'
                  AND vintage::text = $1
                  AND score_raw IS NOT NULL
                  AND (
                    coalesce(region, '') ILIKE '%Burgundy%'
                    OR coalesce(region, '') ILIKE '%Bourgogne%'
                    OR coalesce(full_wine_name, '') ILIKE '%Burgundy%'
                    OR coalesce(full_wine_name, '') ILIKE '%Gevrey%'
                    OR coalesce(full_wine_name, '') ILIKE '%Chambolle%'
                    OR coalesce(full_wine_name, '') ILIKE '%Vosne%'
                    OR coalesce(full_wine_name, '') ILIKE '%Beaune%'
                  )
                ORDER BY
                  CASE WHEN coalesce(tasting_note, '') <> '' THEN 0 ELSE 1 END,
                  id
                LIMIT 80
                """,
                vintage,
            )
            return [dict(row) for row in rows]
        finally:
            await conn.close()
