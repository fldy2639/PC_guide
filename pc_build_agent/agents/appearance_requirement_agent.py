from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pc_build_agent.prompts.appearance_prompts import APPEARANCE_EXTRACTION_PROMPT
from pc_build_agent.schemas.appearance_schema import AppearanceAgentOutput, AppearanceOutput
from pc_build_agent.services.requirement_knowledge_repository import RequirementKnowledgeRepository


class AppearanceRequirementAgent:
    NEGATIVE_OVERRIDES = [
        {
            "dimension": "rgb",
            "value": "no_rgb",
            "keywords": ["不要rgb", "不要 rgb", "不要灯", "不要光污染", "不想要rgb", "不喜欢rgb"],
            "compatibility_constraints": [
                "避免选择RGB风扇、RGB内存和灯效散热器",
                "如果配件带灯，需要支持关闭灯效",
            ],
        },
        {
            "dimension": "case_size",
            "value": "compact_m_atx",
            "keywords": ["不要太大", "不想太大"],
            "preferred_form_factor": ["M-ATX", "Mini-ITX"],
            "compatibility_constraints": [
                "优先考虑M-ATX紧凑机箱",
                "需要校验显卡长度",
                "需要校验散热器高度",
            ],
        },
        {
            "dimension": "case_style",
            "value": "minimalist",
            "keywords": ["不要花哨", "不想花哨"],
            "compatibility_constraints": [
                "优先选择无明显灯光或低调外观机箱",
                "避免过度电竞风外观",
            ],
            "constraints_for_selection_agent": {
                "avoid_features": ["strong_rgb", "aggressive_gaming_style"],
                "rgb_policy_hint": "prefer_no_rgb_or_low_rgb",
            },
        },
        {
            "dimension": "material",
            "value": "avoid_plastic",
            "keywords": ["不要塑料感"],
        },
        {
            "dimension": "color",
            "value": "no_preference",
            "keywords": ["颜色无所谓", "颜色随便", "颜色都行"],
        },
    ]

    FORM_FACTOR_MAP = {
        "itx_compact": ["Mini-ITX"],
        "compact_m_atx": ["M-ATX", "Mini-ITX"],
        "standard_atx": ["ATX", "M-ATX", "Mini-ITX"],
        "large_atx": ["ATX", "E-ATX", "M-ATX"],
        "unknown": [],
    }

    DEFAULT_VALUES = {
        "case_size": "unknown",
        "case_style": "unknown",
        "color": "unknown",
        "material": "unknown",
        "rgb": "unknown",
        "noise": "unknown",
        "appearance_priority": "unknown",
    }

    def __init__(
        self,
        rule_path: str | Path | None = None,
        llm: Any | None = None,
        knowledge_repo: RequirementKnowledgeRepository | None = None,
    ):
        self.rule_path = Path(rule_path) if rule_path is not None else None
        if self.rule_path is not None:
            self.rules = self.load_rules(self.rule_path)
        else:
            repo = knowledge_repo or RequirementKnowledgeRepository()
            self.rules = self.load_rule_items(repo.get_rules("appearance"))
        self.llm = llm

    def load_rules(self, rule_path: Path) -> list[dict]:
        with rule_path.open("r", encoding="utf-8") as f:
            return self.load_rule_items(json.load(f))

    @staticmethod
    def load_rule_items(raw: Any) -> list[dict]:
        return list(raw or [])

    def normalize_text(self, text: str) -> str:
        return text.strip().lower()

    def analyze(self, user_text: str) -> dict:
        normalized_text = self.normalize_text(user_text)

        rule_matches = self.match_rules(normalized_text)

        llm_extraction = None
        if self.llm is not None:
            llm_extraction = self.extract_with_llm(user_text)

        merged = self.merge_rule_and_llm_results(
            rule_matches=rule_matches,
            llm_extraction=llm_extraction,
            user_text=user_text,
        )

        conflicts_or_warnings = self.detect_conflicts(merged)

        constraints = self.build_selection_constraints(
            merged=merged,
            conflicts_or_warnings=conflicts_or_warnings,
        )

        output = self.build_output(
            merged=merged,
            rule_matches=rule_matches,
            conflicts_or_warnings=conflicts_or_warnings,
            constraints_for_selection_agent=constraints,
        )

        return self._model_to_dict(AppearanceAgentOutput(appearance=output))

    def match_rules(self, normalized_text: str) -> list[dict]:
        matched_rules = []
        matched_rules.extend(self._match_negative_overrides(normalized_text))
        matched_rules.extend(self._infer_flexible_appearance_rules(normalized_text))

        for rule in self.rules:
            hit_keywords = []
            for keyword in rule.get("keywords", []):
                if keyword.lower() in normalized_text:
                    hit_keywords.append(keyword)

            if hit_keywords:
                if self._is_overridden_by_negative(rule["dimension"], normalized_text):
                    continue
                matched_rules.append(
                    {
                        "rule_id": rule["rule_id"],
                        "dimension": rule["dimension"],
                        "normalized_value": rule["normalized_value"],
                        "hit_keywords": hit_keywords,
                        "effects": rule.get("effects", {}),
                        "description": rule.get("description", ""),
                    }
                )

        return matched_rules

    def _match_negative_overrides(self, normalized_text: str) -> list[dict]:
        matches: list[dict] = []
        for override in self.NEGATIVE_OVERRIDES:
            hit_keywords = [keyword for keyword in override.get("keywords", []) if keyword in normalized_text]
            if not hit_keywords:
                continue
            effects: dict[str, Any] = {
                override["dimension"]: override["value"],
            }
            if override.get("preferred_form_factor"):
                effects["preferred_form_factor"] = override["preferred_form_factor"]
            if override.get("compatibility_constraints"):
                effects["compatibility_constraints"] = override["compatibility_constraints"]
            if override.get("constraints_for_selection_agent"):
                effects["constraints_for_selection_agent"] = override["constraints_for_selection_agent"]
            matches.append(
                {
                    "rule_id": f"negative_override_{override['dimension']}_{override['value']}",
                    "dimension": override["dimension"],
                    "normalized_value": override["value"],
                    "hit_keywords": hit_keywords,
                    "effects": effects,
                    "description": "否定表达优先规则",
                }
            )
        return matches

    def _is_overridden_by_negative(self, dimension: str, normalized_text: str) -> bool:
        for override in self.NEGATIVE_OVERRIDES:
            if override["dimension"] != dimension:
                continue
            if any(keyword in normalized_text for keyword in override.get("keywords", [])):
                return True
        return False

    def extract_with_llm(self, user_text: str) -> dict | None:
        if not self.llm:
            return None
        if hasattr(self.llm, "api_key") and not getattr(self.llm, "api_key"):
            return None
        if hasattr(self.llm, "chat_json"):
            prompt = APPEARANCE_EXTRACTION_PROMPT.replace("{user_text}", user_text)
            messages = [
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_text},
            ]
            try:
                return self.llm.chat_json(messages, step="appearance_extraction")
            except Exception:
                return None
        return None

    def _infer_flexible_appearance_rules(self, normalized_text: str) -> list[dict[str, Any]]:
        rules: list[dict[str, Any]] = []
        for dimension, value, pattern in [
            ("color", "white", r"(奶油白|珍珠白|象牙白|月光白|雪白|纯白|白色|白机箱|白主机)"),
            ("color", "black", r"(曜石黑|黑武士|纯黑|黑色|黑机箱|黑主机)"),
            ("color", "silver_or_gray", r"(银色|灰色|钛色|月岩灰|太空灰|金属灰)"),
            ("color", "pink", r"(粉色|樱花粉|玫瑰粉)"),
            ("color", "mixed", r"(撞色|双色|黑白配|黑白色)"),
            ("case_style", "panoramic", r"(全景|鱼缸|展示仓|展示感|玻璃房)"),
            ("case_style", "dual_chamber", r"(双仓|分仓|背插|走线整洁)"),
            ("case_style", "minimalist", r"(简洁|简约|低调|素雅|商务|干净外观|不花)"),
            ("case_style", "gaming", r"(电竞|机甲|战斗感|赛博|炫酷)"),
            ("case_style", "airflow_mesh", r"(网孔|mesh|通风|风道|散热好)"),
            ("case_style", "open_frame", r"(开放式|开放机架)"),
            ("case_size", "itx_compact", r"(itx|mini[- ]?itx|sff|迷你|小主机|越小越好)"),
            ("case_size", "compact_m_atx", r"(紧凑|不占地方|桌面空间|小一点|宿舍桌面)"),
            ("case_size", "standard_atx", r"(普通大小|常规机箱|正常机箱)"),
            ("case_size", "large_atx", r"(大机箱|全塔|扩展强|空间大)"),
            ("material", "tempered_glass", r"(玻璃|侧透|全景)"),
            ("material", "metal", r"(金属|钢板|硬朗)"),
            ("material", "aluminum", r"(铝合金|铝制|铝壳)"),
            ("material", "mesh", r"(网孔|mesh|透气)"),
            ("material", "matte", r"(磨砂|哑光)"),
            ("material", "avoid_plastic", r"(不要塑料感|别太塑料|廉价感)"),
            ("rgb", "argb", r"(argb|神光同步|可调灯)"),
            ("rgb", "rgb", r"(rgb|彩灯|灯效)"),
            ("rgb", "low_rgb", r"(低调灯|一点灯|不要太亮)"),
            ("rgb", "no_rgb", r"(无光|不要灯|不要rgb|不带灯|光污染)"),
            ("noise", "silent", r"(越安静越好|不能吵|强静音|极静音)"),
            ("noise", "low_noise", r"(安静|低噪|小声|别太吵|寝室夜里)"),
            ("noise", "airflow_first", r"(散热优先|风量大|温度低|压得住)"),
        ]:
            match = re.search(pattern, normalized_text, flags=re.IGNORECASE)
            if not match:
                continue
            rules.append(
                {
                    "rule_id": f"flexible_{dimension}_{value}",
                    "dimension": dimension,
                    "normalized_value": value,
                    "hit_keywords": [match.group(1)],
                    "effects": {dimension: value},
                    "description": "结构化语义兜底规则",
                }
            )
        return rules

    def merge_rule_and_llm_results(
        self,
        rule_matches: list[dict],
        llm_extraction: dict | None,
        user_text: str,
    ) -> dict:
        merged = {
            "matched_keywords": [],
            "case_size": "unknown",
            "preferred_form_factor": [],
            "case_style": "unknown",
            "color": "unknown",
            "material": "unknown",
            "rgb": "unknown",
            "noise": "unknown",
            "appearance_priority": "unknown",
            "compatibility_constraints": [],
            "conflicts_or_warnings": [],
            "constraints_for_selection_agent": {},
            "missing_information": [],
            "_user_text": user_text,
        }

        for match in rule_matches:
            merged["matched_keywords"].extend(match.get("hit_keywords", []))
            effects = match.get("effects", {})

            for key in ["case_size", "case_style", "color", "material", "rgb", "noise"]:
                value = effects.get(key)
                if value:
                    if merged[key] == "unknown":
                        merged[key] = value

            if "preferred_form_factor" in effects and not merged["preferred_form_factor"]:
                merged["preferred_form_factor"] = effects["preferred_form_factor"]

            if "compatibility_constraints" in effects:
                merged["compatibility_constraints"].extend(effects["compatibility_constraints"])

            if "conflicts_or_warnings" in effects:
                merged["conflicts_or_warnings"].extend(effects["conflicts_or_warnings"])

            if "constraints_for_selection_agent" in effects:
                merged["constraints_for_selection_agent"] = self._deep_merge_dict(
                    merged["constraints_for_selection_agent"],
                    effects["constraints_for_selection_agent"],
                )

        if not merged["preferred_form_factor"]:
            merged["preferred_form_factor"] = self.FORM_FACTOR_MAP.get(merged["case_size"], [])

        if llm_extraction:
            self.apply_llm_supplement(merged, llm_extraction)

        merged["matched_keywords"] = list(dict.fromkeys(merged["matched_keywords"]))
        merged["compatibility_constraints"] = list(dict.fromkeys(merged["compatibility_constraints"]))
        merged["conflicts_or_warnings"] = list(dict.fromkeys(merged["conflicts_or_warnings"]))
        merged["missing_information"] = list(dict.fromkeys(merged["missing_information"]))

        merged["appearance_priority"] = self.estimate_appearance_priority(
            merged=merged,
            rule_matches=rule_matches,
            user_text=user_text,
        )

        return merged

    def apply_llm_supplement(self, merged: dict, llm_extraction: dict) -> None:
        for key in ["case_size", "case_style", "color", "material", "rgb", "noise"]:
            if merged.get(key) == "unknown":
                value_info = llm_extraction.get(key)
                if isinstance(value_info, dict):
                    value = value_info.get("value")
                else:
                    value = value_info
                if value and value != "unknown":
                    merged[key] = value

        if llm_extraction.get("missing_information"):
            merged["missing_information"].extend(llm_extraction["missing_information"])

        if llm_extraction.get("conflicts_or_warnings"):
            merged["conflicts_or_warnings"].extend(llm_extraction["conflicts_or_warnings"])

    def estimate_appearance_priority(
        self,
        merged: dict,
        rule_matches: list[dict],
        user_text: str,
    ) -> str:
        if not rule_matches:
            return "unknown"

        normalized_text = self.normalize_text(user_text)
        high_signal_keywords = ["必须", "一定", "只要", "颜值", "外观优先", "全白", "海景房"]
        low_signal_keywords = ["外观无所谓", "随便", "都行", "无所谓"]

        if any(k in normalized_text for k in low_signal_keywords):
            return "low"
        if any(k in normalized_text for k in high_signal_keywords):
            return "high"

        meaningful_fields = [
            merged.get("case_size"),
            merged.get("case_style"),
            merged.get("color"),
            merged.get("material"),
            merged.get("rgb"),
            merged.get("noise"),
        ]
        meaningful_count = sum(1 for v in meaningful_fields if v != "unknown")

        if meaningful_count >= 2:
            return "high"
        if meaningful_count == 1:
            return "medium"
        return "unknown"

    def detect_conflicts(self, merged: dict) -> list[str]:
        warnings = list(merged.get("conflicts_or_warnings", []))

        case_size = merged.get("case_size")
        case_style = merged.get("case_style")
        color = merged.get("color")
        rgb = merged.get("rgb")
        noise = merged.get("noise")

        if case_size in ["itx_compact", "compact_m_atx"] and case_style == "panoramic":
            warnings.append(
                "用户同时提出小机箱和海景房需求。海景房机箱通常不一定是最小体积，建议优先考虑紧凑型M-ATX海景房。"
            )

        if noise in ["silent", "low_noise"] and case_style == "airflow_mesh":
            warnings.append("用户同时关注静音和高风量散热，需要在散热和噪声之间平衡。")

        if case_style == "gaming" and rgb == "no_rgb":
            warnings.append("用户偏向电竞外观但排斥RGB，应选择无光电竞风或低调侧透方案。")

        if color == "white" and case_style == "panoramic":
            warnings.append("白色海景房可能存在外观溢价，后续价格模块需要考虑是否接受白色配件溢价。")

        return list(dict.fromkeys(warnings))

    def build_selection_constraints(
        self,
        merged: dict,
        conflicts_or_warnings: list[str],
    ) -> dict:
        constraints = {
            "case_size_class": merged.get("case_size", "unknown"),
            "allowed_motherboard_form_factors": merged.get("preferred_form_factor", []),
            "preferred_case_styles": [],
            "required_color": None,
            "required_material": None,
            "side_panel": None,
            "rgb_policy": merged.get("rgb", "unknown"),
            "noise_policy": merged.get("noise", "unknown"),
            "avoid_features": [],
            "must_check": [
                "case_motherboard_compatibility",
                "gpu_length_clearance",
                "cpu_cooler_height_clearance",
                "psu_form_factor",
                "case_airflow",
            ],
        }

        if merged.get("case_style") != "unknown":
            constraints["preferred_case_styles"].append(merged["case_style"])

        if merged.get("color") not in ["unknown", "no_preference"]:
            constraints["required_color"] = merged["color"]

        if merged.get("material") != "unknown":
            constraints["required_material"] = merged["material"]

        if merged.get("material") == "tempered_glass":
            constraints["side_panel"] = "tempered_glass"

        if merged.get("rgb") == "no_rgb":
            constraints["avoid_features"].extend(["rgb_fans", "rgb_memory", "rgb_cooler", "strong_rgb"])

        if merged.get("case_size") in ["itx_compact", "compact_m_atx"]:
            constraints["avoid_features"].append("oversized_case")

        constraints = self._deep_merge_dict(constraints, merged.get("constraints_for_selection_agent", {}))
        constraints["preferred_case_styles"] = list(dict.fromkeys(constraints.get("preferred_case_styles", [])))
        constraints["avoid_features"] = list(dict.fromkeys(constraints.get("avoid_features", [])))
        constraints["must_check"] = list(dict.fromkeys(constraints.get("must_check", [])))
        constraints["conflicts_or_warnings"] = conflicts_or_warnings
        return constraints

    def build_output(
        self,
        merged: dict,
        rule_matches: list[dict],
        conflicts_or_warnings: list[str],
        constraints_for_selection_agent: dict,
    ) -> AppearanceOutput:
        return AppearanceOutput(
            matched_keywords=merged.get("matched_keywords", []),
            case_size=merged.get("case_size", "unknown"),
            preferred_form_factor=merged.get("preferred_form_factor", []),
            case_style=merged.get("case_style", "unknown"),
            color=merged.get("color", "unknown"),
            material=merged.get("material", "unknown"),
            rgb=merged.get("rgb", "unknown"),
            noise=merged.get("noise", "unknown"),
            appearance_priority=merged.get("appearance_priority", "unknown"),
            compatibility_constraints=merged.get("compatibility_constraints", []),
            conflicts_or_warnings=conflicts_or_warnings,
            constraints_for_selection_agent=constraints_for_selection_agent,
            missing_information=merged.get("missing_information", []),
        )

    def apply_other_signals(self, appearance_result: dict, other_result: dict) -> dict:
        result = dict(appearance_result or {})
        signal_names = self._get_signal_names(other_result, "appearance_signals")
        if not signal_names:
            return result

        case_size = result.get("case_size", "unknown")
        preferred_form_factor = list(result.get("preferred_form_factor") or [])
        appearance_priority = result.get("appearance_priority", "unknown")
        noise = result.get("noise", "unknown")
        compatibility_constraints = list(result.get("compatibility_constraints") or [])
        warnings = list(result.get("conflicts_or_warnings") or [])

        if "compact_case_preferred" in signal_names:
            if case_size == "unknown":
                case_size = "compact_m_atx"
                preferred_form_factor = ["M-ATX", "Mini-ITX"]
            elif case_size == "large_atx":
                warnings.append("用户使用环境提示空间有限，但外观需求中出现大机箱倾向，需要确认空间约束是否优先。")

        if "low_noise_preferred" in signal_names:
            if noise in ["unknown", "normal"]:
                noise = "low_noise"
            compatibility_constraints.append("使用环境对噪声敏感，建议优先低噪风扇、低噪散热和合理风道。")

        if "desktop_case_size_preferred" in signal_names:
            if case_size == "unknown":
                case_size = "compact_m_atx"
                preferred_form_factor = ["M-ATX", "Mini-ITX"]
            if appearance_priority == "unknown":
                appearance_priority = "medium"
            compatibility_constraints.append("桌面摆放需要考虑机箱体积、接口可达性和外观协调。")

        result["case_size"] = case_size
        result["preferred_form_factor"] = list(dict.fromkeys(preferred_form_factor))
        result["appearance_priority"] = appearance_priority
        result["noise"] = noise
        result["compatibility_constraints"] = list(dict.fromkeys(compatibility_constraints))
        result["conflicts_or_warnings"] = list(dict.fromkeys(warnings))
        return result

    def _get_signal_names(self, other_result: dict, group: str) -> list[str]:
        other = other_result.get("other", other_result)
        signals = other.get("cross_module_signals", {}).get(group, [])
        return [s.get("signal") if isinstance(s, dict) else s for s in signals]

    def _deep_merge_dict(self, base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
        merged = dict(base)
        for key, value in extra.items():
            if key not in merged or merged[key] in (None, "", [], {}):
                merged[key] = value
                continue
            if isinstance(merged[key], list) and isinstance(value, list):
                merged[key] = list(dict.fromkeys([*merged[key], *value]))
                continue
            if isinstance(merged[key], dict) and isinstance(value, dict):
                merged[key] = self._deep_merge_dict(merged[key], value)
                continue
            merged[key] = merged[key]
        return merged

    @staticmethod
    def _model_to_dict(model: Any) -> dict[str, Any]:
        if hasattr(model, "model_dump"):
            return model.model_dump()
        return model.dict()
