from __future__ import annotations

import unittest

from pc_build_agent.agents.performance_requirement_agent import PerformanceRequirementAgent


class PerformanceRequirementAgentTest(unittest.TestCase):
    def setUp(self) -> None:
        self.agent = PerformanceRequirementAgent()

    def test_match_fps_esports(self) -> None:
        result = self.agent.analyze("主要玩CS2")
        performance = result["performance"]
        self.assertIn("fps_esports", performance["secondary_usage"])

    def test_match_aaa_gaming(self) -> None:
        result = self.agent.analyze("想玩黑神话和赛博朋克")
        performance = result["performance"]
        self.assertIn("aaa_gaming", performance["secondary_usage"])

    def test_match_streaming_as_weak_demand(self) -> None:
        matches = self.agent.match_rules("主要玩CS2，偶尔直播")
        tags = {item["rule"].normalized_tag: item["strength_weight"] for item in matches}
        self.assertEqual(tags.get("fps_esports"), 1.0)
        self.assertEqual(tags.get("game_streaming"), 0.3)

    def test_match_programming_and_local_llm(self) -> None:
        result = self.agent.analyze("写Python，也跑本地大模型")
        performance = result["performance"]
        self.assertIn("programming_development", performance["secondary_usage"])
        self.assertIn("local_llm_inference", performance["secondary_usage"])

    def test_match_study_or_office(self) -> None:
        result = self.agent.analyze("办公学习用，看看网课，写论文")
        performance = result["performance"]
        secondary_usage = set(performance["secondary_usage"])
        self.assertTrue({"general_study", "general_office"} & secondary_usage)

    def test_apply_other_signals_adds_multi_monitor_and_storage_constraints(self) -> None:
        base = self.agent.analyze("写Python")["performance"]
        other_result = {
            "other": {
                "cross_module_signals": {
                    "performance_signals": [
                        {
                            "signal": "multi_monitor_display_output_required",
                            "target": "performance",
                            "target_effect": "increase_display_output_requirement",
                            "priority": "medium",
                            "reason": "",
                        },
                        {
                            "signal": "large_storage_required",
                            "target": "performance",
                            "target_effect": "increase_ssd_capacity_priority",
                            "priority": "medium",
                            "reason": "",
                        },
                    ]
                }
            }
        }

        updated = self.agent.apply_other_signals(base, other_result)

        self.assertIn("多显示器输出", updated["performance_focus"])
        self.assertIn("高分辨率显示稳定性", updated["performance_focus"])
        self.assertEqual(updated["hardware_constraints"]["display_output"], "需要检查核显、主板或显卡显示输出能力")
        self.assertEqual(updated["hardware_constraints"]["storage_capacity"], "2TB_or_more")
        self.assertIn("multi_monitor_display_output_required", updated["extra_performance_constraints"])

    def test_apply_other_signals_adds_wireless_network_only_for_gaming_or_streaming(self) -> None:
        gaming = self.agent.analyze("主要玩CS2")["performance"]
        office = self.agent.analyze("办公学习用")["performance"]
        other_result = {
            "other": {
                "cross_module_signals": {
                    "performance_signals": [
                        {
                            "signal": "wireless_network_stability_required",
                            "target": "performance",
                            "target_effect": "increase_network_priority_if_gaming_or_streaming",
                            "priority": "medium",
                            "reason": "",
                        }
                    ]
                }
            }
        }

        updated_gaming = self.agent.apply_other_signals(gaming, other_result)
        updated_office = self.agent.apply_other_signals(office, other_result)

        self.assertIn("无线网络稳定性", updated_gaming["performance_focus"])
        self.assertIn("低延迟连接", updated_gaming["performance_focus"])
        self.assertEqual(updated_gaming["hardware_constraints"]["network"], "需要稳定WiFi或有线网络条件")
        self.assertNotIn("无线网络稳定性", updated_office["performance_focus"])


if __name__ == "__main__":
    unittest.main()
