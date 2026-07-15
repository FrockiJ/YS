import asyncio
import os
from typing import Any, Dict, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..core.database import get_async_session
from ..models.label_description import LabelDescription
from ..pipelines.llm import openai_client

_MAX_CONCURRENCY = int(os.getenv("LABEL_DESC_MAX_CONCURRENCY", "3"))
_SEMAPHORE = asyncio.Semaphore(_MAX_CONCURRENCY)
_MAX_DESCRIPTION_CHARS = int(os.getenv("LABEL_DESC_MAX_CHARS", "220"))

_SYSTEM_PROMPT_TEMPLATE = (
    "You are a product label copywriter. "
    "Write a {language} paragraph within 220 characters. "
    "Keep product names as provided, avoid bullet points, and keep a refined, informative tone. "
    "Focus on introducing the product using only the provided fields: "
    "Brand, Product Name, Category, Version, Rating, Price."
)


class LabelDescriptionService:
    def __init__(self) -> None:
        self._session_factory = get_async_session

    async def get_description_record(
        self,
        code: str,
        lang: str,
    ) -> Optional[LabelDescription]:
        normalized = self._normalize_code(code)
        if not normalized:
            return None
        async with self._session_factory() as session:
            result = await session.execute(
                select(LabelDescription)
                .where(LabelDescription.product_code == normalized)
                .where(LabelDescription.lang == lang)
            )
            return result.scalar_one_or_none()

    async def get_existing_descriptions(
        self, codes: Iterable[str], lang: str
    ) -> Dict[str, str]:
        code_list = [self._normalize_code(code) for code in codes if code]
        if not code_list:
            return {}
        async with self._session_factory() as session:
            result = await session.execute(
                select(LabelDescription)
                .where(LabelDescription.product_code.in_(code_list))
                .where(LabelDescription.lang == lang)
            )
            rows = result.scalars().all()
            return {row.product_code: row.description for row in rows}

    async def ensure_description(self, product: Dict[str, Any], lang: str) -> Optional[str]:
        code = self._resolve_code(product)
        if not code:
            return None

        existing = await self._fetch_description(code, lang)
        if existing:
            return existing

        description = await self.generate_description(product, lang)
        if not description:
            return None

        async with self._session_factory() as session:
            record = LabelDescription(
                product_code=code,
                lang=lang,
                description=description,
            )
            session.add(record)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                return await self._fetch_description(code, lang)
        return description

    async def generate_description(
        self,
        product: Dict[str, Any],
        lang: str,
        *,
        instruction: Optional[str] = None,
        price_override: Optional[int] = None,
    ) -> Optional[str]:
        description = await self._generate_description(
            product,
            lang,
            instruction=instruction,
            price_override=price_override,
        )
        if not description:
            return None
        return self._trim_description(description)

    async def upsert_description(
        self,
        code: str,
        lang: str,
        description: str,
        price_override: Optional[int] = None,
    ) -> Optional[LabelDescription]:
        normalized = self._normalize_code(code)
        if not normalized:
            return None
        clean_description = self._trim_description(description)
        async with self._session_factory() as session:
            result = await session.execute(
                select(LabelDescription)
                .where(LabelDescription.product_code == normalized)
                .where(LabelDescription.lang == lang)
            )
            record = result.scalar_one_or_none()
            if record:
                record.description = clean_description
                if price_override is not None:
                    record.price_override = price_override
            else:
                record = LabelDescription(
                    product_code=normalized,
                    lang=lang,
                    description=clean_description,
                    price_override=price_override,
                )
                session.add(record)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                return None
            return record

    async def generate_missing_descriptions(
        self, products: Iterable[Dict[str, Any]], lang: str
    ) -> None:
        tasks = [self._generate_with_semaphore(product, lang) for product in products]
        if not tasks:
            return
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _generate_with_semaphore(self, product: Dict[str, Any], lang: str) -> None:
        async with _SEMAPHORE:
            await self.ensure_description(product, lang)

    async def _fetch_description(self, code: str, lang: str) -> Optional[str]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(LabelDescription)
                .where(LabelDescription.product_code == code)
                .where(LabelDescription.lang == lang)
            )
            row = result.scalar_one_or_none()
            if row:
                return row.description
        return None

    async def _generate_description(
        self,
        product: Dict[str, Any],
        lang: str,
        *,
        instruction: Optional[str] = None,
        price_override: Optional[int] = None,
    ) -> str:
        payload = self._build_payload(product, price_override=price_override)
        language = "Traditional Chinese" if (lang or "").lower().startswith("zh") else "English"
        system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(language=language)
        user_prompt = (
            "Create a product introduction for a label using the following details:\n"
            f"Brand: {payload['brand']}\n"
            f"Product Name: {payload['product_name']}\n"
            f"Category: {payload['category']}\n"
            f"Version: {payload['version']}\n"
            f"Rating: {payload['rating']}\n"
            f"Price: {payload['price']}\n"
        )
        if instruction:
            user_prompt += f"Instruction: {instruction.strip()}\n"
        return await openai_client.chat_complete(system_prompt, user_prompt, temperature=0.4)

    @staticmethod
    def _normalize_code(code: str) -> str:
        return code.strip().upper()

    def _resolve_code(self, product: Dict[str, Any]) -> str:
        candidates = [
            product.get("no"),
            product.get("id"),
            product.get("invn002"),
            product.get("code"),
        ]
        for candidate in candidates:
            if isinstance(candidate, str) and candidate.strip():
                return self._normalize_code(candidate)
        return ""

    @staticmethod
    def _resolve_name(product: Dict[str, Any]) -> str:
        for key in ("name_en", "name_ch", "name", "invn005", "title"):
            value = product.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    def _build_payload(
        self,
        product: Dict[str, Any],
        *,
        price_override: Optional[int] = None,
    ) -> Dict[str, str]:
        brand = str(product.get("brand") or product.get("supplier") or product.get("invn006") or "").strip()
        product_name = self._resolve_name(product)
        category = str(product.get("category") or product.get("region") or product.get("invn030") or "").strip()
        version = str(product.get("specification") or product.get("model_year") or product.get("version") or product.get("invn051") or "").strip()
        rating = str(product.get("rating") or product.get("invn804") or product.get("invn805") or "").strip()
        price_value = None
        if isinstance(price_override, int) and price_override > 0:
            price_value = price_override
        if price_value in (None, ""):
            price_value = product.get("list_price")
        if price_value in (None, ""):
            price_value = product.get("price")
        price_text = self._format_price(price_value)

        if not version:
            version = "N/A"

        return {
            "brand": brand,
            "product_name": product_name,
            "category": category,
            "version": version,
            "rating": rating,
            "price": price_text,
        }

    @staticmethod
    def _format_price(value: Any) -> str:
        try:
            amount = float(str(value).replace(",", ""))
        except (TypeError, ValueError):
            return ""
        return f"${amount:,.0f}"

    @staticmethod
    def _trim_description(value: str) -> str:
        if not value:
            return ""
        cleaned = value.strip()
        if _MAX_DESCRIPTION_CHARS > 0 and len(cleaned) > _MAX_DESCRIPTION_CHARS:
            return cleaned[:_MAX_DESCRIPTION_CHARS].rstrip()
        return cleaned
