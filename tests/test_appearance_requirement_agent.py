from __future__ import annotations

from pathlib import Path

from pc_build_agent.agents.appearance_requirement_agent import AppearanceRequirementAgent


RULE_PATH = Path(__file__).resolve().parents[1] / "pc_build_agent" / "rules" / "appearance_rules.json"


def build_agent() -> AppearanceRequirementAgent:
    return AppearanceRequirementAgent(rule_path=RULE_PATH, llm=None)


def test_panoramic_case():
    """
    输入：海景房
    期望：
    - case_style == panoramic
    - material == tempered_glass
    - matched_keywords 包含 海景房
    """
    result = build_agent().analyze("海景房")
    appearance = result["appearance"]

    assert appearance["case_style"] == "panoramic"
    assert appearance["material"] == "tempered_glass"
    assert "海景房" in appearance["matched_keywords"]


def test_white_panoramic_no_rgb():
    """
    输入：白色海景房，不要RGB
    期望：
    - color == white
    - case_style == panoramic
    - rgb == no_rgb
    - conflicts_or_warnings 不为空
    """
    result = build_agent().analyze("白色海景房，不要RGB")
    appearance = result["appearance"]

    assert appearance["color"] == "white"
    assert appearance["case_style"] == "panoramic"
    assert appearance["rgb"] == "no_rgb"
    assert appearance["conflicts_or_warnings"]


def test_dorm_compact_low_noise():
    """
    输入：宿舍用，小一点，安静
    期望：
    - case_size == compact_m_atx
    - preferred_form_factor 包含 M-ATX
    - noise in ["silent", "low_noise"]
    """
    result = build_agent().analyze("宿舍用，小一点，安静")
    appearance = result["appearance"]

    assert appearance["case_size"] == "compact_m_atx"
    assert "M-ATX" in appearance["preferred_form_factor"]
    assert appearance["noise"] in ["silent", "low_noise"]


def test_itx_compact():
    """
    输入：ITX小主机
    期望：
    - case_size == itx_compact
    - preferred_form_factor == ["Mini-ITX"]
    """
    result = build_agent().analyze("ITX小主机")
    appearance = result["appearance"]

    assert appearance["case_size"] == "itx_compact"
    assert appearance["preferred_form_factor"] == ["Mini-ITX"]


def test_black_minimalist_no_rgb():
    """
    输入：黑色低调无光
    期望：
    - color == black
    - case_style == minimalist
    - rgb == no_rgb
    """
    result = build_agent().analyze("黑色低调无光")
    appearance = result["appearance"]

    assert appearance["color"] == "black"
    assert appearance["case_style"] == "minimalist"
    assert appearance["rgb"] == "no_rgb"


def test_no_size_preference():
    """
    输入：颜色无所谓，正常机箱就行
    期望：
    - color == no_preference
    - case_size == standard_atx
    """
    result = build_agent().analyze("颜色无所谓，正常机箱就行")
    appearance = result["appearance"]

    assert appearance["color"] == "no_preference"
    assert appearance["case_size"] == "standard_atx"


def test_gaming_but_no_rgb_conflict():
    """
    输入：电竞风，但是不要RGB
    期望：
    - case_style == gaming
    - rgb == no_rgb
    - conflicts_or_warnings 包含 电竞风和无RGB相关提示
    """
    result = build_agent().analyze("电竞风，但是不要RGB")
    appearance = result["appearance"]

    assert appearance["case_style"] == "gaming"
    assert appearance["rgb"] == "no_rgb"
    assert any("电竞" in item and "RGB" in item for item in appearance["conflicts_or_warnings"])


def test_apply_other_signals_prefers_compact_and_low_noise_when_unknown():
    agent = build_agent()
    base = {
        "case_size": "unknown",
        "preferred_form_factor": [],
        "appearance_priority": "unknown",
        "noise": "unknown",
        "compatibility_constraints": [],
        "conflicts_or_warnings": [],
    }
    other_result = {
        "other": {
            "cross_module_signals": {
                "appearance_signals": [
                    {
                        "signal": "compact_case_preferred",
                        "target": "appearance",
                        "target_effect": "prefer_compact_m_atx",
                        "priority": "medium",
                        "reason": "",
                    },
                    {
                        "signal": "low_noise_preferred",
                        "target": "appearance",
                        "target_effect": "prefer_low_noise",
                        "priority": "medium",
                        "reason": "",
                    },
                    {
                        "signal": "desktop_case_size_preferred",
                        "target": "appearance",
                        "target_effect": "prefer_desktop_friendly_case_size",
                        "priority": "medium",
                        "reason": "",
                    },
                ]
            }
        }
    }

    updated = agent.apply_other_signals(base, other_result)

    assert updated["case_size"] == "compact_m_atx"
    assert updated["preferred_form_factor"] == ["M-ATX", "Mini-ITX"]
    assert updated["noise"] == "low_noise"
    assert updated["appearance_priority"] == "medium"
    assert any("桌面摆放需要考虑机箱体积" in item for item in updated["compatibility_constraints"])


def test_apply_other_signals_does_not_override_explicit_large_case():
    agent = build_agent()
    base = {
        "case_size": "large_atx",
        "preferred_form_factor": ["ATX", "E-ATX", "M-ATX"],
        "appearance_priority": "unknown",
        "noise": "unknown",
        "compatibility_constraints": [],
        "conflicts_or_warnings": [],
    }
    other_result = {
        "other": {
            "cross_module_signals": {
                "appearance_signals": [
                    {
                        "signal": "compact_case_preferred",
                        "target": "appearance",
                        "target_effect": "prefer_compact_m_atx",
                        "priority": "medium",
                        "reason": "",
                    }
                ]
            }
        }
    }

    updated = agent.apply_other_signals(base, other_result)

    assert updated["case_size"] == "large_atx"
    assert any("空间有限" in item and "大机箱倾向" in item for item in updated["conflicts_or_warnings"])
