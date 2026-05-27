from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from pc_build_agent.agents.dynamic_clarification import DynamicClarificationAgent
from pc_build_agent.agents.external_search import ExternalSearchBuildAgent, should_use_external_search
from pc_build_agent.agents.selection import PartsSelectionAgent, SelectionResult
from pc_build_agent.agents.validation_engine import ValidationOutcome, validate_and_select
from pc_build_agent.models.schemas import (
    BuildLine,
    BudgetModel,
    ParsedRequirements,
    ProductRecord,
    RecommendRequest,
    RequirementsModel,
    SpecifiedPartModel,
)
from pc_build_agent.pipeline import orchestrator


class _FakeStore:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str, str]] = []

    def create_session(self) -> str:
        return "sid-debug"

    def session_exists(self, sid: str) -> bool:
        return sid == "sid-debug"

    def append_message(self, sid: str, role: str, content: str, meta=None) -> None:
        self.messages.append((sid, role, content))

    def list_turns(self, sid: str, limit: int = 40):
        user_messages = [content for msg_sid, role, content in self.messages if msg_sid == sid and role == "user"]
        return [SimpleNamespace(role="user", content=text) for text in user_messages]


class _FakeRepo:
    def load(self):
        return []


def _parsed() -> ParsedRequirements:
    parsed = ParsedRequirements(
        need_clarification=False,
        requirements=RequirementsModel(
            budget=BudgetModel(min=6000, max=7000),
            appearance={"appearance_priority": "low", "color": "no_preference"},
        ),
        weights={"performance": 0.5, "price": 0.3, "appearance": 0.1, "other": 0.1},
        explanation="debug test",
    )
    parsed.requirements.usage = ["3A游戏"]
    parsed.__dict__["requirement_profile"] = {
        "original_user_text": "用户：测试装机需求",
        "performance": {"secondary_usage": ["aaa_gaming"]},
        "appearance": {"appearance_priority": "low", "color": "no_preference"},
        "price": {"budget_extraction": {"min_budget": 6000, "max_budget": 7000}},
        "other": {},
        "selection_context": {},
    }
    return parsed


def _selection_result() -> SelectionResult:
    return SelectionResult(
        sorted_by_category={},
        scores_by_category={},
        top3_preview={},
        debug={
            "requirement_profile": {"selection_context": {}},
            "categories": ["处理器", "显卡"],
            "by_category": {
                "显卡": {
                    "raw_count": 2,
                    "after_specified_parts_count": 1,
                    "after_must_satisfy_count": 1,
                    "after_avoid_count": 1,
                    "final_candidate_count": 1,
                    "filter_warnings": [],
                    "top5": [],
                }
            },
            "warnings": {},
        },
    )


def _empty_selection_result() -> SelectionResult:
    return SelectionResult(
        sorted_by_category={},
        scores_by_category={},
        top3_preview={},
        debug={
            "requirement_profile": {"selection_context": {}},
            "categories": ["处理器", "显卡"],
            "by_category": {
                "处理器": {
                    "raw_count": 0,
                    "after_specified_parts_count": 0,
                    "after_must_satisfy_count": 0,
                    "after_avoid_count": 0,
                    "final_candidate_count": 0,
                    "filter_warnings": [],
                    "top5": [],
                }
            },
            "warnings": {},
        },
    )


def _validation_outcome() -> ValidationOutcome:
    return ValidationOutcome(
        status="success",
        final_build=[BuildLine(category="显卡", sku_id="gpu-1", name="测试显卡", price=3999)],
        total_price=3999,
        budget_check={"status": "within_budget"},
        compatibility_check={"status": "pass", "warnings": []},
        risk_check={"status": "pass", "warnings": []},
        unmet_constraints=[],
        alternative_suggestions=[],
        debug={
            "initial_parts": {},
            "diagnose_steps": [],
            "fix_steps": [],
            "budget_steps": [],
            "final_parts": {},
            "final_status": "success",
            "final_issues": [],
        },
    )


