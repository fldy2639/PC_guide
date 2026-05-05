from __future__ import annotations

from pc_build_agent.agents import requirement_agent
from pc_build_agent.models.schemas import DisplayModel, ParsedRequirements, RequirementsModel


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
