from __future__ import annotations

import json
from types import SimpleNamespace

from pc_build_agent.agents.selection import PartsSelectionAgent, SelectionResult
from pc_build_agent.agents.validation_engine import ValidationOutcome, validate_and_select
from pc_build_agent.models.schemas import BuildLine, BudgetModel, ParsedRequirements, ProductRecord, RecommendRequest, RequirementsModel
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
        requirements=RequirementsModel(budget=BudgetModel(min=6000, max=7000)),
        weights={"performance": 0.5, "price": 0.3, "appearance": 0.1, "other": 0.1},
        explanation="debug test",
    )
    parsed.requirements.usage = ["3A游戏"]
    parsed.__dict__["requirement_profile"] = {
        "original_user_text": "用户：测试装机需求",
        "performance": {"secondary_usage": ["aaa_gaming"]},
        "appearance": {},
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
    assert "待补充信息：目标分辨率、是否需要WiFi" in resp.data.recommendation_reason


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
