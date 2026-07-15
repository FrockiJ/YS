from pathlib import Path


def test_chat_runtime_has_no_keyword_external_router():
    source = (Path(__file__).parents[1] / "src" / "api" / "routes_chat.py").read_text(encoding="utf-8")
    assert "_requires_external_verification" not in source
    assert "ProductIntentAnalysisService" not in source
    assert "ProductNeedExtractor" not in source
    assert "if False and" not in source


def test_planner_runtime_has_no_benchmark_case_switches():
    source = (Path(__file__).parents[1] / "src" / "services" / "ai" / "chat_planner.py").read_text(encoding="utf-8")
    assert "benchmark_case_id" not in source
    assert "case_id ==" not in source
