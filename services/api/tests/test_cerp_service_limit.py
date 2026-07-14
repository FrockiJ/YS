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

        products = await service.search_products("wine", limit=3, page_size=50)

        self.assertEqual(len(products), 3)
        self.assertEqual([product["no"] for product in products], ["SKU-0", "SKU-1", "SKU-2"])
        self.assertEqual(service._collect_rows_by_keyword.await_args.kwargs["max_results"], 50)


if __name__ == "__main__":
    unittest.main()
