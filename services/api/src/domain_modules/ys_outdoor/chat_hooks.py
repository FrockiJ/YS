from __future__ import annotations

from typing import Any

from ...services.cerp_business_fields_service import CerpBusinessFieldsService
from ...services.cerp_recommendation_service import CerpRecommendationService


class YsOutdoorChatHooks:
    def __init__(
        self,
        *,
        business_fields_service: CerpBusinessFieldsService | None = None,
        recommendation_service: CerpRecommendationService | None = None,
    ) -> None:
        self._business_fields_service = business_fields_service or CerpBusinessFieldsService()
        self._recommendation_service = recommendation_service or CerpRecommendationService()

    def requested_business_fields(self, text: str) -> list[str]:
        return CerpBusinessFieldsService.requested_fields(text)

    def should_handle_business_fields(self, text: str) -> bool:
        return CerpBusinessFieldsService.should_handle(text)

    async def answer_business_fields(self, text: str, *, language: str) -> dict[str, Any] | None:
        return await self._business_fields_service.answer(text, language=language)

    def should_handle_recommendation(self, text: str) -> bool:
        return CerpRecommendationService.should_handle(text)

    async def recommend(
        self,
        text: str,
        *,
        language: str,
        rag_context: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        return await self._recommendation_service.recommend(
            text,
            language=language,
            rag_context=rag_context,
        )