def _empty_validation_outcome() -> ValidationOutcome:
    return ValidationOutcome(
        status="success",
        final_build=[],
        total_price=0,
        budget_check={"status": "unknown"},
        compatibility_check={"status": "pass", "warnings": []},
        risk_check={"status": "pass", "warnings": []},
        unmet_constraints=[],
        alternative_suggestions=[],
        debug={"final_status": "success", "final_parts": {}},
    )


def _parsed_for_clarification(
    *,
    budget: BudgetModel | None = None,
    usage: list[str] | None = None,
    appearance: dict | None = None,
    performance: dict | None = None,
    profile_price: dict | None = None,
    profile_appearance: dict | None = None,
) -> ParsedRequirements:
    parsed = ParsedRequirements(
        need_clarification=False,
        requirements=RequirementsModel(
            budget=budget,
            appearance=appearance or {},
            performance=performance or {},
        ),
        weights={"performance": 0.5, "price": 0.3, "appearance": 0.1, "other": 0.1},
        explanation="clarification matrix",
    )
    parsed.requirements.usage = usage or []
    parsed.__dict__["requirement_profile"] = {
        "performance": performance or {},
        "appearance": profile_appearance if profile_appearance is not None else (appearance or {}),
        "price": profile_price or {},
        "other": {},
        "selection_context": {},
    }
    return parsed


def _product(category: str, sku_id: str, name: str, price: float, specs: dict | None = None) -> ProductRecord:
    return ProductRecord(
        sku_id=sku_id,
        category=category,
        name=name,
        price=price,
        specs=specs or {},
        tags=[],
        component_type=(specs or {}).get("component_type"),
        brand=(specs or {}).get("brand"),
        current_price=price,
    )


def test_recommend_does_not_create_debug_outputs_when_disabled(monkeypatch, tmp_path):
    debug_dir = tmp_path / "debug_outputs"
    monkeypatch.delenv("PC_GUIDE_DEBUG", raising=False)
    monkeypatch.setattr(orchestrator, "_project_root", lambda: tmp_path)
    monkeypatch.setattr(orchestrator, "get_session_store", lambda: _FakeStore())
    monkeypatch.setattr(orchestrator, "get_product_repository", lambda: _FakeRepo())
    monkeypatch.setattr(orchestrator, "get_client", lambda: object())
    monkeypatch.setattr(orchestrator, "safe_parse", lambda transcript, client=None, trace_sink=None: _parsed())
    monkeypatch.setattr(orchestrator, "retrieve_candidates", lambda parsed, pool: _selection_result())
    monkeypatch.setattr(orchestrator, "validate_and_select", lambda parsed, sorted_by_category: _validation_outcome())
    monkeypatch.setattr(orchestrator, "render_final_markdown", lambda parsed, outcome, polish=False: "# debug off")

    resp = orchestrator.recommend(RecommendRequest(user_query="测试 debug 关闭"))

    assert resp.code == 0
    assert not debug_dir.exists()


def test_recommend_writes_debug_outputs_when_enabled(monkeypatch, tmp_path):
    debug_dir = tmp_path / "debug_outputs"
    monkeypatch.setenv("PC_GUIDE_DEBUG", "1")
    monkeypatch.setattr(orchestrator, "_project_root", lambda: tmp_path)
    monkeypatch.setattr(orchestrator, "get_session_store", lambda: _FakeStore())
    monkeypatch.setattr(orchestrator, "get_product_repository", lambda: _FakeRepo())
    monkeypatch.setattr(orchestrator, "get_client", lambda: object())
    monkeypatch.setattr(orchestrator, "safe_parse", lambda transcript, client=None, trace_sink=None: _parsed())
    monkeypatch.setattr(orchestrator, "retrieve_candidates", lambda parsed, pool: _selection_result())
    monkeypatch.setattr(orchestrator, "validate_and_select", lambda parsed, sorted_by_category: _validation_outcome())
    monkeypatch.setattr(orchestrator, "render_final_markdown", lambda parsed, outcome, polish=False: "# final output")

    resp = orchestrator.recommend(RecommendRequest(user_query="测试 debug 开启"))

    assert resp.code == 0
    assert debug_dir.exists()

    trace_path = debug_dir / "latest_trace.json"
    requirement_path = debug_dir / "latest_requirement_profile.json"
    selection_path = debug_dir / "latest_selection_debug.json"
    validation_path = debug_dir / "latest_validation_debug.json"
    final_md_path = debug_dir / "latest_final_output.md"

    for path in [trace_path, requirement_path, selection_path, validation_path]:
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data is not None

    requirement_data = json.loads(requirement_path.read_text(encoding="utf-8"))
    assert "raw_input" in requirement_data
    assert "parsed" in requirement_data
    assert "requirement_profile" in requirement_data

    selection_data = json.loads(selection_path.read_text(encoding="utf-8"))
    validation_data = json.loads(validation_path.read_text(encoding="utf-8"))
    assert isinstance(selection_data, dict)
    assert isinstance(validation_data, dict)

    assert final_md_path.exists()
    assert final_md_path.read_text(encoding="utf-8") == "# final output"


