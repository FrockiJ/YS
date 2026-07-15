import re
from typing import Any, Dict, List, Optional

from sqlalchemy import select

from ...core.database import SessionLocal
from ...models.brand_source_domain import BrandSourceDomain


_NORMALIZE_RE = re.compile(r"[^\w]+", re.UNICODE)


def normalize_brand_name(value: Optional[str]) -> str:
    if not isinstance(value, str):
        return ""
    normalized = _NORMALIZE_RE.sub(" ", value.lower())
    return re.sub(r"\s+", " ", normalized).strip()


class BrandSourceDomainService:
    async def lookup_seeded_domains(self, brand_hint: Any) -> Dict[str, Any]:
        brand_names = self._coerce_brand_names(brand_hint)
        if not brand_names:
            return {"brand_names": [], "verified_domains": [], "candidate_domains": [], "rows": []}

        async with SessionLocal() as session:
            stmt = (
                select(BrandSourceDomain)
                .where(
                    BrandSourceDomain.brand_name_normalized.in_(brand_names),
                    BrandSourceDomain.verification_status.in_(["verified", "candidate"]),
                )
                .order_by(BrandSourceDomain.verification_status.asc(), BrandSourceDomain.source_tier.asc())
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()
            if not rows:
                fallback = await session.execute(
                    select(BrandSourceDomain)
                    .where(BrandSourceDomain.verification_status.in_(["verified", "candidate"]))
                    .order_by(BrandSourceDomain.verification_status.asc(), BrandSourceDomain.source_tier.asc())
                )
                rows = [
                    row for row in fallback.scalars().all()
                    if any(name in (row.brand_name_normalized or "") for name in brand_names)
                ]

        verified_domains: List[str] = []
        candidate_domains: List[str] = []
        serialized_rows: List[Dict[str, Any]] = []
        for row in rows:
            payload = {
                "brand_name_raw": row.brand_name_raw,
                "brand_name_normalized": row.brand_name_normalized,
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
            "brand_names": brand_names,
            "verified_domains": verified_domains,
            "candidate_domains": candidate_domains,
            "rows": serialized_rows,
        }

    @staticmethod
    def _coerce_brand_names(brand_hint: Any) -> List[str]:
        values = brand_hint if isinstance(brand_hint, list) else [brand_hint]
        normalized: List[str] = []
        for value in values:
            name = normalize_brand_name(str(value or ""))
            if name and name not in normalized:
                normalized.append(name)
        return normalized
