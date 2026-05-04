from __future__ import annotations

from pathlib import Path

from pc_build_agent.agents.price_requirement_agent import PriceRequirementAgent


RULE_PATH = Path(__file__).resolve().parents[1] / "pc_build_agent" / "rules" / "price_rules.json"


def build_agent() -> PriceRequirementAgent:
    return PriceRequirementAgent(rule_path=RULE_PATH, llm=None)


def test_extract_budget_supports_multiple_price_phrases():
    budget = build_agent().extract_budget("5000到6000，性价比高一点，可以小超")

    assert budget["min_budget"] == 5000
    assert budget["max_budget"] == 6000
    assert budget["target_budget"] == 5500
    assert budget["budget_flexibility"] == "small_overspend"
    assert budget["value_preference"] == "cost_effective"


def test_extract_budget_supports_hard_limit_and_unlimited_phrases():
    hard_budget = build_agent().extract_budget("预算卡死，不超过6000")
    rich_budget = build_agent().extract_budget("不差钱")

    assert hard_budget["hard_limit"] is True
    assert hard_budget["budget_flexibility"] == "none"
    assert hard_budget["max_budget"] == 6000

    assert rich_budget["budget_flexibility"] == "flexible"
    assert rich_budget["price_priority"] == "low"
    assert rich_budget["value_preference"] == "quality_first"


def test_office_low_budget():
    result = build_agent().analyze(
        "6000以内，办公学习，越便宜越好",
        performance_result={"performance": {"secondary_usage": ["general_office"]}},
        appearance_result={"appearance": {}},
        other_result={"other": {}},
    )
    price = result["price"]

    assert price["budget_extraction"]["hard_limit"] is True
    assert set(price["selection_context_for_parts_agent"]["protected_components"]) >= {"cpu", "ram", "ssd"}
    gpu_policy = next(item for item in price["component_budget_policy"] if item["component"] == "gpu")
    assert gpu_policy["budget_priority"] == "low" or gpu_policy["price_control_level"] == "minimal"


def test_programming_white_panoramic_dorm():
    result = build_agent().analyze(
        "6000以内，主要写代码，白色海景房，宿舍用，安静一点",
        performance_result={"performance": {"secondary_usage": ["programming_development"]}},
        appearance_result={
            "appearance": {
                "case_size": "compact_m_atx",
                "case_style": "panoramic",
                "color": "white",
                "noise": "low_noise",
                "appearance_priority": "high",
            }
        },
        other_result={"other": {}},
    )
    price = result["price"]

    drivers = set(price["appearance_price_impact"]["appearance_cost_drivers"])
    assert {"white_build_premium", "panoramic_case_premium", "low_noise_cost"} <= drivers
    assert set(price["selection_context_for_parts_agent"]["protected_components"]) >= {"cpu", "ram", "ssd", "case", "cooling"}
    gpu_policy = next(item for item in price["component_budget_policy"] if item["component"] == "gpu")
    assert gpu_policy["can_cut_cost"] is True
    assert price["selection_context_for_parts_agent"]


def test_aaa_white_panoramic_tight_budget():
    result = build_agent().analyze(
        "6000左右，玩黑神话，白色海景房",
        performance_result={"performance": {"secondary_usage": ["aaa_gaming"]}},
        appearance_result={
            "appearance": {
                "case_style": "panoramic",
                "color": "white",
                "appearance_priority": "high",
            }
        },
        other_result={"other": {}},
    )
    price = result["price"]

    assert "gpu" in price["performance_price_impact"]["protected_by_performance"]
    drivers = set(price["appearance_price_impact"]["appearance_cost_drivers"])
    assert {"white_build_premium", "panoramic_case_premium"} <= drivers
    assert price["budget_pressure"]["level"] in ["medium_high", "high", "over_constrained"]
    assert any("白色机箱" in item or "外观" in item for item in price["tradeoff_strategy"]["fallback_plans"])


def test_ai_local_llm_with_small_case():
    result = build_agent().analyze(
        "预算8000，跑本地大模型，小主机",
        performance_result={"performance": {"secondary_usage": ["local_llm_inference"]}},
        appearance_result={
            "appearance": {
                "case_size": "itx_compact",
                "appearance_priority": "medium",
            }
        },
        other_result={"other": {}},
    )
    price = result["price"]

    assert set(price["selection_context_for_parts_agent"]["protected_components"]) >= {"gpu", "ram", "ssd", "psu"}
    assert "itx_premium" in price["appearance_price_impact"]["appearance_cost_drivers"]
    for component in ["motherboard", "psu", "cooling", "case"]:
        item = next(policy for policy in price["component_budget_policy"] if policy["component"] == component)
        assert item["budget_priority"] in ["medium_high", "high"]


def test_budget_includes_monitor_and_peripherals():
    result = build_agent().analyze(
        "7000预算，包含显示器和键鼠，主要玩游戏",
        performance_result={"performance": {"secondary_usage": ["fps_esports"]}},
        appearance_result={"appearance": {}},
        other_result={"other": {"include_monitor": True, "include_peripherals": True}},
    )
    price = result["price"]

    assert set(price["budget_scope"]["external_budget_items"]) >= {"monitor", "peripherals"}
    assert price["budget_scope"]["effective_host_budget"] is None
    assert (
        price["budget_pressure"]["level"] in ["medium", "medium_high", "high", "over_constrained"]
        or "external_scope_cost" in price["budget_pressure"]["risk_flags"]
    )


def test_budget_pressure_consumes_other_price_signals():
    result = build_agent().analyze(
        "7000预算，主要玩游戏",
        performance_result={"performance": {"secondary_usage": ["fps_esports"]}},
        appearance_result={"appearance": {}},
        other_result={
            "other": {
                "cross_module_signals": {
                    "price_signals": [
                        {
                            "signal": "wifi_bluetooth_cost_driver",
                            "target": "price",
                            "target_effect": "increase_motherboard_or_adapter_budget",
                            "priority": "medium",
                            "reason": "",
                        },
                        {
                            "signal": "storage_capacity_cost_driver",
                            "target": "price",
                            "target_effect": "increase_ssd_budget_priority",
                            "priority": "medium",
                            "reason": "",
                        },
                        {
                            "signal": "front_type_c_cost_driver",
                            "target": "price",
                            "target_effect": "increase_case_and_motherboard_feature_budget",
                            "priority": "medium",
                            "reason": "",
                        },
                    ]
                }
            }
        },
    )
    risk_flags = set(result["price"]["budget_pressure"]["risk_flags"])

    assert "wifi_bluetooth_cost" in risk_flags
    assert "storage_capacity_cost" in risk_flags
    assert "front_type_c_cost" in risk_flags