def test_recommend_continues_selection_even_if_first_layer_marks_missing_fields(monkeypatch, tmp_path):
    parsed = _parsed()
    parsed.need_clarification = True
    parsed.missing_fields = ["目标分辨率", "是否需要WiFi"]
    parsed.clarification_question = "这个问题不应阻断流程"

    monkeypatch.delenv("PC_GUIDE_DEBUG", raising=False)
    monkeypatch.setattr(orchestrator, "_project_root", lambda: tmp_path)
    monkeypatch.setattr(orchestrator, "get_session_store", lambda: _FakeStore())
    monkeypatch.setattr(orchestrator, "get_product_repository", lambda: _FakeRepo())
    monkeypatch.setattr(orchestrator, "get_client", lambda: object())
    monkeypatch.setattr(orchestrator, "safe_parse", lambda transcript, client=None, trace_sink=None: parsed)
    monkeypatch.setattr(orchestrator, "retrieve_candidates", lambda parsed, pool: _selection_result())
    monkeypatch.setattr(orchestrator, "validate_and_select", lambda parsed, sorted_by_category: _validation_outcome())
    monkeypatch.setattr(orchestrator, "render_final_markdown", lambda parsed, outcome, polish=False: "# proceed")

    resp = orchestrator.recommend(RecommendRequest(user_query="测试继续选配"))

    assert resp.code == 0
    assert resp.message == "success"
    assert resp.data.need_clarification is False
    assert resp.data.final_build
    assert "可选优化信息：目标分辨率、是否需要WiFi" in resp.data.recommendation_reason


def test_recommend_returns_dynamic_clarification_before_selection(monkeypatch, tmp_path):
    parsed = ParsedRequirements(
        need_clarification=False,
        requirements=RequirementsModel(),
        weights={"performance": 0.5, "price": 0.3, "appearance": 0.1, "other": 0.1},
        explanation="needs budget",
    )
    parsed.requirements.usage = ["3A游戏"]
    parsed.__dict__["requirement_profile"] = {
        "performance": {"secondary_usage": ["aaa_gaming"]},
        "appearance": {},
        "price": {},
        "other": {},
        "selection_context": {},
    }

    def fail_selection(parsed, pool):  # noqa: ANN001
        raise AssertionError("selection should not run when clarification is required")

    monkeypatch.delenv("PC_GUIDE_DEBUG", raising=False)
    monkeypatch.setattr(orchestrator, "_project_root", lambda: tmp_path)
    monkeypatch.setattr(orchestrator, "get_session_store", lambda: _FakeStore())
    monkeypatch.setattr(orchestrator, "get_product_repository", lambda: _FakeRepo())
    monkeypatch.setattr(orchestrator, "get_client", lambda: object())
    monkeypatch.setattr(orchestrator, "safe_parse", lambda transcript, client=None, trace_sink=None: parsed)
    monkeypatch.setattr(orchestrator, "retrieve_candidates", fail_selection)

    resp = orchestrator.recommend(RecommendRequest(user_query="主要玩3A"))

    assert resp.code == 0
    assert resp.message == "need_clarification"
    assert resp.data.need_clarification is True
    assert resp.data.missing_fields == ["预算范围", "外观偏好"]
    assert resp.data.clarification_cards
    assert resp.data.final_build == []


