from __future__ import annotations

import json

from pc_build_agent.agents import requirement_agent
from pc_build_agent.agents.appearance_requirement_agent import AppearanceRequirementAgent
from pc_build_agent.agents.other_requirement_agent import OtherRequirementAgent
from pc_build_agent.agents.performance_requirement_agent import PerformanceRequirementAgent
from pc_build_agent.agents.price_requirement_agent import PriceRequirementAgent
from pc_build_agent.models.schemas import DisplayModel, ParsedRequirements, RequirementsModel
from pc_build_agent.services.requirement_knowledge_repository import RequirementKnowledgeRepository


def _stub_parsed_requirements() -> ParsedRequirements:
    return ParsedRequirements(
        need_clarification=False,
        requirements=RequirementsModel(display=DisplayModel()),
        weights={"performance": 0.4, "price": 0.3, "appearance": 0.2, "other": 0.1},
        explanation="stub",
    )


def test_repository_prefers_v1_stable_sources():
    repo = RequirementKnowledgeRepository()

    performance_rules = repo.get_rules("performance")
    appearance_rules = repo.get_rules("appearance")
    other_rules = repo.get_rules("other")
    price_rules = repo.get_rules("price")
    performance_source = repo.get_source("performance")
    appearance_source = repo.get_source("appearance")
    other_source = repo.get_source("other")
    price_source = repo.get_source("price")

    assert isinstance(performance_rules, list)
    assert performance_rules
    assert isinstance(appearance_rules, list)
    assert appearance_rules
    assert isinstance(other_rules, list)
    assert other_rules
    assert isinstance(price_rules, dict)
    assert "performance_profiles" in price_rules
    assert "database/requirement_knowledge/v1/scenario_capability_rules.json" in performance_source
    assert "database/requirement_knowledge/v1/appearance_requirement_rules.json" in appearance_source
    assert "database/requirement_knowledge/v1/other_requirement_rules.json" in other_source
    assert "database/requirement_knowledge/v1/budget_strategy_rules.json" in price_source


def test_repository_loads_runtime_enabled_reference_profiles_and_conflicts():
    repo = RequirementKnowledgeRepository()

    capability_profiles = repo.get_capability_weight_profiles()
    conflict_rules = repo.get_conflict_rules()

    assert isinstance(capability_profiles, list)
    assert capability_profiles
    assert isinstance(conflict_rules, list)
    assert conflict_rules

    capability_path = repo.stable_root / "capability_weight_rules.json"
    conflict_path = repo.stable_root / "conflict_rules.json"
    capability_data = json.loads(capability_path.read_text(encoding="utf-8"))
    conflict_data = json.loads(conflict_path.read_text(encoding="utf-8"))

    assert capability_data["status"] == "runtime_enabled"
    assert capability_data["runtime_scope"] == "first_layer_only"
    assert conflict_data["status"] == "runtime_enabled"
    assert conflict_data["runtime_scope"] == "first_layer_only"


def test_agents_can_still_analyze_with_repository_defaults():
    performance_agent = PerformanceRequirementAgent()
    appearance_agent = AppearanceRequirementAgent()
    other_agent = OtherRequirementAgent()
    price_agent = PriceRequirementAgent()

    performance = performance_agent.analyze("主要玩CS2")
    appearance = appearance_agent.analyze("白色海景房")
    other = other_agent.analyze("宿舍用，要WiFi，不要二手")
    price = price_agent.analyze(
        "6000以内，办公学习",
        performance_result={"performance": {"secondary_usage": ["general_office"]}},
        appearance_result={"appearance": {}},
        other_result={"other": {}},
    )

    assert "performance" in performance
    assert "appearance" in appearance
    assert "other" in other
    assert price["price"]["budget_extraction"]["max_budget"] == 6000


def test_safe_parse_remains_stable_with_v1_repository(monkeypatch):
    monkeypatch.setattr(requirement_agent, "parse_requirements", lambda transcript, client=None, trace_sink=None: _stub_parsed_requirements())

    parsed = requirement_agent.safe_parse("用户：6000以内，主要写代码，白色海景房，宿舍用，安静一点，只要主机")

    assert parsed.requirements.budget is not None
    assert parsed.requirements.budget.max == 6000
    assert "programming_development" in parsed.requirements.performance.get("secondary_usage", [])
    assert parsed.requirements.appearance.get("case_style") == "panoramic"
    assert parsed.requirements.appearance.get("color") == "white"
    assert parsed.requirements.other.need_monitor is False


def test_safe_parse_acceptance_inputs_run_without_error(monkeypatch):
    monkeypatch.setattr(requirement_agent, "parse_requirements", lambda transcript, client=None, trace_sink=None: _stub_parsed_requirements())

    inputs = [
        "用户：我想配一台电脑，主要玩黑神话，预算6000，只要主机",
        "用户：我想配白色海景房，预算7000，偶尔直播",
        "用户：我要AI训练和本地大模型，预算12000，不要RGB",
        "用户：办公学习用，越便宜越好，不含显示器",
    ]

    for text in inputs:
        parsed = requirement_agent.safe_parse(text)
        assert parsed is not None
        assert parsed.requirements is not None
        assert isinstance(parsed.requirements.performance, dict)
        assert isinstance(parsed.requirements.appearance, dict)
        assert isinstance(parsed.requirements.price, dict)
