from types import SimpleNamespace

from src.api.routes_edm import EdmPreviewCreatePayload, _normalize_preview_row, _serialize_preview


def test_edm_preview_payload_keeps_quote_schema_columns_and_row_extras():
    payload = EdmPreviewCreatePayload.model_validate(
        {
            "rows": [{"no": "CAMP0721", "product_name": "Trekking Pole", "brand": "PeakPath"}],
            "table_columns": [
                {"key": "product_name", "label": "Product", "width": 220},
                {"key": "brand", "label": "Brand", "width": 130},
            ],
        }
    )

    assert payload.rows[0].model_dump()["brand"] == "PeakPath"
    assert [column.key for column in payload.table_columns] == ["product_name", "brand"]


def test_edm_preview_normalizes_legacy_empty_spec_to_canonical_specification():
    payload = EdmPreviewCreatePayload.model_validate(
        {
            "rows": [
                {
                    "no": "CAMP0002",
                    "product": "PinePeak Tarp",
                    "spec": "",
                    "specification": "4x4m / UV coated",
                }
            ]
        }
    )
    row = _normalize_preview_row(payload.rows[0])
    assert row["specification"] == "4x4m / UV coated"
    assert "spec" not in row


def test_edm_preview_serializer_returns_persisted_column_snapshot():
    preview = SimpleNamespace(
        share_token="SHARE01",
        share_url="https://example.test/edm/share/SHARE01",
        quote_no="SEQ202607140001",
        quote_date=SimpleNamespace(isoformat=lambda: "2026-07-14T00:00:00+00:00"),
        sales_rep="sales",
        hero_text="Outdoor picks",
        banner_snapshot={},
        rows_snapshot=[{"no": "CAMP0721", "brand": "PeakPath"}],
        table_columns_snapshot=[{"key": "brand", "label": "Brand", "width": 130}],
        project_snapshot={},
        conversation_id=None,
    )

    serialized = _serialize_preview(preview)
    assert serialized["table_columns"] == [
        {"key": "brand", "label": "Brand", "width": 130}
    ]
