from __future__ import annotations

from pc_build_agent.agents import requirement_agent
from pc_build_agent.agents.selection import retrieve_candidates
from pc_build_agent.models.schemas import DisplayModel, ParsedRequirements, RequirementsModel
from pc_build_agent.services.product_repository import get_product_repository


def _stub_parsed_requirements() -> ParsedRequirements:
    return ParsedRequirements(
        need_clarification=False,
        requirements=RequirementsModel(display=DisplayModel()),
        weights={"performance": 0.4, "price": 0.3, "appearance": 0.2, "other": 0.1},
        explanation="stub",
    )


class _BrokenLlm:
    api_key = "fake-key"

    def chat_json(self, messages, step):  # noqa: ANN001
        raise OSError("dns failure")

    def chat_text(self, messages, temperature=0.2, step="chat_text"):  # noqa: ANN001
        raise OSError("dns failure")


def test_safe_parse_aggregates_price_and_backfills_compatibility(monkeypatch):
    monkeypatch.setattr(requirement_agent, "parse_requirements", lambda transcript, client=None, trace_sink=None: _stub_parsed_requirements())

    parsed = requirement_agent.safe_parse(
        "用户：6000以内，主要写代码，白色海景房，宿舍用，安静一点，只要主机"
    )

    assert "budget_extraction" in parsed.requirements.price
    assert "selection_context_for_parts_agent" in parsed.requirements.price
    assert parsed.requirements.budget is not None
    assert parsed.requirements.budget.max == 6000
    assert parsed.requirements.other.need_monitor is False
    assert parsed.requirements.display is not None
    assert parsed.requirements.display.need_monitor is False

    assert parsed.requirements.performance.get("secondary_usage")
    assert "programming_development" in parsed.requirements.performance["secondary_usage"]
    assert "编程开发" in parsed.requirements.usage

    assert parsed.requirements.appearance.get("case_style") == "panoramic"
    assert parsed.requirements.appearance.get("color") == "white"
    assert parsed.requirements.appearance.get("noise") in ["silent", "low_noise"]


def test_safe_parse_keeps_cross_module_backfill_stable(monkeypatch):
    monkeypatch.setattr(requirement_agent, "parse_requirements", lambda transcript, client=None, trace_sink=None: _stub_parsed_requirements())

    parsed = requirement_agent.safe_parse(
        "用户：预算8000，跑本地大模型，小主机，不含显示器"
    )

    price = parsed.requirements.price
    assert price["budget_extraction"]["max_budget"] == 8000
    assert price["performance_price_impact"]["protected_by_performance"]
    assert "gpu" in price["performance_price_impact"]["protected_by_performance"]
    assert "itx_premium" in price["appearance_price_impact"]["appearance_cost_drivers"]

    selection_context = price["selection_context_for_parts_agent"]
    assert set(selection_context["protected_components"]) >= {"gpu", "ram", "ssd", "psu"}
    assert "case_size:itx_compact" in selection_context["must_satisfy"]
    assert "oversized_case" in selection_context["avoid"]

    assert parsed.requirements.budget is not None
    assert parsed.requirements.budget.max == 8000
    assert parsed.requirements.other.need_monitor is False
    assert parsed.requirements.display is not None
    assert parsed.requirements.display.need_monitor is False
    assert "本地模型" in parsed.requirements.usage
    assert parsed.capability_profile
    assert "component_weights" in parsed.capability_profile
    assert parsed.capability_profile["component_weights"].get("gpu", 0) >= 4