def test_recommend_uses_external_search_fallback_when_local_catalog_is_empty(monkeypatch, tmp_path):
    monkeypatch.delenv("PC_GUIDE_DEBUG", raising=False)
    monkeypatch.setattr(orchestrator, "_project_root", lambda: tmp_path)
    monkeypatch.setattr(orchestrator, "get_session_store", lambda: _FakeStore())
    monkeypatch.setattr(orchestrator, "get_product_repository", lambda: _FakeRepo())
    monkeypatch.setattr(orchestrator, "get_client", lambda: SimpleNamespace(api_key=""))
    monkeypatch.setattr(orchestrator, "safe_parse", lambda transcript, client=None, trace_sink=None: _parsed())
    monkeypatch.setattr(orchestrator, "retrieve_candidates", lambda parsed, pool: _empty_selection_result())
    monkeypatch.setattr(orchestrator, "validate_and_select", lambda parsed, sorted_by_category: _empty_validation_outcome())

    resp = orchestrator.recommend(RecommendRequest(user_query="预算7000，玩3A"))

    assert resp.code == 0
    assert resp.message == "external_search_fallback"
    assert resp.data.status == "external_search_fallback"
    assert resp.data.recommendation_source == "external_search"
    assert resp.data.final_build
    assert all(item.sku_id.startswith("external-search-") for item in resp.data.final_build)
    assert all(item.source == "external_search" for item in resp.data.final_build)
    assert resp.data.total_price >= 6000
    assert resp.data.risk_notes


def test_recommend_keeps_failed_local_outcome_when_catalog_candidates_exist(monkeypatch, tmp_path):
    failed = ValidationOutcome(
        status="failed_with_alternative",
        final_build=[],
        total_price=8200,
        budget_check={"status": "over_budget"},
        compatibility_check={"status": "pass", "warnings": []},
        risk_check={"status": "fail", "warnings": ["预算无法闭合"]},
        unmet_constraints=["price"],
        alternative_suggestions=["降低显卡档位或提高预算。"],
        debug={"final_status": "failed_with_alternative"},
    )

    monkeypatch.delenv("PC_GUIDE_DEBUG", raising=False)
    monkeypatch.setattr(orchestrator, "_project_root", lambda: tmp_path)
    monkeypatch.setattr(orchestrator, "get_session_store", lambda: _FakeStore())
    monkeypatch.setattr(orchestrator, "get_product_repository", lambda: _FakeRepo())
    monkeypatch.setattr(orchestrator, "get_client", lambda: SimpleNamespace(api_key=""))
    monkeypatch.setattr(orchestrator, "safe_parse", lambda transcript, client=None, trace_sink=None: _parsed())
    monkeypatch.setattr(orchestrator, "retrieve_candidates", lambda parsed, pool: _selection_result())
    monkeypatch.setattr(orchestrator, "validate_and_select", lambda parsed, sorted_by_category: failed)

    resp = orchestrator.recommend(RecommendRequest(user_query="预算7000，玩3A，外观无所谓"))

    assert resp.code == 0
    assert resp.message == "failed_with_alternative"
    assert resp.data.recommendation_source == "local_catalog"
    assert resp.data.alternative_suggestions == ["降低显卡档位或提高预算。"]


