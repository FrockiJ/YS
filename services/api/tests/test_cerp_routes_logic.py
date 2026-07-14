import ast
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _load_route_helpers():
    path = Path(__file__).resolve().parents[1] / "src" / "api" / "routes_cerp.py"
    source = path.read_text(encoding="utf-8")
    module = ast.parse(source)
    needed = {
        "_sort_rows_by_stock",
        "_stock_value_for_row",
        "_normalize_products_info_stock_fields",
        "_apply_stock_filtering",
    }
    segments = [
        "from typing import Any, Dict, Optional\n",
        "from src.services.cerp_service import CerpService\n",
    ]
    has_enrich_field = False
    export_products_source = ""
    search_products_source = ""
    for node in module.body:
        if isinstance(node, ast.ClassDef) and node.name == "ProductInfoRequest":
            has_enrich_field = any(
                isinstance(item, ast.AnnAssign)
                and isinstance(item.target, ast.Name)
                and item.target.id == "enrich_product_fields"
                for item in node.body
            )
        if isinstance(node, ast.FunctionDef) and node.name in needed:
            segments.append(ast.get_source_segment(source, node))
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "export_products":
            export_products_source = ast.get_source_segment(source, node) or ""
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "search_products":
            search_products_source = ast.get_source_segment(source, node) or ""
    namespace = {}
    exec("\n\n".join(segments), namespace)
    return (
        namespace["_sort_rows_by_stock"],
        namespace["_apply_stock_filtering"],
        namespace["_normalize_products_info_stock_fields"],
        has_enrich_field,
        export_products_source,
        search_products_source,
    )


(
    SORT_ROWS_BY_STOCK,
    APPLY_STOCK_FILTERING,
    NORMALIZE_PRODUCTS_INFO_STOCK_FIELDS,
    HAS_ENRICH_FIELD,
    EXPORT_PRODUCTS_SOURCE,
    SEARCH_PRODUCTS_SOURCE,
) = _load_route_helpers()


class CerpRoutesLogicTests(unittest.TestCase):
    def test_product_info_request_can_disable_enrichment(self):
        self.assertTrue(HAS_ENRICH_FIELD)

    def test_stock_sorting_uses_only_inv1015_warehouses(self):
        rows = [
            {"invn002": "ZERO", "invn045": 999, "wd4inv1as": [{"inv1015": 0}]},
            {"invn002": "FALLBACK", "invn045": 10},
            {"invn002": "WAREHOUSE", "wd4inv1as": [{"inv1015": 2}, {"inv1015": 12}]},
        ]
        sorted_rows = SORT_ROWS_BY_STOCK(rows)
        self.assertEqual([row["invn002"] for row in sorted_rows], ["WAREHOUSE"])

    def test_stock_filtering_uses_only_inv1015_warehouses(self):
        response = {
            "data": {
                "wd4invnas": [
                    {"invn002": "LOW", "invn045": 3},
                    {"invn002": "OK", "wd4inv1as": [{"inv1015": 2}, {"inv1015": 5}]},
                    {"invn002": "ZERO", "invn045": 99, "wd4inv1as": [{"inv1015": 0}]},
                ]
            }
        }
        filtered = APPLY_STOCK_FILTERING(response, 5, None)
        rows = filtered["data"]["wd4invnas"]
        self.assertEqual([row["invn002"] for row in rows], ["OK"])

    def test_products_info_enrichment_adds_normalized_stock_fields(self):
        row = {
            "invn002": "BOR-CC0-MSE00000-100",
            "invn045": 198,
            "wd4inv1as": [
                {"inv1002": "RA-S", "name002": "仁愛-門市", "inv1015": 4},
                {"inv1002": "TM-A", "name002": "潭美-A區", "inv1015": 194},
            ],
        }
        normalized = NORMALIZE_PRODUCTS_INFO_STOCK_FIELDS(row)
        self.assertEqual(normalized["stock_qty"], 198)
        self.assertEqual(normalized["stock"], 198)
        self.assertEqual(normalized["total_stock"], 198)
        self.assertEqual(normalized["cerp_stock_reference"], 198)
        self.assertEqual(
            [(wh["warehouse_code"], wh["quantity"]) for wh in normalized["warehouses"]],
            [("RA-S", 4), ("TM-A", 194)],
        )

    def test_products_export_does_not_use_invn053_stock_params(self):
        self.assertNotIn("invn053b", EXPORT_PRODUCTS_SOURCE)
        self.assertNotIn("invn053e", EXPORT_PRODUCTS_SOURCE)

    def test_products_search_requires_live_cerp_stock(self):
        self.assertIn("raise_on_error=True", SEARCH_PRODUCTS_SOURCE)


if __name__ == "__main__":
    unittest.main()
