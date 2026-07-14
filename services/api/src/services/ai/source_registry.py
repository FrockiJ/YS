import re
from typing import Any, Dict, List, Optional

from sqlalchemy import select

from ...core.database import SessionLocal
from ...models.producer_source_domain import ProducerSourceDomain


_NORMALIZE_RE = re.compile(r"[^\w]+", re.UNICODE)


def normalize_producer_name(value: Optional[str]) -> str:
    if not isinstance(value, str):
        return ""
    normalized = _NORMALIZE_RE.sub(" ", value.lower())
    return re.sub(r"\s+", " ", normalized).strip()


class ProducerSourceDomainService:
    async def lookup_seeded_domains(self, producer_hint: Any) -> Dict[str, Any]:
        producer_names = self._coerce_producer_names(producer_hint)
        if not producer_names:
            return {
                "producer_names": [],
                "verified_domains": [],
                "candidate_domains": [],
                "rows": [],
            }

        async with SessionLocal() as session:
            stmt = (
                select(ProducerSourceDomain)
                .where(
                    ProducerSourceDomain.producer_name_normalized.in_(producer_names),
                    ProducerSourceDomain.verification_status.in_(["verified", "candidate"]),
                )
                .order_by(ProducerSourceDomain.verification_status.asc(), ProducerSourceDomain.source_tier.asc())
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()
            if not rows and producer_names:
                fallback_stmt = (
                    select(ProducerSourceDomain)
                    .where(
                        ProducerSourceDomain.verification_status.in_(["verified", "candidate"]),
                    )
                    .order_by(ProducerSourceDomain.verification_status.asc(), ProducerSourceDomain.source_tier.asc())
                )
                fallback_result = await session.execute(fallback_stmt)
                rows = [
                    row
                    for row in fallback_result.scalars().all()
                    if any(name in (row.producer_name_normalized or "") for name in producer_names)
                ]

        verified_domains: List[str] = []
        candidate_domains: List[str] = []
        serialized_rows: List[Dict[str, Any]] = []
        for row in rows:
            payload = {
                "producer_name_raw": row.producer_name_raw,
                "producer_name_normalized": row.producer_name_normalized,
                "source_kind": row.source_kind,
                "domain": row.domain,
                "source_tier": row.source_tier,
                "source_origin": row.source_origin,
                "verification_status": row.verification_status,
                "region_scope": row.region_scope,
                "notes": row.notes,
            }
            serialized_rows.append(payload)
            domain = (row.domain or "").strip().lower()
            if not domain:
                continue
            if row.verification_status == "verified" and domain not in verified_domains:
                verified_domains.append(domain)
            if row.verification_status == "candidate" and domain not in candidate_domains:
                candidate_domains.append(domain)

        return {
            "producer_names": producer_names,
            "verified_domains": verified_domains,
            "candidate_domains": candidate_domains,
            "rows": serialized_rows,
        }

    @staticmethod
    def _coerce_producer_names(producer_hint: Any) -> List[str]:
        values = producer_hint if isinstance(producer_hint, list) else [producer_hint]
        normalized: List[str] = []
        for value in values:
            name = normalize_producer_name(str(value or ""))
            if name and name not in normalized:
                normalized.append(name)
        return normalized
