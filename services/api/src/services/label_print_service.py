from typing import Any, Dict, List, Optional

from sqlalchemy import select, delete
from sqlalchemy.exc import IntegrityError

from ..core.database import get_async_session
from ..models.label_print_item import LabelPrintItem
from ..utils.cerp_export_lookup import find_export_row_by_code
from .label_description_service import LabelDescriptionService


class LabelPrintService:
    def __init__(self) -> None:
        self._session_factory = get_async_session
        self._label_description_service = LabelDescriptionService()

    @staticmethod
    def _normalize_code(code: str) -> str:
        return (code or "").strip().upper()

    @staticmethod
    def _normalize_positive_int(value: Any) -> Optional[int]:
        if value in (None, ""):
            return None
        try:
            number = int(value)
        except (TypeError, ValueError):
            return None
        return number if number > 0 else None

    @classmethod
    def _merge_snapshot(
        cls,
        existing_snapshot: Optional[Dict[str, Any]],
        next_snapshot: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        merged = dict(existing_snapshot or {})
        for key, value in (next_snapshot or {}).items():
            if value in (None, "", [], {}):
                continue
            if merged.get(key) in (None, "", [], {}):
                merged[key] = value
        return merged

    @classmethod
    def _has_price_conflict(cls, existing_price: Any, incoming_price: Any) -> bool:
        normalized_existing = cls._normalize_positive_int(existing_price)
        normalized_incoming = cls._normalize_positive_int(incoming_price)
        if normalized_incoming is None:
            return False
        if normalized_existing is None:
            return False
        return normalized_existing != normalized_incoming

    @classmethod
    def _compact_snapshot(cls, snapshot: Optional[Dict[str, Any]], code: str) -> Dict[str, Any]:
        if not isinstance(snapshot, dict):
            return {}

        def pick(keys: List[str]) -> Optional[Any]:
            for key in keys:
                value = snapshot.get(key)
                if value not in (None, "", [], {}):
                    return value
            return None

        normalized_code = cls._normalize_code(code)
        name_en = pick(["name_en", "name", "invn005", "name_ch"])
        name_ch = pick(["name_ch", "name", "invn005", "name_en"])
        data = {
            "no": cls._normalize_code(pick(["no", "id", "invn002"]) or normalized_code),
            "name_en": name_en,
            "name_ch": name_ch,
            "producer": pick(["producer", "invn006"]),
            "vintage": pick(["vintage", "invn051"]),
            "region": pick(["region", "invn030"]),
            "rating": pick(["rating", "invn804", "invn805", "invn803"]),
            "list_price": pick(["list_price", "invn013"]),
            "price": pick(["price", "invn015", "invn013"]),
        }
        return {key: value for key, value in data.items() if value not in (None, "", [], {})}

    def _snapshot_from_export(self, code: str) -> Dict[str, Any]:
        row = find_export_row_by_code(code)
        if not row:
            return {}
        return self._compact_snapshot(
            {
                "no": row.get("invn002"),
                "name": row.get("invn005"),
                "producer": row.get("invn006"),
                "vintage": row.get("invn051"),
                "region": row.get("invn030"),
                "rating": row.get("invn804") or row.get("invn805") or row.get("invn803"),
                "list_price": row.get("invn013"),
                "price": row.get("invn015") or row.get("invn013"),
            },
            code,
        )

    async def add_item(
        self,
        user_id: int,
        code: str,
        size: str,
        *,
        product_snapshot: Optional[Dict[str, Any]] = None,
        quantity: int = 1,
        price_override: Optional[int] = None,
    ) -> Dict[str, Any]:
        normalized = self._normalize_code(code)
        if not normalized:
            return {"status": "invalid", "record": None}
        normalized_quantity = self._normalize_positive_int(quantity)
        if normalized_quantity is None:
            return {"status": "invalid", "record": None}
        normalized_price = self._normalize_positive_int(price_override)
        snapshot = self._compact_snapshot(product_snapshot or {}, normalized)
        if not snapshot:
            snapshot = self._snapshot_from_export(normalized)
        async with self._session_factory() as session:
            result = await session.execute(
                select(LabelPrintItem)
                .where(LabelPrintItem.user_id == user_id)
                .where(LabelPrintItem.product_code == normalized)
                .where(LabelPrintItem.size == size)
            )
            existing = result.scalar_one_or_none()
            if existing:
                return await self._merge_existing_record(
                    session,
                    existing,
                    quantity=normalized_quantity,
                    price_override=normalized_price,
                    product_snapshot=snapshot,
                )
            record = LabelPrintItem(
                user_id=user_id,
                product_code=normalized,
                size=size,
                quantity=normalized_quantity,
                price_override=normalized_price,
                product_snapshot=snapshot or {},
            )
            session.add(record)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                result = await session.execute(
                    select(LabelPrintItem)
                    .where(LabelPrintItem.user_id == user_id)
                    .where(LabelPrintItem.product_code == normalized)
                    .where(LabelPrintItem.size == size)
                )
                existing = result.scalar_one_or_none()
                if existing:
                    return await self._merge_existing_record(
                        session,
                        existing,
                        quantity=normalized_quantity,
                        price_override=normalized_price,
                        product_snapshot=snapshot,
                    )
                return {"status": "invalid", "record": None}
            return {"status": "created", "record": record}

    async def _merge_existing_record(
        self,
        session,
        existing: LabelPrintItem,
        *,
        quantity: int,
        price_override: Optional[int],
        product_snapshot: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if self._has_price_conflict(existing.price_override, price_override):
            return {"status": "conflict", "record": existing}

        changed = False
        merged_snapshot = self._merge_snapshot(existing.product_snapshot, product_snapshot)
        if merged_snapshot != (existing.product_snapshot or {}):
            existing.product_snapshot = merged_snapshot
            changed = True
        if self._normalize_positive_int(existing.price_override) is None and price_override is not None:
            existing.price_override = price_override
            changed = True

        next_quantity = max(int(existing.quantity or 0), 0) + quantity
        if next_quantity != existing.quantity:
            existing.quantity = next_quantity
            changed = True

        if changed:
            await session.commit()
        return {"status": "merged", "record": existing}

    async def delete_item(self, user_id: int, item_id: str) -> bool:
        async with self._session_factory() as session:
            result = await session.execute(
                select(LabelPrintItem)
                .where(LabelPrintItem.id == item_id)
                .where(LabelPrintItem.user_id == user_id)
            )
            record = result.scalar_one_or_none()
            if not record:
                return False
            await session.delete(record)
            await session.commit()
            return True

    async def reset_items(self, user_id: int) -> None:
        async with self._session_factory() as session:
            await session.execute(
                delete(LabelPrintItem).where(LabelPrintItem.user_id == user_id)
            )
            await session.commit()

    async def list_items(self, user_id: int, lang: str = "zh-TW") -> List[Dict[str, Any]]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(LabelPrintItem)
                .where(LabelPrintItem.user_id == user_id)
                .order_by(LabelPrintItem.created_at.asc())
            )
            items = result.scalars().all()
            responses: List[Dict[str, Any]] = []
            updated = False
            for record in items:
                product_snapshot = record.product_snapshot or {}
                if not product_snapshot:
                    product_snapshot = self._snapshot_from_export(record.product_code)
                    if product_snapshot:
                        record.product_snapshot = product_snapshot
                        updated = True
                description_record = await self._label_description_service.get_description_record(
                    record.product_code,
                    lang,
                )
                responses.append(
                    {
                        "id": str(record.id),
                        "code": record.product_code,
                        "size": record.size,
                        "quantity": record.quantity,
                        "description": description_record.description if description_record else "",
                        "price_override": (
                            record.price_override
                            if self._normalize_positive_int(record.price_override) is not None
                            else (description_record.price_override if description_record else None)
                        ),
                        "product_snapshot": product_snapshot or {},
                    }
                )
            if updated:
                await session.commit()
            return responses

    async def update_item_price_override(
        self,
        user_id: int,
        item_id: str,
        *,
        price_override: int,
    ) -> Optional[LabelPrintItem]:
        normalized_price = self._normalize_positive_int(price_override)
        if normalized_price is None:
            return None
        async with self._session_factory() as session:
            result = await session.execute(
                select(LabelPrintItem)
                .where(LabelPrintItem.id == item_id)
                .where(LabelPrintItem.user_id == user_id)
            )
            record = result.scalar_one_or_none()
            if not record:
                return None
            record.price_override = normalized_price
            await session.commit()
            return record

    async def get_total_quantity(self, user_id: int) -> int:
        async with self._session_factory() as session:
            result = await session.execute(
                select(LabelPrintItem)
                .where(LabelPrintItem.user_id == user_id)
            )
            items = result.scalars().all()
        return sum(item.quantity or 0 for item in items)
