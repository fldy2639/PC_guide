from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pc_build_agent.schemas.price_schema import ComponentBudgetPolicyItem, PriceAgentOutput, PriceOutput


class PriceRequirementAgent:
    COMPONENTS = ["cpu", "gpu", "motherboard", "ram", "ssd", "cooling", "psu", "case"]
    COMPONENT_CN = {
        "cpu": "处理器",
        "gpu": "显卡",
        "motherboard": "主板",
        "ram": "内存",
        "ssd": "固态硬盘",
        "cooling": "散热",
        "psu": "电源",
        "case": "机箱",
    }
    PERFORMANCE_RELEVANCE_SCORES = {"none": 0, "low": 1, "medium": 2, "high": 3}
    BUDGET_PRIORITY_ORDER = ["low", "medium", "medium_high", "high"]
    PRESSURE_LEVELS = ["low", "medium", "medium_high", "high", "over_constrained"]
    FLEXIBILITY_ORDER = {
        "none": 0,
        "soft": 1,
        "small_overspend": 2,
        "flexible": 3,
        "unknown": -1,
    }
    CHINESE_DIGITS = {
        "零": 0,
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
    }
    PRICE_SIGNAL_RISK_FLAG_MAP = {
        "monitor_budget_required": "external_scope_cost",
        "peripherals_budget_required": "external_scope_cost",
        "os_budget_required": "os_budget_required",
        "assembly_service_budget_required": "assembly_service_budget_required",
        "new_parts_only_cost_driver": "new_parts_only_increases_cost",
        "warranty_service_cost_driver": "warranty_increases_cost",
        "wifi_bluetooth_cost_driver": "wifi_bluetooth_cost",
        "upgrade_space_cost_driver": "upgrade_space_cost",
        "storage_capacity_cost_driver": "storage_capacity_cost",
        "front_type_c_cost_driver": "front_type_c_cost",
        "io_expandability_cost_driver": "io_expandability_cost",
        "low_noise_cost_driver": "low_noise_cost",
        "compact_low_noise_cost_driver": "compact_low_noise_cost",
    }

    def __init__(self, rule_path: str | Path | None = None, llm: Any | None = None):
        default_rule_path = Path(__file__).resolve().parents[1] / "rules" / "price_rules.json"
        self.rule_path = Path(rule_path or default_rule_path)
        self.rules = self.load_rules(self.rule_path)
        self.llm = llm

    def load_rules(self, rule_path: Path) -> dict[str, Any]:
        with rule_path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def normalize_text(self, text: str) -> str:
        return re.sub(r"\s+", "", text.strip().lower())

    def analyze(
        self,
        user_text: str,
        performance_result: dict[str, Any],
        appearance_result: dict[str, Any],
        other_result: dict[str, Any] | None = None,
        budget_extraction: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        resolved_user_text = str(user_text or "")
        performance_result = self._unwrap_section(performance_result, "performance")
        appearance_result = self._unwrap_section(appearance_result, "appearance")
        other_result = self._unwrap_section(other_result, "other")

        performance_result = performance_result or {}
        appearance_result = appearance_result or {}
        other_result = self._normalize_other_result(other_result or {})
        if budget_extraction is None:
            budget_extraction = self.extract_budget(resolved_user_text)

        budget_scope = self.build_budget_scope(resolved_user_text, other_result, budget_extraction)
        performance_price_impact = self.build_performance_price_impact(performance_result)
        appearance_price_impact = self.build_appearance_price_impact(appearance_result)
        other_price_impact = self.build_other_price_impact(other_result, budget_scope)
        budget_pressure = self.build_budget_pressure(
            budget_extraction=budget_extraction,
            budget_scope=budget_scope,
            performance_price_impact=performance_price_impact,
            appearance_price_impact=appearance_price_impact,
            other_price_impact=other_price_impact,
            other_result=other_result,
        )
        component_budget_policy = self.build_component_budget_policy(
            performance_result=performance_result,
            appearance_result=appearance_result,
            other_result=other_result,
            performance_price_impact=performance_price_impact,
            appearance_price_impact=appearance_price_impact,
            other_price_impact=other_price_impact,
            budget_pressure=budget_pressure,
        )
        budget_allocation_profile = self.build_budget_allocation_profile(
            performance_price_impact=performance_price_impact,
            appearance_result=appearance_result,
            component_budget_policy=component_budget_policy,
        )
        tradeoff_strategy = self.build_tradeoff_strategy(
            budget_extraction=budget_extraction,
            performance_price_impact=performance_price_impact,
            appearance_price_impact=appearance_price_impact,
            component_budget_policy=component_budget_policy,
            budget_pressure=budget_pressure,
        )
        selection_context = self.build_selection_context_for_parts_agent(
            budget_extraction=budget_extraction,
            budget_scope=budget_scope,
            budget_pressure=budget_pressure,
            performance_result=performance_result,
            appearance_result=appearance_result,
            component_budget_policy=component_budget_policy,
            tradeoff_strategy=tradeoff_strategy,
        )
        missing_information = self.build_missing_information(
            budget_extraction=budget_extraction,
            performance_result=performance_result,
            appearance_result=appearance_result,
            other_result=other_result,
        )

        output = PriceOutput(
            budget_extraction=budget_extraction,
            budget_scope=budget_scope,
            budget_pressure=budget_pressure,
            performance_price_impact=performance_price_impact,
            appearance_price_impact=appearance_price_impact,
            other_price_impact=other_price_impact,
            component_budget_policy=[ComponentBudgetPolicyItem(**item) for item in component_budget_policy],
            budget_allocation_profile=budget_allocation_profile,
            tradeoff_strategy=tradeoff_strategy,
            selection_context_for_parts_agent=selection_context,
            missing_information=missing_information,
        )
        return self._model_to_dict(PriceAgentOutput(price=output))

    def analyze_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.analyze(
            user_text=str(payload.get("user_text") or ""),
            performance_result=payload.get("performance_result") or {},
            appearance_result=payload.get("appearance_result") or {},
            other_result=payload.get("other_result") or {},
            budget_extraction=payload.get("budget_extraction"),
        )

    def extract_budget(self, user_text: str) -> dict[str, Any]:
        normalized_text = self.normalize_text(user_text)
        direct_price_phrases: list[str] = []
        min_budget = None
        max_budget = None
        target_budget = None

        range_match = re.search(
            r"(\d+(?:\.\d+)?)\s*(k|w|万)?(?:-|到|至)(\d+(?:\.\d+)?)\s*(k|w|万)?",
            normalized_text,
        )
        if range_match:
            left = self._parse_numeric_token(range_match.group(1), range_match.group(2))
            right = self._parse_numeric_token(range_match.group(3), range_match.group(4) or range_match.group(2))
            min_budget, max_budget = sorted([left, right])
            target_budget = int(round((min_budget + max_budget) / 2))
            direct_price_phrases.append(range_match.group(0))

        chinese_range = re.search(r"([一二三四五六七八九])([一二三四五六七八九])千", user_text)
        if chinese_range and min_budget is None and max_budget is None:
            a = self.CHINESE_DIGITS[chinese_range.group(1)] * 1000
            b = self.CHINESE_DIGITS[chinese_range.group(2)] * 1000
            min_budget, max_budget = sorted([a, b])
            target_budget = int(round((min_budget + max_budget) / 2))
            direct_price_phrases.append(chinese_range.group(0))

        if min_budget is None and max_budget is None:
            hard_match = re.search(r"(不超过|以内|最多)(\d+(?:\.\d+)?)(k|w|万)?", normalized_text)
            if hard_match:
                max_budget = self._parse_numeric_token(hard_match.group(2), hard_match.group(3))
                target_budget = max_budget
                direct_price_phrases.append(hard_match.group(0))

        if min_budget is None and max_budget is None:
            around_match = re.search(r"(\d+(?:\.\d+)?)(k|w|万)?左右", normalized_text)
            if around_match:
                target_budget = self._parse_numeric_token(around_match.group(1), around_match.group(2))
                min_budget = int(round(target_budget * 0.9))
                max_budget = int(round(target_budget * 1.1))
                direct_price_phrases.append(around_match.group(0))

        if min_budget is None and max_budget is None:
            chinese_single = re.search(r"([一二三四五六七八九两])千", user_text)
            if chinese_single:
                target_budget = self.CHINESE_DIGITS[chinese_single.group(1)] * 1000
                min_budget = max_budget = target_budget
                direct_price_phrases.append(chinese_single.group(0))

        if min_budget is None and max_budget is None:
            single_match = re.search(r"(\d+(?:\.\d+)?)(k|w|万)?", normalized_text)
            if single_match:
                target_budget = self._parse_numeric_token(single_match.group(1), single_match.group(2))
                min_budget = max_budget = target_budget
                direct_price_phrases.append(single_match.group(0))

        hard_limit = any(token in normalized_text for token in ["不超过", "以内", "最多", "预算卡死", "卡死"])
        if hard_limit and max_budget is None and target_budget is not None:
            max_budget = target_budget

        if "越便宜越好" in user_text or "越便宜越好" in normalized_text:
            price_priority = "high"
            value_preference = "low_price_first"
        elif any(token in normalized_text for token in ["性价比", "划算"]):
            price_priority = "medium_high"
            value_preference = "cost_effective"
        elif "不差钱" in normalized_text:
            price_priority = "low"
            value_preference = "quality_first"
        elif any(token in normalized_text for token in ["性能优先", "性能第一"]):
            price_priority = "medium"
            value_preference = "performance_first"
        elif any(token in normalized_text for token in ["品质优先", "做工好", "质量好"]):
            price_priority = "medium"
            value_preference = "quality_first"
        else:
            price_priority = "medium"
            value_preference = "balanced"

        if hard_limit:
            budget_flexibility = "none"
        elif "不差钱" in normalized_text:
            budget_flexibility = "flexible"
        elif "左右" in normalized_text:
            budget_flexibility = "soft"
        elif any(token in normalized_text for token in ["小超", "超一点", "加一点", "可以小超"]):
            budget_flexibility = "small_overspend"
        elif any(token in normalized_text for token in ["预算可加", "可以加预算", "预算灵活"]):
            budget_flexibility = "flexible"
        else:
            budget_flexibility = "unknown"

        return {
            "direct_price_phrases": list(dict.fromkeys(direct_price_phrases)),
            "min_budget": min_budget,
            "max_budget": max_budget,
            "target_budget": target_budget,
            "hard_limit": hard_limit,
            "budget_flexibility": budget_flexibility,
            "price_priority": price_priority,
            "value_preference": value_preference,
        }

    def build_budget_scope(self, user_text: str, other_result: dict[str, Any], budget_extraction: dict[str, Any]) -> dict[str, Any]:
        normalized_text = self.normalize_text(user_text)
        only_host = self._infer_bool(normalized_text, ["只要主机", "单主机", "不含显示器"], ["包含显示器", "带显示器", "一整套"])
        include_monitor = self._infer_bool(normalized_text, ["包含显示器", "带显示器", "一整套"], ["不含显示器", "只要主机", "单主机"])
        include_peripherals = self._infer_bool(normalized_text, ["带键鼠", "含外设", "键鼠"], [])
        include_os = self._infer_bool(normalized_text, ["正版系统", "带系统"], [])
        include_assembly_service = self._infer_bool(normalized_text, ["装机服务", "代装"], [])

        if other_result.get("include_monitor") is not None:
            include_monitor = bool(other_result.get("include_monitor"))
        if other_result.get("only_host") is not None:
            only_host = bool(other_result.get("only_host"))
        if other_result.get("include_peripherals") is not None:
            include_peripherals = bool(other_result.get("include_peripherals"))
        if other_result.get("include_os") is not None:
            include_os = bool(other_result.get("include_os"))
        if other_result.get("include_assembly_service") is not None:
            include_assembly_service = bool(other_result.get("include_assembly_service"))

        external_budget_items: list[str] = []
        if include_monitor:
            external_budget_items.append("monitor")
        if include_peripherals:
            external_budget_items.append("peripherals")
        if include_os:
            external_budget_items.append("os")
        if include_assembly_service:
            external_budget_items.append("assembly_service")

        max_budget = budget_extraction.get("max_budget")
        effective_host_budget = max_budget if (max_budget is not None and only_host is True) else None

        return {
            "only_host": only_host,
            "include_monitor": include_monitor,
            "include_peripherals": include_peripherals,
            "include_os": include_os,
            "include_assembly_service": include_assembly_service,
            "external_budget_items": external_budget_items,
            "estimated_external_budget_reserved": None,
            "effective_host_budget": effective_host_budget,
        }

    def build_performance_price_impact(self, performance_result: dict[str, Any]) -> dict[str, Any]:
        scenarios = list(performance_result.get("secondary_usage") or [])
        if not scenarios:
            scenarios = list(performance_result.get("primary_usage") or [])
        selected_key = self._select_performance_profile(scenarios)
        if not selected_key:
            return {
                "performance_scenario": scenarios,
                "performance_cost_level": "unknown",
                "protected_by_performance": [],
                "compressible_by_performance": [],
                "performance_price_risks": [],
                "reason": "",
            }
        profile = self.rules["performance_profiles"][selected_key]
        risks: list[str] = []
        if selected_key in ["aaa_gaming", "local_llm_inference", "deep_learning_training"]:
            risks.append("high_performance_budget_sensitive")
        return {
            "performance_scenario": scenarios or [selected_key],
            "performance_cost_level": profile["performance_cost_level"],
            "protected_by_performance": profile["protected_by_performance"],
            "compressible_by_performance": profile["compressible_by_performance"],
            "performance_price_risks": risks,
            "reason": profile["reason"],
        }

    def build_appearance_price_impact(self, appearance_result: dict[str, Any]) -> dict[str, Any]:
        drivers: list[str] = []
        protected_items: list[str] = []
        relaxable_items: list[str] = []
        reasons: list[str] = []
        impact_levels: list[str] = []

        for key in [
            appearance_result.get("case_size"),
            appearance_result.get("color"),
            appearance_result.get("case_style"),
            appearance_result.get("material"),
            appearance_result.get("noise"),
            appearance_result.get("rgb"),
        ]:
            if not key or key == "unknown":
                continue
            rule = self.rules["appearance_drivers"].get(key)
            if not rule:
                continue
            drivers.append(rule["driver"])
            impact_levels.append(rule["price_impact"])
            protected_items.extend(rule["affected_components"])
            relaxable_items.append(rule["fallback_strategy"])
            reasons.append(f"{key} 会带来 {rule['driver']}。")

        appearance_priority = appearance_result.get("appearance_priority", "unknown")
        cost_level = self._merge_appearance_cost_level(impact_levels, appearance_priority)
        return {
            "appearance_priority": appearance_priority,
            "appearance_cost_level": cost_level,
            "appearance_cost_drivers": list(dict.fromkeys(drivers)),
            "appearance_protected_items": list(dict.fromkeys(protected_items)),
            "appearance_relaxable_items": list(dict.fromkeys(relaxable_items)),
            "reason": "；".join(reasons),
        }

    def build_other_price_impact(self, other_result: dict[str, Any], budget_scope: dict[str, Any]) -> dict[str, Any]:
        scope_cost_items = list(dict.fromkeys(list(budget_scope.get("external_budget_items") or [])))
        quality_cost_drivers: list[str] = []
        functional_cost_drivers: list[str] = []
        upgrade_cost_drivers: list[str] = []

        if other_result.get("need_wifi_bluetooth") is True:
            functional_cost_drivers.append("wifi_bluetooth_required")
        if other_result.get("accept_used_parts") is False:
            quality_cost_drivers.append("new_parts_or_warranty_preferred")
        if other_result.get("need_warranty") is True:
            quality_cost_drivers.append("warranty_required")
        if other_result.get("upgrade_space_required") is True:
            upgrade_cost_drivers.append("upgrade_space_required")
        if other_result.get("storage_capacity_requirement"):
            functional_cost_drivers.append("storage_capacity_required")

        return {
            "scope_cost_items": scope_cost_items,
            "quality_cost_drivers": quality_cost_drivers,
            "functional_cost_drivers": functional_cost_drivers,
            "upgrade_cost_drivers": upgrade_cost_drivers,
        }

    def build_budget_pressure(
        self,
        budget_extraction: dict[str, Any],
        budget_scope: dict[str, Any],
        performance_price_impact: dict[str, Any],
        appearance_price_impact: dict[str, Any],
        other_price_impact: dict[str, Any],
        other_result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        max_budget = budget_extraction.get("max_budget") or budget_extraction.get("target_budget")
        if max_budget is None:
            return {"level": "unknown", "reason": "用户未给出明确预算。", "risk_flags": []}

        risk_flags: list[str] = []
        score = {
            "low": 1,
            "medium": 2,
            "medium_high": 3,
            "high": 4,
            "very_high": 5,
            "unknown": 2,
        }.get(performance_price_impact.get("performance_cost_level", "unknown"), 2)

        appearance_level = appearance_price_impact.get("appearance_cost_level", "unknown")
        score += {
            "low": 0,
            "medium": 1,
            "medium_high": 2,
            "high": 3,
            "neutral_or_saving": -1,
            "low_to_medium": 1,
            "unknown": 0,
        }.get(appearance_level, 0)

        if other_price_impact.get("scope_cost_items"):
            score += 1
            risk_flags.append("external_scope_cost")
        if budget_extraction.get("hard_limit"):
            score += 1
            risk_flags.append("strict_budget_limit")
        if any(driver in appearance_price_impact.get("appearance_cost_drivers", []) for driver in ["itx_premium", "white_build_premium", "panoramic_case_premium", "rgb_lighting_cost", "low_noise_cost"]):
            score += 1

        for signal_name in self._get_price_signal_names(other_result or {}):
            mapped_flag = self.PRICE_SIGNAL_RISK_FLAG_MAP.get(signal_name)
            if mapped_flag:
                risk_flags.append(mapped_flag)

        perf_level = performance_price_impact.get("performance_cost_level")
        if max_budget <= 6000 and perf_level in ["high", "very_high"]:
            score += 2
        elif max_budget <= 8000 and perf_level == "very_high":
            score += 2
        elif max_budget <= 7000 and perf_level == "medium_high":
            score += 1

        if score <= 2:
            level = "low"
        elif score <= 4:
            level = "medium"
        elif score <= 6:
            level = "medium_high"
        elif score <= 8:
            level = "high"
        else:
            level = "over_constrained"

        reason = f"预算约束需要同时覆盖性能成本等级 {perf_level}、外观溢价和额外范围成本。"
        return {"level": level, "reason": reason, "risk_flags": list(dict.fromkeys(risk_flags))}

    def build_component_budget_policy(
        self,
        performance_result: dict[str, Any],
        appearance_result: dict[str, Any],
        other_result: dict[str, Any],
        performance_price_impact: dict[str, Any],
        appearance_price_impact: dict[str, Any],
        other_price_impact: dict[str, Any],
        budget_pressure: dict[str, Any],
    ) -> list[dict[str, Any]]:
        protected_by_performance = set(performance_price_impact.get("protected_by_performance") or [])
        appearance_protected = set(appearance_price_impact.get("appearance_protected_items") or [])
        performance_scenarios = set(performance_price_impact.get("performance_scenario") or [])
        other_map = self._build_other_component_map(other_result, other_price_impact)
        appearance_case = appearance_result.get("case_size")
        appearance_color = appearance_result.get("color")
        appearance_noise = appearance_result.get("noise")

        policies: list[dict[str, Any]] = []
        for component in self.COMPONENTS:
            performance_relevance = self._component_relevance(component, protected_by_performance, performance_scenarios)
            appearance_relevance = self._appearance_component_relevance(component, appearance_protected, appearance_result)
            other_relevance = other_map.get(component, "none")
            protected = performance_relevance == "high" or appearance_relevance == "high" or other_relevance == "high"
            can_cut_cost = component not in protected_by_performance and component != "psu"
            if component == "psu":
                can_cut_cost = False
            if component == "gpu" and self._is_no_graphics_scenario(performance_scenarios):
                performance_relevance = "low"
                protected = False
                can_cut_cost = True

            budget_priority = self._merge_budget_priority(performance_relevance, appearance_relevance, other_relevance, component, appearance_case, appearance_color, appearance_noise)
            price_control_level = self._derive_price_control_level(component, protected, can_cut_cost, budget_priority, performance_scenarios)
            must_preserve_attributes = self._build_must_preserve_attributes(component, performance_scenarios, appearance_result, other_result)
            relaxable_attributes = self._build_relaxable_attributes(component, appearance_result, performance_price_impact, appearance_price_impact)
            can_upgrade_if_budget_allows = budget_pressure.get("level") in ["low", "medium"] and budget_priority in ["medium_high", "high"]
            selection_instruction = self._build_selection_instruction(
                component=component,
                budget_priority=budget_priority,
                price_control_level=price_control_level,
                protected=protected,
            )
            reason = self._build_component_reason(component, performance_relevance, appearance_relevance, other_relevance, protected)

            policies.append(
                {
                    "component": component,
                    "chinese_name": self.COMPONENT_CN[component],
                    "performance_relevance": performance_relevance,
                    "appearance_relevance": appearance_relevance,
                    "other_relevance": other_relevance,
                    "budget_priority": budget_priority,
                    "price_control_level": price_control_level,
                    "protected": protected,
                    "can_cut_cost": can_cut_cost,
                    "can_upgrade_if_budget_allows": can_upgrade_if_budget_allows,
                    "must_preserve_attributes": must_preserve_attributes,
                    "relaxable_attributes": relaxable_attributes,
                    "selection_instruction": selection_instruction,
                    "reason": reason,
                }
            )
        return policies

    def build_budget_allocation_profile(
        self,
        performance_price_impact: dict[str, Any],
        appearance_result: dict[str, Any],
        component_budget_policy: list[dict[str, Any]],
    ) -> dict[str, Any]:
        selected_key = self._select_performance_profile(performance_price_impact.get("performance_scenario") or [])
        if selected_key:
            base_ranges = self.rules["performance_profiles"][selected_key]["component_ranges"]
            profile_name = selected_key
        else:
            base_ranges = self.rules["performance_profiles"]["general_office"]["component_ranges"]
            profile_name = "general_office"

        targets = {component: base_ranges[component]["target_ratio"] for component in self.COMPONENTS}
        if appearance_result.get("case_size") == "itx_compact":
            for component in ["case", "motherboard", "psu", "cooling"]:
                targets[component] += 0.02
            targets["gpu"] = max(0.0, targets["gpu"] - 0.03)
        if appearance_result.get("color") == "white":
            for component in ["case", "cooling"]:
                targets[component] += 0.01
            targets["gpu"] = max(0.0, targets["gpu"] - 0.01)
        if appearance_result.get("case_style") == "panoramic":
            targets["case"] += 0.02
            targets["cooling"] += 0.01
        if appearance_result.get("noise") in ["silent", "low_noise"]:
            targets["cooling"] += 0.02
            targets["psu"] += 0.01

        total = sum(targets.values()) or 1.0
        normalized_targets = {key: value / total for key, value in targets.items()}

        component_ranges = {}
        for component in self.COMPONENTS:
            spread = base_ranges[component]["spread"]
            target = round(normalized_targets[component], 4)
            component_ranges[component] = {
                "min_ratio": round(max(0.0, target - spread), 4),
                "target_ratio": target,
                "max_ratio": round(min(1.0, target + spread), 4),
            }

        return {
            "profile_name": profile_name,
            "allocation_mode": "range",
            "component_ranges": component_ranges,
        }

    def build_tradeoff_strategy(
        self,
        budget_extraction: dict[str, Any],
        performance_price_impact: dict[str, Any],
        appearance_price_impact: dict[str, Any],
        component_budget_policy: list[dict[str, Any]],
        budget_pressure: dict[str, Any],
    ) -> dict[str, Any]:
        protected_components = [item["component"] for item in component_budget_policy if item["protected"]]
        can_relax: list[str] = []
        fallback_plans: list[str] = []
        for driver in appearance_price_impact.get("appearance_cost_drivers", []):
            if driver == "itx_premium":
                can_relax.append("itx_size_preference")
                fallback_plans.append("ITX成本过高 -> 放宽到M-ATX")
            elif driver == "white_build_premium":
                can_relax.append("full_white_internal_parts")
                fallback_plans.append("白色海景房成本过高 -> 保留白色机箱，内部配件颜色放宽")
            elif driver == "low_noise_cost":
                can_relax.append("extreme_silent_tuning")
                fallback_plans.append("静音成本过高 -> 保留基础低噪，放弃极致静音")
            elif driver in ["rgb_lighting_cost", "panoramic_case_premium", "dual_chamber_premium", "aluminum_case_premium"]:
                can_relax.append(driver)

        if performance_price_impact.get("performance_scenario") and any(tag in performance_price_impact["performance_scenario"] for tag in ["aaa_gaming"]):
            fallback_plans.append("3A游戏预算不足 -> 降低分辨率/画质目标或提示预算不足")

        cannot_relax = list(dict.fromkeys(protected_components))
        if budget_extraction.get("hard_limit"):
            cannot_relax.insert(0, "budget_upper_limit")

        return {
            "strategy_name": f"{budget_pressure.get('level', 'unknown')}_budget_tradeoff",
            "priority_order": cannot_relax + [item for item in self.COMPONENTS if item not in cannot_relax],
            "can_relax": list(dict.fromkeys(can_relax)),
            "cannot_relax": cannot_relax,
            "fallback_plans": list(dict.fromkeys(fallback_plans)),
        }

    def build_selection_context_for_parts_agent(
        self,
        budget_extraction: dict[str, Any],
        budget_scope: dict[str, Any],
        budget_pressure: dict[str, Any],
        performance_result: dict[str, Any],
        appearance_result: dict[str, Any],
        component_budget_policy: list[dict[str, Any]],
        tradeoff_strategy: dict[str, Any],
    ) -> dict[str, Any]:
        protected_components = [item["component"] for item in component_budget_policy if item["protected"]]
        cost_cut_components = [item["component"] for item in component_budget_policy if item["can_cut_cost"] and item["budget_priority"] == "low"]
        must_satisfy: list[str] = []
        prefer_satisfy: list[str] = []
        avoid: list[str] = []

        if budget_extraction.get("hard_limit"):
            must_satisfy.append("budget_upper_limit")
        if appearance_result.get("case_size") not in [None, "unknown"]:
            must_satisfy.append(f"case_size:{appearance_result.get('case_size')}")
        if appearance_result.get("rgb") == "no_rgb":
            must_satisfy.append("no_rgb_policy")
            avoid.extend(["rgb_fans", "rgb_memory", "rgb_cooler", "strong_rgb"])
        if appearance_result.get("color") == "white":
            prefer_satisfy.append("white_case_preferred")
            avoid.append("non_white_case_only_strategy")
        if appearance_result.get("case_style") == "panoramic":
            prefer_satisfy.append("panoramic_case_preferred")
        if appearance_result.get("noise") in ["silent", "low_noise"]:
            prefer_satisfy.append("low_noise_preferred")
        if appearance_result.get("case_size") == "itx_compact":
            avoid.append("oversized_case")

        selection_strategy = tradeoff_strategy.get("strategy_name", "")
        if performance_result.get("secondary_usage"):
            selection_strategy = f"{selection_strategy}:{','.join(performance_result.get('secondary_usage')[:2])}"

        return {
            "total_budget": {
                "min_budget": budget_extraction.get("min_budget"),
                "max_budget": budget_extraction.get("max_budget"),
                "target_budget": budget_extraction.get("target_budget"),
                "hard_limit": budget_extraction.get("hard_limit"),
                "effective_host_budget": budget_scope.get("effective_host_budget"),
            },
            "selection_strategy": selection_strategy,
            "budget_pressure": budget_pressure.get("level"),
            "protected_components": protected_components,
            "cost_cut_components": cost_cut_components,
            "must_satisfy": list(dict.fromkeys(must_satisfy)),
            "prefer_satisfy": list(dict.fromkeys(prefer_satisfy)),
            "avoid": list(dict.fromkeys(avoid)),
            "required_compatibility_checks": [
                "cpu_motherboard_socket",
                "motherboard_case_form_factor",
                "gpu_length_clearance",
                "cpu_cooler_height_clearance",
                "psu_form_factor",
                "ram_motherboard_compatibility",
                "ssd_interface_compatibility",
                "case_airflow",
            ],
        }

    def build_missing_information(
        self,
        budget_extraction: dict[str, Any],
        performance_result: dict[str, Any],
        appearance_result: dict[str, Any],
        other_result: dict[str, Any],
    ) -> list[str]:
        missing: list[str] = []
        if budget_extraction.get("max_budget") is None and budget_extraction.get("target_budget") is None:
            missing.append("预算上限")
        if not performance_result:
            missing.append("核心性能场景")
        if appearance_result.get("color") == "white":
            missing.append("是否必须全白内部配件")
        if appearance_result.get("case_size") == "itx_compact":
            missing.append("是否接受M-ATX而不是ITX")
        if appearance_result.get("noise") in ["silent", "low_noise"]:
            missing.append("是否更重视静音还是散热")
        if other_result.get("include_monitor") is None and other_result.get("only_host") is None:
            missing.append("预算是否包含显示器")
        return list(dict.fromkeys(missing))

    def _unwrap_section(self, value: Any, key: str) -> dict[str, Any]:
        if isinstance(value, dict) and key in value and isinstance(value[key], dict):
            return value[key]
        return value if isinstance(value, dict) else {}

    def _normalize_other_result(self, other_result: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(other_result, dict):
            return {}

        purchase_scope = dict(other_result.get("purchase_scope") or {})
        connectivity = dict(other_result.get("connectivity") or {})
        purchase_risk = dict(other_result.get("purchase_risk") or {})
        warranty_service = dict(other_result.get("warranty_service") or {})
        upgrade_plan = dict(other_result.get("upgrade_plan") or {})
        special_requirements = dict(other_result.get("special_requirements") or {})

        if not any([purchase_scope, connectivity, purchase_risk, warranty_service, upgrade_plan, special_requirements]):
            return other_result

        normalized = dict(other_result)
        need_wifi = connectivity.get("need_wifi")
        need_bluetooth = connectivity.get("need_bluetooth")
        normalized.update(
            {
                "only_host": purchase_scope.get("only_host"),
                "include_monitor": purchase_scope.get("include_monitor"),
                "include_peripherals": purchase_scope.get("include_peripherals"),
                "include_os": purchase_scope.get("include_os"),
                "include_assembly_service": purchase_scope.get("include_assembly_service"),
                "need_wifi_bluetooth": True if (need_wifi is True or need_bluetooth is True) else None,
                "accept_used_parts": purchase_risk.get("accept_used_parts"),
                "need_warranty": warranty_service.get("need_warranty"),
                "upgrade_space_required": upgrade_plan.get("upgrade_space_required"),
                "storage_capacity_requirement": special_requirements.get("storage_capacity_requirement"),
            }
        )
        return normalized

    def _get_price_signal_names(self, other_result: dict[str, Any]) -> list[str]:
        other = other_result.get("other", other_result) if other_result else {}
        signals = other.get("cross_module_signals", {}).get("price_signals", [])
        names: list[str] = []
        for item in signals:
            if isinstance(item, dict):
                signal = item.get("signal")
                if signal:
                    names.append(signal)
            elif item:
                names.append(str(item))
        return names

    def _parse_numeric_token(self, number: str, unit: str | None) -> int:
        value = float(number)
        if unit in ("k", "K"):
            value *= 1000
        elif unit in ("w", "W", "万"):
            value *= 10000
        return int(round(value))

    def _infer_bool(self, text: str, positive_tokens: list[str], negative_tokens: list[str]) -> bool | None:
        if any(token in text for token in positive_tokens):
            return True
        if any(token in text for token in negative_tokens):
            return False
        return None

    def _select_performance_profile(self, scenarios: list[str]) -> str | None:
        priority = [
            "deep_learning_training",
            "local_llm_inference",
            "aaa_gaming",
            "professional_video_editing",
            "3d_modeling_rendering",
            "simulation_computing",
            "fps_esports",
            "light_video_editing",
            "programming_development",
            "general_office",
            "general_study",
        ]
        for key in priority:
            if key in scenarios:
                return key
        return None

    def _merge_appearance_cost_level(self, impact_levels: list[str], appearance_priority: str) -> str:
        if not impact_levels:
            return "unknown"
        score = 0
        for level in impact_levels:
            score += {
                "neutral_or_saving": 0,
                "low": 1,
                "low_to_medium": 1,
                "medium": 2,
                "medium_high": 3,
                "high": 4,
            }.get(level, 0)
        if appearance_priority == "high":
            score += 1
        if score <= 1:
            return "low"
        if score <= 3:
            return "medium"
        if score <= 5:
            return "medium_high"
        return "high"

    def _build_other_component_map(self, other_result: dict[str, Any], other_price_impact: dict[str, Any]) -> dict[str, str]:
        out = {component: "none" for component in self.COMPONENTS}
        if "wifi_bluetooth_required" in other_price_impact.get("functional_cost_drivers", []):
            out["motherboard"] = "medium"
        if "storage_capacity_required" in other_price_impact.get("functional_cost_drivers", []):
            out["ssd"] = "high"
        if "upgrade_space_required" in other_price_impact.get("upgrade_cost_drivers", []):
            out["motherboard"] = "high"
            out["psu"] = "medium_high"
            out["case"] = "medium_high"
        if "new_parts_or_warranty_preferred" in other_price_impact.get("quality_cost_drivers", []):
            out["psu"] = "medium_high" if out["psu"] == "medium_high" else "medium"
        if "warranty_required" in other_price_impact.get("quality_cost_drivers", []):
            out["psu"] = "medium_high" if out["psu"] in ["medium", "medium_high"] else "medium"
        return out

    def _component_relevance(self, component: str, protected: set[str], scenarios: set[str]) -> str:
        if component in protected:
            return "high"
        if component == "gpu" and self._is_no_graphics_scenario(scenarios):
            return "low"
        if component in ["motherboard", "case"]:
            return "medium" if scenarios else "low"
        return "low"

    def _appearance_component_relevance(self, component: str, protected_items: set[str], appearance_result: dict[str, Any]) -> str:
        if component in protected_items:
            return "high"
        if component == "case" and any(appearance_result.get(key) not in [None, "unknown"] for key in ["case_style", "color", "case_size"]):
            return "high"
        if component in ["cooling", "psu"] and appearance_result.get("noise") in ["silent", "low_noise"]:
            return "high"
        return "none"

    def _merge_budget_priority(
        self,
        performance_relevance: str,
        appearance_relevance: str,
        other_relevance: str,
        component: str,
        case_size: str | None,
        color: str | None,
        noise: str | None,
    ) -> str:
        score = max(
            self._relevance_score(performance_relevance),
            self._relevance_score(appearance_relevance),
            self._relevance_score(other_relevance),
        )
        if component == "psu":
            score = max(score, 2)
        if case_size == "itx_compact" and component in ["case", "motherboard", "psu", "cooling"]:
            score = max(score, 3)
        if color == "white" and component == "case":
            score = max(score, 3)
        if noise in ["silent", "low_noise"] and component in ["cooling", "psu"]:
            score = max(score, 3)
        return {0: "low", 1: "medium", 2: "medium", 3: "medium_high"}.get(score, "high") if score < 4 else "high"

    def _derive_price_control_level(self, component: str, protected: bool, can_cut_cost: bool, budget_priority: str, scenarios: set[str]) -> str:
        if protected:
            return "protected"
        if component == "gpu" and self._is_no_graphics_scenario(scenarios):
            return "minimal"
        if component == "case" and budget_priority in ["medium_high", "high"]:
            return "optional_upgrade"
        if can_cut_cost and budget_priority == "low":
            return "minimal"
        if can_cut_cost:
            return "cost_controlled"
        return "balanced"

    def _build_must_preserve_attributes(self, component: str, scenarios: set[str], appearance_result: dict[str, Any], other_result: dict[str, Any]) -> list[str]:
        items: list[str] = []
        if component == "gpu":
            if "aaa_gaming" in scenarios:
                items.extend(["3a_gameplay_performance", "sufficient_vram_for_target"])
            if "local_llm_inference" in scenarios or "deep_learning_training" in scenarios:
                items.extend(["ai_vram_capacity", "gpu_compute_capacity"])
        if component == "cpu":
            if "programming_development" in scenarios or "simulation_computing" in scenarios:
                items.append("multi_core_productivity")
            if "fps_esports" in scenarios:
                items.append("high_fps_stability")
        if component == "ram":
            items.append("minimum_capacity_for_workload")
        if component == "ssd":
            items.append("system_and_project_capacity")
        if component == "psu":
            items.append("reliable_wattage_margin")
        if component == "motherboard":
            items.append("platform_compatibility")
            if appearance_result.get("case_size") not in [None, "unknown"]:
                items.append("required_form_factor")
        if component == "case":
            if appearance_result.get("case_style") not in [None, "unknown"]:
                items.append(f"style:{appearance_result.get('case_style')}")
            if appearance_result.get("color") == "white":
                items.append("white_case")
        if component == "cooling":
            if appearance_result.get("noise") in ["silent", "low_noise"]:
                items.append("low_noise_operation")
            items.append("baseline_thermal_stability")
        return list(dict.fromkeys(items))

    def _build_relaxable_attributes(
        self,
        component: str,
        appearance_result: dict[str, Any],
        performance_price_impact: dict[str, Any],
        appearance_price_impact: dict[str, Any],
    ) -> list[str]:
        items: list[str] = []
        if component in ["gpu", "ram", "cooling"] and appearance_result.get("color") == "white":
            items.append("all_white_internal_parts")
        if component in ["cooling", "ram", "case", "motherboard"] and appearance_result.get("rgb") in ["rgb", "argb"]:
            items.append("premium_rgb_effects")
        if component == "motherboard":
            items.append("premium_motherboard_features")
        if component == "case" and appearance_result.get("case_style") in ["dual_chamber", "panoramic"]:
            items.append("premium_case_style")
        if component == "cooling" and appearance_result.get("noise") in ["silent", "low_noise"]:
            items.append("extreme_silent_tuning")
        return list(dict.fromkeys(items))

    def _build_selection_instruction(self, component: str, budget_priority: str, price_control_level: str, protected: bool) -> str:
        if protected:
            return f"优先保护 {self.COMPONENT_CN[component]} 的核心规格，不建议为了省钱明显降档。"
        if price_control_level == "minimal":
            return f"{self.COMPONENT_CN[component]} 可采取最低满足策略，把预算让给更关键配件。"
        if price_control_level == "cost_controlled":
            return f"{self.COMPONENT_CN[component]} 应控制成本，优先满足基础兼容与稳定。"
        if price_control_level == "optional_upgrade":
            return f"{self.COMPONENT_CN[component]} 可在预算允许时升级，预算紧张时可放宽外观溢价。"
        return f"{self.COMPONENT_CN[component]} 采取均衡策略。"

    def _build_component_reason(self, component: str, performance_relevance: str, appearance_relevance: str, other_relevance: str, protected: bool) -> str:
        reasons = []
        if performance_relevance != "none":
            reasons.append(f"性能相关性{performance_relevance}")
        if appearance_relevance != "none":
            reasons.append(f"外观相关性{appearance_relevance}")
        if other_relevance != "none":
            reasons.append(f"其他约束相关性{other_relevance}")
        if protected:
            reasons.append("需要重点保护")
        return "，".join(reasons)

    def _is_no_graphics_scenario(self, scenarios: set[str]) -> bool:
        return bool(scenarios & {"general_office", "general_study", "programming_development"}) and not bool(
            scenarios & {"aaa_gaming", "fps_esports", "3d_modeling_rendering", "local_llm_inference", "deep_learning_training", "professional_video_editing"}
        )

    @staticmethod
    def _relevance_score(value: str) -> int:
        return {
            "none": 0,
            "low": 1,
            "medium": 2,
            "medium_high": 3,
            "high": 4,
        }.get(value, 0)

    @staticmethod
    def _model_to_dict(model: Any) -> dict[str, Any]:
        if hasattr(model, "model_dump"):
            return model.model_dump()
        return model.dict()