def test_recommend_preserves_local_catalog_prices_and_does_not_call_external_search(monkeypatch, tmp_path):
    local_outcome = ValidationOutcome(
        status="success",
        final_build=[
            BuildLine(category="处理器", sku_id="cpu-local", name="本地 CPU", price=1599, source="local_catalog"),
            BuildLine(category="显卡", sku_id="gpu-local", name="本地显卡", price=3499, source="local_catalog"),
        ],
        total_price=5098,
        budget_check={"status": "within_budget", "target_max": 7000},
        compatibility_check={"status": "pass", "warnings": []},
        risk_check={"status": "pass", "warnings": []},
        unmet_constraints=[],
        alternative_suggestions=[],
        debug={"final_status": "success"},
    )

    def fail_external_search(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("external search should not run when local catalog outcome succeeds")

    monkeypatch.delenv("PC_GUIDE_DEBUG", raising=False)
    monkeypatch.setattr(orchestrator, "_project_root", lambda: tmp_path)
    monkeypatch.setattr(orchestrator, "get_session_store", lambda: _FakeStore())
    monkeypatch.setattr(orchestrator, "get_product_repository", lambda: _FakeRepo())
    monkeypatch.setattr(orchestrator, "get_client", lambda: SimpleNamespace(api_key=""))
    monkeypatch.setattr(orchestrator, "safe_parse", lambda transcript, client=None, trace_sink=None: _parsed())
    monkeypatch.setattr(orchestrator, "retrieve_candidates", lambda parsed, pool: _selection_result())
    monkeypatch.setattr(orchestrator, "validate_and_select", lambda parsed, sorted_by_category: local_outcome)
    monkeypatch.setattr(ExternalSearchBuildAgent, "search", fail_external_search)

    resp = orchestrator.recommend(RecommendRequest(user_query="预算7000，玩3A，外观无所谓"))

    assert resp.code == 0
    assert resp.message == "success"
    assert resp.data.recommendation_source == "local_catalog"
    assert resp.data.total_price == 5098
    assert [(item.sku_id, item.price, item.source) for item in resp.data.final_build] == [
        ("cpu-local", 1599, "local_catalog"),
        ("gpu-local", 3499, "local_catalog"),
    ]


def test_external_search_trigger_ignores_missing_optional_fan_when_build_exists():
    selection = _selection_result()
    selection.debug["by_category"]["风扇"] = {
        "raw_count": 0,
        "after_specified_parts_count": 0,
        "after_must_satisfy_count": 0,
        "after_avoid_count": 0,
        "final_candidate_count": 0,
        "filter_warnings": [],
        "top5": [],
    }

    assert should_use_external_search(selection, _validation_outcome()) is False


def test_external_search_trigger_requires_missing_required_category_even_without_build():
    selection = _selection_result()
    selection.debug["by_category"]["显卡"] = {
        "raw_count": 0,
        "after_specified_parts_count": 0,
        "after_must_satisfy_count": 0,
        "after_avoid_count": 0,
        "final_candidate_count": 0,
        "filter_warnings": [],
        "top5": [],
    }

    assert should_use_external_search(selection, _empty_validation_outcome()) is True


@pytest.mark.parametrize(
    ("parsed", "transcript", "expected_missing", "expected_cards"),
    [
        (
            _parsed_for_clarification(
                usage=["3A游戏"],
                appearance={"color": "white"},
                profile_appearance={"color": "white"},
            ),
            "用户：主要玩3A，白色海景房",
            ["预算范围"],
            ["budget_range"],
        ),
        (
            _parsed_for_clarification(
                budget=BudgetModel(max=9000),
                appearance={"color": "black"},
                profile_price={"budget_extraction": {"max_budget": 9000}},
                profile_appearance={"color": "black"},
            ),
            "用户：预算9000，黑色无光",
            ["主要用途"],
            ["primary_usage"],
        ),
        (
            _parsed_for_clarification(
                budget=BudgetModel(max=9000),
                usage=["3A游戏"],
                profile_price={"budget_extraction": {"max_budget": 9000}},
            ),
            "用户：预算9000，主要玩3A",
            ["外观偏好"],
            ["appearance_preference"],
        ),
        (
            _parsed_for_clarification(),
            "用户：帮我配台电脑",
            ["预算范围", "主要用途", "外观偏好"],
            ["budget_range", "primary_usage", "appearance_preference"],
        ),
        (
            _parsed_for_clarification(
                budget=BudgetModel(max=9000),
                usage=["3A游戏"],
                profile_price={"budget_extraction": {"max_budget": 9000}},
            ),
            "用户：预算9000，主要玩3A，外观无所谓",
            [],
            [],
        ),
        (
            _parsed_for_clarification(
                budget=BudgetModel(max=9000),
                usage=["3A游戏"],
                profile_price={"budget_extraction": {"max_budget": 9000}},
            ),
            "用户：预算9000，主要玩3A，小主机，黑色无光",
            [],
            [],
        ),
    ],
)
def test_dynamic_clarification_matrix(parsed, transcript, expected_missing, expected_cards):  # noqa: ANN001
    decision = DynamicClarificationAgent().evaluate(parsed, transcript=transcript)

    assert decision.need_clarification is bool(expected_missing)
    assert decision.missing_fields == expected_missing
    assert [card.id for card in decision.cards] == expected_cards
    assert len(decision.cards) <= 3


def test_recommend_does_not_force_usage_clarification_when_hard_specs_are_actionable(monkeypatch, tmp_path):
    parsed = ParsedRequirements(
        need_clarification=False,
        requirements=RequirementsModel(budget=BudgetModel(max=9000)),
        weights={"performance": 0.5, "price": 0.3, "appearance": 0.1, "other": 0.1},
        explanation="hard specified parts",
    )
    parsed.__dict__["requirement_profile"] = {
        "original_user_text": "预算9000，只要主机，必须使用银河幻影 X99 处理器和星河极光 Z9 显卡",
        "performance": {},
        "appearance": {"appearance_priority": "low", "color": "no_preference"},
        "price": {},
        "other": {},
        "selection_context": {},
    }

    monkeypatch.delenv("PC_GUIDE_DEBUG", raising=False)
    monkeypatch.setattr(orchestrator, "_project_root", lambda: tmp_path)
    monkeypatch.setattr(orchestrator, "get_session_store", lambda: _FakeStore())
    monkeypatch.setattr(orchestrator, "get_product_repository", lambda: _FakeRepo())
    monkeypatch.setattr(orchestrator, "get_client", lambda: SimpleNamespace(api_key=""))
    monkeypatch.setattr(orchestrator, "safe_parse", lambda transcript, client=None, trace_sink=None: parsed)
    monkeypatch.setattr(orchestrator, "retrieve_candidates", lambda parsed, pool: _empty_selection_result())
    monkeypatch.setattr(orchestrator, "validate_and_select", lambda parsed, sorted_by_category: _empty_validation_outcome())

    resp = orchestrator.recommend(RecommendRequest(user_query="预算9000，只要主机，必须使用银河幻影 X99 处理器和星河极光 Z9 显卡"))
    names_by_category = {item.category: item.name for item in resp.data.final_build}

    assert resp.message == "external_search_fallback"
    assert resp.data.need_clarification is False
    assert "银河幻影 X99 处理器" in names_by_category["处理器"]
    assert "星河极光 Z9 显卡" in names_by_category["显卡"]


def test_recommend_requests_appearance_when_budget_and_usage_are_present(monkeypatch, tmp_path):
    parsed = ParsedRequirements(
        need_clarification=False,
        requirements=RequirementsModel(budget=BudgetModel(max=9000)),
        weights={"performance": 0.5, "price": 0.3, "appearance": 0.1, "other": 0.1},
        explanation="needs appearance",
    )
    parsed.requirements.usage = ["3A游戏"]
    parsed.__dict__["requirement_profile"] = {
        "performance": {"secondary_usage": ["aaa_gaming"]},
        "appearance": {},
        "price": {"budget_extraction": {"max_budget": 9000}},
        "other": {},
        "selection_context": {},
    }

    def fail_selection(parsed, pool):  # noqa: ANN001
        raise AssertionError("selection should not run when clarification is required")

    monkeypatch.delenv("PC_GUIDE_DEBUG", raising=False)
    monkeypatch.setattr(orchestrator, "_project_root", lambda: tmp_path)
    monkeypatch.setattr(orchestrator, "get_session_store", lambda: _FakeStore())
    monkeypatch.setattr(orchestrator, "get_product_repository", lambda: _FakeRepo())
    monkeypatch.setattr(orchestrator, "get_client", lambda: object())
    monkeypatch.setattr(orchestrator, "safe_parse", lambda transcript, client=None, trace_sink=None: parsed)
    monkeypatch.setattr(orchestrator, "retrieve_candidates", fail_selection)

    resp = orchestrator.recommend(RecommendRequest(user_query="预算9000，主要玩3A"))

    assert resp.code == 0
    assert resp.message == "need_clarification"
    assert resp.data.missing_fields == ["外观偏好"]
    assert [card.id for card in resp.data.clarification_cards] == ["appearance_preference"]


def test_external_search_fallback_preserves_hard_specified_parts():
    parsed = ParsedRequirements(
        need_clarification=False,
        requirements=RequirementsModel(budget=BudgetModel(max=9000)),
        weights={"performance": 0.5, "price": 0.3, "appearance": 0.1, "other": 0.1},
        explanation="specified parts",
    )
    parsed.requirements.usage = ["3A游戏"]
    parsed.requirements.specified_parts = [
        SpecifiedPartModel(category="处理器", user_text="苹果 M3 Max 处理器"),
        SpecifiedPartModel(category="显卡", user_text="RTX 4090 粉色显卡"),
    ]

    outcome = ExternalSearchBuildAgent(client=None).search(parsed)
    names_by_category = {item.category: item.name for item in outcome.final_build}

    assert outcome.status == "external_search_fallback"
    assert outcome.total_price >= 9000 * 0.35
    assert all(item.source == "external_search" for item in outcome.final_build)
    assert "苹果 M3 Max 处理器" in names_by_category["处理器"]
    assert "RTX 4090 粉色显卡" in names_by_category["显卡"]


def test_external_search_fallback_cleans_cross_category_spec_leaks():
    class LeakySearchClient:
        api_key = "test"

        def chat_json(self, *args, **kwargs):  # noqa: ANN002, ANN003
            return {
                "items": [
                    {"category": "处理器", "keyword": "Intel i7 处理器", "estimated_price": 1},
                    {"category": "显卡", "keyword": "RTX 4090 粉色 显卡", "estimated_price": 1},
                    {"category": "主板", "keyword": "苹果 M3 Max 主板", "estimated_price": 1},
                ]
            }

    parsed = ParsedRequirements(
        need_clarification=False,
        requirements=RequirementsModel(budget=BudgetModel(max=9000)),
        weights={"performance": 0.5, "price": 0.3, "appearance": 0.1, "other": 0.1},
        explanation="specified parts",
    )
    parsed.requirements.usage = ["3A游戏"]
    parsed.requirements.specified_parts = [
        SpecifiedPartModel(category="处理器", user_text="苹果 M3 Max 处理器"),
        SpecifiedPartModel(category="显卡", user_text="RTX 4090 粉色显卡"),
    ]

    outcome = ExternalSearchBuildAgent(client=LeakySearchClient()).search(parsed)
    names_by_category = {item.category: item.name for item in outcome.final_build}

    assert "苹果 M3 Max 处理器" in names_by_category["处理器"]
    assert "RTX 4090 粉色显卡" in names_by_category["显卡"]
    assert "苹果 M3 Max" not in names_by_category["主板"]


def test_external_search_fallback_recovers_specs_from_original_text():
    class GenericSearchClient:
        api_key = "test"

        def chat_json(self, *args, **kwargs):  # noqa: ANN002, ANN003
            return {
                "items": [
                    {"category": "处理器", "keyword": "英特尔 i7-13700KF 盒装", "estimated_price": 2499},
                    {"category": "显卡", "keyword": "RTX 4090 粉色", "estimated_price": 15999},
                    {"category": "主板", "keyword": "Z790 DDR5 主板", "estimated_price": 1499},
                ]
            }

    parsed = ParsedRequirements(
        need_clarification=False,
        requirements=RequirementsModel(budget=BudgetModel(max=9000)),
        weights={"performance": 0.5, "price": 0.3, "appearance": 0.1, "other": 0.1},
        explanation="specified parts",
    )
    parsed.requirements.usage = ["3A游戏"]
    parsed.__dict__["requirement_profile"] = {
        "original_user_text": "按默认，预算9000，只要主机，必须使用苹果 M3 Max 处理器和 RTX 4090 粉色显卡",
        "performance": {"secondary_usage": ["aaa_gaming"]},
        "appearance": {},
        "price": {},
        "other": {},
        "selection_context": {},
    }

    outcome = ExternalSearchBuildAgent(client=GenericSearchClient()).search(parsed)
    names_by_category = {item.category: item.name for item in outcome.final_build}

    assert "苹果 M3 Max 处理器" in names_by_category["处理器"]
    assert "RTX 4090 粉色显卡" in names_by_category["显卡"]


def test_external_search_fallback_recovers_unknown_model_names_from_text():
    parsed = ParsedRequirements(
        need_clarification=False,
        requirements=RequirementsModel(budget=BudgetModel(max=9000)),
        weights={"performance": 0.5, "price": 0.3, "appearance": 0.1, "other": 0.1},
        explanation="specified parts",
    )
    parsed.requirements.usage = ["3A游戏"]
    parsed.__dict__["requirement_profile"] = {
        "original_user_text": "预算9000，只要主机，必须使用银河幻影 X99 处理器和星河极光 Z9 显卡",
        "performance": {"secondary_usage": ["aaa_gaming"]},
        "appearance": {},
        "price": {},
        "other": {},
        "selection_context": {},
    }

    outcome = ExternalSearchBuildAgent(client=None).search(parsed)
    names_by_category = {item.category: item.name for item in outcome.final_build}

    assert "银河幻影 X99 处理器" in names_by_category["处理器"]
    assert "星河极光 Z9 显卡" in names_by_category["显卡"]


def test_parts_selection_agent_exposes_selection_debug():
    products = [
        _product("显卡", "gpu-rtx", "RTX 4070 Super", 4499, {"vram_gb": 12}),
        _product("显卡", "gpu-rx", "RX 7800 XT", 3599, {"vram_gb": 16}),
    ]
    profile = {
        "selection_context": {
            "must_satisfy": [],
            "prefer_satisfy": [],
            "avoid": [],
        },
        "specified_parts": [{"component": "gpu", "keyword": "RTX"}],
    }

    result = PartsSelectionAgent().select({"requirement_profile": profile}, products)

    assert isinstance(result.debug, dict)
    assert "by_category" in result.debug
    assert "显卡" in result.debug["by_category"]


def test_validate_and_select_exposes_validation_debug():
    parsed = ParsedRequirements(
        need_clarification=False,
        requirements=RequirementsModel(budget=BudgetModel(min=0, max=12000)),
        weights={"performance": 0.5, "price": 0.3, "appearance": 0.1, "other": 0.1},
        explanation="validation debug",
    )
    outcome = validate_and_select(
        parsed,
        {
            "处理器": [_product("处理器", "cpu-1", "AM5 CPU", 1500, {"socket": "AM5", "tdp_w": 65})],
            "主板": [_product("主板", "mb-1", "AM5 主板", 1000, {"socket": "AM5", "memory_type": "DDR5", "form_factor": "ATX"})],
            "内存": [_product("内存", "ram-1", "DDR5 32G", 400, {"memory_type": "DDR5"})],
            "显卡": [_product("显卡", "gpu-1", "短显卡", 3000, {"gpu_length_mm": 250, "tbp_w": 200, "recommended_psu_w": 650})],
            "电源": [_product("电源", "psu-1", "650W 电源", 400, {"wattage_w": 650, "form_factor": "ATX"})],
            "散热": [_product("散热", "cool-1", "风冷散热", 150, {"supported_sockets": ["AM5"], "cooler_height_mm": 150, "cooling_capacity_w": 180})],
            "机箱": [_product("机箱", "case-1", "ATX 机箱", 250, {"supported_motherboard_form_factors": ["ATX"], "max_gpu_length_mm": 320, "max_cpu_cooler_height_mm": 160, "psu_form_factor_supported": ["ATX"]})],
        },
        rules={"cpu_motherboard_rules": [], "memory_rules": [], "power_rules": []},
    )

    assert isinstance(outcome.debug, dict)
    assert "initial_parts" in outcome.debug
    assert "diagnose_steps" in outcome.debug
    assert "final_status" in outcome.debug