def test_safe_parse_integrates_other_agent_into_price_and_compatibility(monkeypatch):
    monkeypatch.setattr(requirement_agent, "parse_requirements", lambda transcript, client=None, trace_sink=None: _stub_parsed_requirements())

    parsed = requirement_agent.safe_parse(
        "用户：7000预算，只要主机，宿舍用，要WiFi，不要二手，要质保，以后升级显卡"
    )

    assert parsed.requirements.other.need_monitor is False
    assert parsed.requirements.other.need_wifi is True
    assert parsed.requirements.other.accept_second_hand is False
    assert parsed.requirements.other.need_full_system_warranty is True
    assert parsed.requirements.other.upgradeability_requirement == "high"

    price = parsed.requirements.price
    assert price["budget_scope"]["only_host"] is True
    assert "wifi_bluetooth_required" in price["other_price_impact"]["functional_cost_drivers"]
    assert "new_parts_or_warranty_preferred" in price["other_price_impact"]["quality_cost_drivers"]
    assert "warranty_required" in price["other_price_impact"]["quality_cost_drivers"]
    assert "upgrade_space_required" in price["other_price_impact"]["upgrade_cost_drivers"]


def test_requirement_profile_translates_semantic_constraints_for_selection(monkeypatch):
    monkeypatch.setattr(requirement_agent, "parse_requirements", lambda transcript, client=None, trace_sink=None: _stub_parsed_requirements())

    parsed = requirement_agent.safe_parse(
        "用户：预算5000以内，只办公学习，不要独显，要WiFi，宿舍用不要太大"
    )

    profile = parsed.__dict__.get("requirement_profile", {})
    selection_context = profile["selection_context"]
    assert "budget_upper_limit" not in selection_context["must_satisfy"]
    assert "case_size:compact_m_atx" not in selection_context["must_satisfy"]
    assert {"component": "motherboard", "field": "wifi_builtin", "operator": "==", "value": True} in selection_context["must_satisfy"]

    pool = get_product_repository().load()
    result = retrieve_candidates(parsed, pool)
    assert result.sorted_by_category["处理器"]
    assert result.sorted_by_category["主板"]
    assert result.sorted_by_category["内存"]
    assert result.sorted_by_category["硬盘"]


def test_requirement_profile_translates_storage_and_upgrade_constraints(monkeypatch):
    monkeypatch.setattr(requirement_agent, "parse_requirements", lambda transcript, client=None, trace_sink=None: _stub_parsed_requirements())

    parsed = requirement_agent.safe_parse(
        "用户：预算12000，玩4K 3A，高画质，要32G内存和2TB固态，以后升级显卡"
    )

    profile = parsed.__dict__.get("requirement_profile", {})
    must_satisfy = profile["selection_context"]["must_satisfy"]
    assert {"component": "ssd", "field": "capacity_gb", "operator": ">=", "value": 2000} in must_satisfy
    assert {"component": "psu", "field": "wattage_w", "operator": ">=", "value": 750} in must_satisfy
    assert {"component": "case", "field": "max_gpu_length_mm", "operator": ">=", "value": 340} in must_satisfy

    pool = get_product_repository().load()
    result = retrieve_candidates(parsed, pool)
    assert result.sorted_by_category["显卡"]
    assert result.sorted_by_category["硬盘"]
    assert result.sorted_by_category["电源"]


def test_requirement_profile_compiles_explicit_part_requirements(monkeypatch):
    monkeypatch.setattr(requirement_agent, "parse_requirements", lambda transcript, client=None, trace_sink=None: _stub_parsed_requirements())

    parsed = requirement_agent.safe_parse(
        "用户：我要 RTX 4070 显卡，英特尔 CPU，32G DDR5内存，2TB SSD，白色海景房，750W金牌电源，360水冷"
    )

    must_satisfy = parsed.__dict__["requirement_profile"]["selection_context"]["must_satisfy"]
    prefer_satisfy = parsed.__dict__["requirement_profile"]["selection_context"]["prefer_satisfy"]

    assert {"component": "gpu", "keywords": ["RTX", "4070"]} in must_satisfy
    assert {"component": "cpu", "field": "brand", "operator": "contains", "value": "英特尔"} in must_satisfy
    assert {"component": "memory", "field": "capacity_gb", "operator": ">=", "value": 32} in must_satisfy
    assert {"component": "memory", "field": "memory_type", "operator": "==", "value": "DDR5"} in must_satisfy
    assert {"component": "ssd", "field": "capacity_gb", "operator": ">=", "value": 2000} in must_satisfy
    assert {"component": "case", "field": "color", "operator": "contains", "value": "白"} in must_satisfy
    assert {"component": "case", "field": "case_style", "operator": "contains", "value": "海景房"} in must_satisfy
    assert {"component": "psu", "field": "wattage_w", "operator": ">=", "value": 750} in must_satisfy
    assert {"component": "cooling", "field": "cooling_type", "operator": "contains", "value": "水冷"} in must_satisfy
    assert {"component": "cooling", "field": "radiator_size_mm", "operator": ">=", "value": 360} in must_satisfy
    assert {"component": "psu", "field": "efficiency_rating", "operator": "contains_any", "value": ["Gold", "金牌"]} in prefer_satisfy


