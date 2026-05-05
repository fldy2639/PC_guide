from __future__ import annotations

from pathlib import Path

from pc_build_agent.agents.other_requirement_agent import OtherRequirementAgent


RULE_PATH = Path("pc_build_agent/rules/other_rules.json")


def make_agent(llm=None) -> OtherRequirementAgent:
    return OtherRequirementAgent(rule_path=RULE_PATH, llm=llm)


def test_host_only_wifi_new_parts_dormitory():
    """
    输入：宿舍用，要WiFi，不要二手，预算只算主机。
    期望：
    - only_host=true
    - need_wifi=true
    - accept_used_parts=false
    - scene=dormitory
    - must_have_features 包含 wifi_required 和 new_parts_only
    """
    agent = make_agent()
    result = agent.analyze("宿舍用，要WiFi，不要二手，预算只算主机。")
    other = result["other"]

    assert other["purchase_scope"]["only_host"] is True
    assert other["connectivity"]["need_wifi"] is True
    assert other["purchase_risk"]["accept_used_parts"] is False
    assert other["usage_environment"]["scene"] == "dormitory"

    must_have = other["constraints_for_selection_agent"]["must_have_features"]
    assert "wifi_required" in must_have
    assert "new_parts_only" in must_have


def test_include_monitor_and_peripherals():
    """
    输入：7000预算，一整套，包含显示器和键鼠，买回来能用。
    期望：
    - include_monitor=true
    - include_peripherals=true
    - need_assembly_service=true
    - budget_scope_modifiers 包含 include_monitor 和 include_peripherals
    """
    agent = make_agent()
    result = agent.analyze("7000预算，一整套，包含显示器和键鼠，买回来能用。")
    other = result["other"]

    assert other["purchase_scope"]["include_monitor"] is True
    assert other["purchase_scope"]["include_peripherals"] is True
    assert other["warranty_service"]["need_assembly_service"] is True

    modifiers = other["constraints_for_selection_agent"]["budget_scope_modifiers"]
    assert "include_monitor" in modifiers
    assert "include_peripherals" in modifiers


def test_future_gpu_upgrade():
    """
    输入：现在预算有限，以后想升级显卡，电源和机箱别太小。
    期望：
    - upgrade_space_required=true
    - future_gpu_upgrade=true
    - must_have_features 包含 psu_upgrade_headroom 和 gpu_clearance_headroom
    """
    agent = make_agent()
    result = agent.analyze("现在预算有限，以后想升级显卡，电源和机箱别太小。")
    other = result["other"]

    assert other["upgrade_plan"]["upgrade_space_required"] is True
    assert other["upgrade_plan"]["future_gpu_upgrade"] is True

    must_have = other["constraints_for_selection_agent"]["must_have_features"]
    assert "psu_upgrade_headroom" in must_have
    assert "gpu_clearance_headroom" in must_have


def test_front_type_c_requirement():
    """
    输入：需要前置Type-C，USB口多一点。
    期望：
    - front_type_c_required=true
    - usb_ports_priority=high
    - compatibility_checks 包含 case_front_type_c_header 和 motherboard_front_type_c_header
    """
    agent = make_agent()
    result = agent.analyze("需要前置Type-C，USB口多一点。")
    other = result["other"]

    assert other["special_requirements"]["front_type_c_required"] is True
    assert other["special_requirements"]["usb_ports_priority"] == "high"

    checks = other["constraints_for_selection_agent"]["compatibility_checks"]
    assert "case_front_type_c_header" in checks
    assert "motherboard_front_type_c_header" in checks


def test_multi_monitor_and_large_storage():
    """
    输入：要接两个显示器，还需要2TB硬盘。
    期望：
    - multi_monitor_required=true
    - storage_capacity_requirement=2TB
    - performance_signals 包含 multi_monitor_display_output_required 和 large_storage_required
    """
    agent = make_agent()
    result = agent.analyze("要接两个显示器，还需要2TB硬盘。")
    other = result["other"]

    assert other["special_requirements"]["multi_monitor_required"] is True
    assert other["special_requirements"]["storage_capacity_requirement"] == "2TB"

    perf_signals = other["cross_module_signals"]["performance_signals"]
    signal_names = [item["signal"] for item in perf_signals]
    assert "multi_monitor_display_output_required" in signal_names
    assert "large_storage_required" in signal_names


def test_owned_monitor_and_keyboard_mouse():
    """
    输入：我有显示器和键鼠了，只配主机。
    期望：
    - has_monitor=true
    - has_keyboard_mouse=true
    - only_host=true
    - include_monitor=false
    - include_peripherals=false
    """
    agent = make_agent()
    result = agent.analyze("我有显示器和键鼠了，只配主机。")
    other = result["other"]

    assert other["owned_parts"]["has_monitor"] is True
    assert other["owned_parts"]["has_keyboard_mouse"] is True
    assert other["purchase_scope"]["only_host"] is True
    assert other["purchase_scope"]["include_monitor"] is False
    assert other["purchase_scope"]["include_peripherals"] is False


class FakeLlm:
    def chat_json(self, messages, step):  # noqa: ANN001
        return {
            "connectivity": {
                "need_wifi": False,
                "need_bluetooth": True,
            },
            "usage_environment": {
                "placement": "desktop",
            },
            "missing_information": ["是否需要蓝牙"],
        }


def test_llm_only_fills_unknown_fields():
    result = make_agent(llm=FakeLlm()).analyze("宿舍用，要WiFi")
    other = result["other"]

    assert other["connectivity"]["need_wifi"] is True
    assert other["connectivity"]["need_bluetooth"] is True
    assert other["usage_environment"]["scene"] == "dormitory"
    assert other["usage_environment"]["placement"] == "desktop"
    assert "是否需要蓝牙" in other["missing_information"]


class BrokenLlm:
    api_key = "fake-key"

    def chat_json(self, messages, step):  # noqa: ANN001
        raise OSError("dns failure")


def test_llm_failure_falls_back_to_rules_only():
    result = make_agent(llm=BrokenLlm()).analyze("宿舍用，要WiFi，不要二手，只要主机")
    other = result["other"]

    assert other["purchase_scope"]["only_host"] is True
    assert other["connectivity"]["need_wifi"] is True
    assert other["purchase_risk"]["accept_used_parts"] is False


def test_cross_module_signals_are_structured_and_deduped():
    agent = make_agent()
    merged = agent.merge_rule_and_llm_results(
        rule_matches=[
            {
                "rule_id": "rule_a",
                "dimension": "usage_environment",
                "hit_keywords": ["宿舍"],
                "effects": {
                    "cross_module_signals": {
                        "appearance_signals": [
                            {
                                "signal": "low_noise_preferred",
                                "target": "appearance",
                                "target_effect": "prefer_low_noise",
                                "priority": "medium",
                                "reason": "old",
                            }
                        ]
                    }
                },
                "description": "",
            },
            {
                "rule_id": "rule_b",
                "dimension": "usage_environment",
                "hit_keywords": ["晚上用"],
                "effects": {
                    "cross_module_signals": {
                        "appearance_signals": [
                            {
                                "signal": "low_noise_preferred",
                                "target": "appearance",
                                "target_effect": "prefer_low_noise",
                                "priority": "high",
                                "reason": "new",
                            }
                        ]
                    }
                },
                "description": "",
            },
        ],
        llm_extraction=None,
    )

    signals = merged["cross_module_signals"]["appearance_signals"]
    assert len(signals) == 1
    assert signals[0]["priority"] == "high"
    assert signals[0]["reason"] == "new"
