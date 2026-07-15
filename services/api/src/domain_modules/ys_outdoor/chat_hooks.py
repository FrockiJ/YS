from __future__ import annotations

from typing import Any

from ...services.cerp_business_fields_service import CerpBusinessFieldsService


class YsOutdoorChatHooks:
    def __init__(
        self,
        *,
        business_fields_service: CerpBusinessFieldsService | None = None,
    ) -> None:
        self._business_fields_service = business_fields_service or CerpBusinessFieldsService()

    def requested_business_fields(self, text: str) -> list[str]:
        return CerpBusinessFieldsService.requested_fields(text)

    def should_handle_business_fields(self, text: str) -> bool:
        return CerpBusinessFieldsService.should_handle(text)

    async def answer_business_fields(self, text: str, *, language: str) -> dict[str, Any] | None:
        return await self._business_fields_service.answer(text, language=language)