def test_requirement_profile_compiles_intel_nvidia_platform(monkeypatch):
    monkeypatch.setattr(requirement_agent, "parse_requirements", lambda transcript, client=None, trace_sink=None: _stub_parsed_requirements())

    parsed = requirement_agent.safe_parse("用户：预算2万，主要做视频剪辑、3D渲染，要Intel+NVIDIA，64G内存")
    selection_context = parsed.__dict__["requirement_profile"]["selection_context"]

    assert {"component": "cpu", "field": "brand", "operator": "contains", "value": "英特尔"} in selection_context["must_satisfy"]
    assert {
        "component": "gpu",
        "field": "name",
        "operator": "contains_any",
        "value": ["NVIDIA", "英伟达", "GeForce", "RTX", "GTX"],
    } in selection_context["must_satisfy"]
    assert {"component": "memory", "field": "capacity_gb", "operator": ">=", "value": 64} in selection_context["must_satisfy"]


def test_safe_parse_emits_conflict_warning_for_low_budget_4k_aaa(monkeypatch):
    monkeypatch.setattr(requirement_agent, "parse_requirements", lambda transcript, client=None, trace_sink=None: _stub_parsed_requirements())

    parsed = requirement_agent.safe_parse("用户：预算5000，想玩4K 3A 高画质")
    profile = parsed.__dict__.get("requirement_profile", {})
    conflict_warnings = (((profile.get("selection_context") or {}).get("cross_module_signals") or {}).get("conflict_warnings") or [])

    assert any(item.get("rule_id") == "low_budget_4k_aaa" for item in conflict_warnings)


def test_safe_parse_emits_conflict_warning_for_budget_vs_white_panoramic(monkeypatch):
    monkeypatch.setattr(requirement_agent, "parse_requirements", lambda transcript, client=None, trace_sink=None: _stub_parsed_requirements())

    parsed = requirement_agent.safe_parse("用户：预算6000，白色海景房，玩黑神话")
    profile = parsed.__dict__.get("requirement_profile", {})
    conflict_warnings = (((profile.get("selection_context") or {}).get("cross_module_signals") or {}).get("conflict_warnings") or [])

    assert any(item.get("rule_id") == "budget_vs_white_panoramic" for item in conflict_warnings)


def test_safe_parse_host_only_vs_include_monitor_conflict_is_stable(monkeypatch):
    monkeypatch.setattr(requirement_agent, "parse_requirements", lambda transcript, client=None, trace_sink=None: _stub_parsed_requirements())

    parsed = requirement_agent.safe_parse("用户：只要主机，也要含显示器")
    profile = parsed.__dict__.get("requirement_profile", {})
    conflict_warnings = (((profile.get("selection_context") or {}).get("cross_module_signals") or {}).get("conflict_warnings") or [])

    assert parsed is not None
    assert any(item.get("rule_id") == "host_only_vs_include_monitor" for item in conflict_warnings)


def test_safe_parse_stays_available_when_llm_network_fails():
    parsed = requirement_agent.safe_parse(
        "用户：预算8000，只要主机，主要写代码，偶尔玩3A，白色机箱，安静一点",
        client=_BrokenLlm(),
    )

    assert parsed.need_clarification is False
    assert parsed.requirements.budget is not None
    assert parsed.requirements.budget.max == 8000
    assert parsed.requirements.other.need_monitor is False
    assert "编程开发" in parsed.requirements.usage
    assert "目标分辨率" in parsed.missing_fields
