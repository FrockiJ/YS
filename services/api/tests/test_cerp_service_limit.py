import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.services.cerp_service import CerpService


class CerpServiceLimitTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_products_honors_requested_limit_after_page_fetch(self):
        service = CerpService(client=Mock())
        rows = {f"SKU-{index}": {"invn002": f"SKU-{index}"} for index in range(8)}
        service._collect_rows_by_keyword = AsyncMock(return_value=rows)
        service._map_row = Mock(side_effect=lambda row, _: {"no": row["invn002"], "stock_qty": 1})
        service._score_keyword = Mock(return_value=1.0)

        products = await service.search_products("tent", limit=3, page_size=50)

        self.assertEqual(len(products), 3)
        self.assertEqual([product["no"] for product in products], ["SKU-0", "SKU-1", "SKU-2"])
        self.assertEqual(service._collect_rows_by_keyword.await_args.kwargs["max_results"], 50)

    async def test_keyword_search_queries_name_brand_category_and_specification_fields(self):
        client = Mock()
        response = {
            "data": {
                "wd4invnas": [{"invn002": "SKU-1", "invn005": "Fishing rod"}],
                "wd4inv1as": [],
            }
        }
        client.export_products = AsyncMock(return_value=response)
        client.export_products_info = AsyncMock(return_value=response)
        service = CerpService(client=client)

        rows = await service._collect_rows_by_keyword(
            "rod", max_results=10, page_size=10, max_pages=1
        )

        self.assertEqual(set(rows), {"SKU-1"})
        searched_fields = {
            next(iter(call.kwargs["paramchar1"]))
            for call in client.export_products.await_args_list
        }
        self.assertEqual(
            searched_fields,
            {"invn005", "invn006", "invn030", "invn051", "invn807"},
        )


if __name__ == "__main__":
    unittest.main()
