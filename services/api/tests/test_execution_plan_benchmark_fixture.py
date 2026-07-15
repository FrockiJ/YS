import json
from pathlib import Path


FIXTURE = Path(__file__).parent / "fixtures" / "chat_execution_plan_v2.json"
RUNTIME_FILES = (
    Path(__file__).parents[1] / "src" / "services" / "ai" / "chat_planner.py",
    Path(__file__).parents[1] / "src" / "services" / "ai" / "erp_ast.py",
    Path(__file__).parents[1] / "src" / "api" / "routes_chat.py",
)


def test_execution_plan_benchmark_has_paraphrases_and_counterexamples():
    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert len(cases) >= 10
    assert all(item.get("paraphrases") for item in cases)
    assert any("counterexample" in item["id"] for item in cases)
    assert any(item["expected"].get("external") for item in cases)
    assert any(item["expected"].get("operation") == "inventory" for item in cases)


def test_benchmark_prompts_do_not_leak_into_runtime_shortcuts():
    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))
    runtime = "\n".join(path.read_text(encoding="utf-8") for path in RUNTIME_FILES).casefold()
    for item in cases:
        assert item["prompt"].casefold() not in runtime
        for paraphrase in item["paraphrases"]:
            assert paraphrase.casefold() not in runtime
