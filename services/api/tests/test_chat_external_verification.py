from src.api.routes_chat import _requires_external_verification


def test_current_product_advice_does_not_trigger_external_search():
    assert not _requires_external_verification("目前釣竿怎麼挑")


def test_erp_lookup_never_uses_current_word_as_external_trigger():
    assert not _requires_external_verification(
        "目前釣竿品牌有哪些？",
        task_type="erp_lookup",
    )


def test_product_recommendation_does_not_trigger_external_search():
    assert not _requires_external_verification(
        "目前適合的釣魚用品推薦",
        task_type="product_recommendation",
    )


def test_current_weather_still_requires_external_verification():
    assert _requires_external_verification("目前玉山天氣")


def test_explicit_url_remains_authoritative_even_for_erp_task():
    assert _requires_external_verification(
        "請核對這個商品",
        ["https://example.com/product"],
        task_type="erp_lookup",
    )
