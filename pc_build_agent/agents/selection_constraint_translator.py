from __future__ import annotations

import re
from typing import Any

from pc_build_agent.agents.flexible_text_signals import extract_component_specs
from pc_build_agent.schemas.requirement_profile_schema import SelectionContext, dedupe_list


TARGET_BUCKETS = {"must_satisfy", "prefer_satisfy", "avoid"}
REQUIRED_CONSTRAINT_KEYS = {"component", "field", "operator"}
CATEGORY_TO_COMPONENT = {
    "处理器": "cpu",
    "显卡": "gpu",
    "主板": "motherboard",
    "内存": "memory",
    "硬盘": "ssd",
    "机箱": "case",
    "散热": "cooling",
    "电源": "psu",
    "风扇": "fan",
    "显示器": "monitor",
}


class SelectionConstraintTranslator:
    def __init__(self, mapping: dict[str, Any] | None = None) -> None:
        self.mapping = mapping or {}
        self.rules = dict(self.mapping.get("rules") or {})
        self.prefix_rules = list(self.mapping.get("prefix_rules") or [])
        self.unknown_policy = dict(self.mapping.get("unknown_policy") or {})
        self.version = str(self.mapping.get("version") or "unknown")

    def compile_context(self, context: SelectionContext, profile: dict[str, Any] | None = None) -> SelectionContext:
        output: dict[str, list[Any]] = {
            "must_satisfy": [],
            "prefer_satisfy": [],
            "avoid": [],
        }
        warnings: list[dict[str, Any]] = []

        for bucket in TARGET_BUCKETS:
            for item in list(getattr(context, bucket) or []):
                self._compile_item(item=item, source_bucket=bucket, output=output, warnings=warnings)

        self._compile_cross_module_selection_signals(context, output, warnings)
        if profile:
            self._compile_explicit_user_requirements(profile, output)

        cross_module_signals = dict(context.cross_module_signals or {})
        cross_module_signals["selection_constraint_mapping_version"] = self.version
        if warnings:
            cross_module_signals["constraint_translation_warnings"] = warnings

        return SelectionContext(
            must_satisfy=dedupe_list(output["must_satisfy"]),
            prefer_satisfy=dedupe_list(output["prefer_satisfy"]),
            avoid=dedupe_list(output["avoid"]),
            protected_components=list(context.protected_components or []),
            cost_cut_components=list(context.cost_cut_components or []),
            budget_context=dict(context.budget_context or {}),
            compatibility_checks=list(context.compatibility_checks or []),
            cross_module_signals=cross_module_signals,
        )

    def _compile_cross_module_selection_signals(
        self,
        context: SelectionContext,
        output: dict[str, list[Any]],
        warnings: list[dict[str, Any]],
    ) -> None:
        signals = ((context.cross_module_signals or {}).get("selection_signals") or [])
        for item in signals:
            if not isinstance(item, dict):
                continue
            signal = str(item.get("signal") or "").strip()
            if not signal:
                continue
            rule = self.rules.get(signal)
            if not rule or "cross_module_signals.selection_signals" not in list(rule.get("source_buckets") or []):
                continue
            self._apply_rule(tag=signal, rule=rule, source_bucket="cross_module_signals.selection_signals", output=output, warnings=warnings)

    def _compile_explicit_user_requirements(self, profile: dict[str, Any], output: dict[str, list[Any]]) -> None:
        text = str(profile.get("original_user_text") or "")
        compact = re.sub(r"\s+", "", text.lower())
        lower = text.lower()
        appearance = dict(profile.get("appearance") or {})

        self._extract_gpu_constraints(text, lower, compact, output)
        self._extract_cpu_constraints(text, lower, compact, output)
        self._extract_memory_constraints(lower, output)
        self._extract_storage_constraints(lower, output)
        self._extract_motherboard_constraints(text, lower, output)
        self._extract_case_constraints(text, lower, compact, appearance, output)
        self._extract_psu_constraints(text, lower, output)
        self._extract_cooling_constraints(text, compact, output)
        self._extract_risk_avoidance_constraints(compact, output)
        self._extract_generic_component_specs(text, output)

    def _extract_generic_component_specs(self, text: str, output: dict[str, list[Any]]) -> None:
        for category, phrase in extract_component_specs(text).items():
            component = CATEGORY_TO_COMPONENT.get(category)
            if component and phrase:
                output["must_satisfy"].append({"component": component, "keyword": phrase})

    def _extract_gpu_constraints(self, text: str, lower: str, compact: str, output: dict[str, list[Any]]) -> None:
        for match in re.finditer(r"\b(RTX|GTX)\s*([0-9]{3,4})(?:\s*(SUPER|TI))?\b", text, re.I):
            keywords = [match.group(1).upper(), match.group(2)]
            if match.group(3):
                keywords.append(match.group(3).upper())
            output["must_satisfy"].append({"component": "gpu", "keywords": keywords})
        for match in re.finditer(r"\bRX\s*([0-9]{3,4})(?:\s*(XT|XTX))?\b", text, re.I):
            keywords = ["RX", match.group(1)]
            if match.group(2):
                keywords.append(match.group(2).upper())
            output["must_satisfy"].append({"component": "gpu", "keywords": keywords})
        for match in re.finditer(r"(\d{1,2})\s*(?:g|gb)\s*显存", lower, re.I):
            output["must_satisfy"].append({"component": "gpu", "field": "vram_gb", "operator": ">=", "value": int(match.group(1))})
        if any(token in compact for token in ["n卡", "英伟达", "nvidia", "geforce"]):
            output["must_satisfy"].append(
                {
                    "component": "gpu",
                    "field": "name",
                    "operator": "contains_any",
                    "value": ["NVIDIA", "英伟达", "GeForce", "RTX", "GTX"],
                }
            )
            output["avoid"].append(
                {
                    "component": "gpu",
                    "field": "name",
                    "operator": "contains_any",
                    "value": ["Intel Arc", "Arc ", "锐炫", "B580", "B570", "A770", "A750", "RX", "RADEON"],
                }
            )
        if any(token in compact for token in ["a卡", "amd显卡", "radeon显卡"]):
            output["must_satisfy"].append({"component": "gpu", "keywords": ["RX"]})

    def _extract_cpu_constraints(self, text: str, lower: str, compact: str, output: dict[str, list[Any]]) -> None:
        wants_intel_nvidia_platform = (
            any(token in compact for token in ["nvidia", "英伟达", "n卡", "geforce"])
            and any(token in compact for token in ["intel", "英特尔", "酷睿"])
            and not any(token in compact for token in ["intel显卡", "英特尔显卡", "intelarc", "锐炫"])
        )
        if wants_intel_nvidia_platform or any(token in compact for token in ["intelcpu", "intel处理器", "英特尔cpu", "英特尔处理器", "酷睿"]):
            output["must_satisfy"].append({"component": "cpu", "field": "brand", "operator": "contains", "value": "英特尔"})
        if any(token in compact for token in ["amdcpu", "amd处理器", "锐龙"]):
            output["must_satisfy"].append({"component": "cpu", "keywords": ["AMD"]})
        for match in re.finditer(r"\b(i[3579])[-\s]?([0-9]{4,5}[a-z]{0,3})\b", text, re.I):
            output["must_satisfy"].append({"component": "cpu", "keywords": [match.group(1), match.group(2)]})
        for match in re.finditer(r"\b([579][0-9]{3}x3d|[579][0-9]{3}x)\b", text, re.I):
            output["must_satisfy"].append({"component": "cpu", "keyword": match.group(1)})
        for match in re.finditer(r"(?:至少|不低于)?\s*(\d{1,2})\s*核", text):
            output["must_satisfy"].append({"component": "cpu", "field": "cores", "operator": ">=", "value": int(match.group(1))})
        if any(token in compact for token in ["不要独显", "不用独显", "核显办公", "只要核显"]):
            output["must_satisfy"].append({"component": "cpu", "field": "has_integrated_graphics", "operator": "==", "value": True})

    def _extract_memory_constraints(self, lower: str, output: dict[str, list[Any]]) -> None:
        for match in re.finditer(r"(\d{2,3})\s*(?:g|gb)(?:\s*ddr[45])?\s*内存", lower, re.I):
            output["must_satisfy"].append({"component": "memory", "field": "capacity_gb", "operator": ">=", "value": int(match.group(1))})
        for memory_type in ["DDR5", "DDR4"]:
            if memory_type.lower() in lower:
                output["must_satisfy"].append({"component": "memory", "field": "memory_type", "operator": "==", "value": memory_type})
                output["must_satisfy"].append({"component": "motherboard", "field": "memory_type", "operator": "==", "value": memory_type})

    def _extract_storage_constraints(self, lower: str, output: dict[str, list[Any]]) -> None:
        for match in re.finditer(r"(\d+(?:\.\d+)?)\s*(t|tb)\s*(?:固态|ssd|硬盘)", lower, re.I):
            output["must_satisfy"].append({"component": "ssd", "field": "capacity_gb", "operator": ">=", "value": int(float(match.group(1)) * 1000)})
        for match in re.finditer(r"(?:至少|不低于)\s*(\d+(?:\.\d+)?)\s*(t|tb)", lower, re.I):
            output["must_satisfy"].append({"component": "ssd", "field": "capacity_gb", "operator": ">=", "value": int(float(match.group(1)) * 1000)})

    def _extract_motherboard_constraints(self, text: str, lower: str, output: dict[str, list[Any]]) -> None:
        for socket in ["AM5", "AM4", "LGA1700", "LGA1851"]:
            if socket.lower() in lower:
                output["must_satisfy"].append({"component": "cpu", "field": "socket", "operator": "==", "value": socket})
                output["must_satisfy"].append({"component": "motherboard", "field": "socket", "operator": "==", "value": socket})
        if re.search(r"(itx|mini-?itx)\s*主板", lower, re.I):
            output["must_satisfy"].append({"component": "motherboard", "field": "form_factor", "operator": "contains_any", "value": ["ITX", "Mini-ITX"]})
        if re.search(r"(m-atx|matx|micro-?atx)\s*主板", lower, re.I):
            output["must_satisfy"].append({"component": "motherboard", "field": "form_factor", "operator": "contains_any", "value": ["M-ATX", "Micro-ATX"]})

    def _extract_case_constraints(self, text: str, lower: str, compact: str, appearance: dict[str, Any], output: dict[str, list[Any]]) -> None:
        if re.search(r"(白色|白)\s*(机箱|海景房)", text):
            output["must_satisfy"].append({"component": "case", "field": "color", "operator": "contains", "value": "白"})
        elif appearance.get("color") == "white":
            output["prefer_satisfy"].append({"component": "case", "field": "color", "operator": "contains", "value": "白"})
        if re.search(r"(黑色|黑)\s*机箱", text):
            output["must_satisfy"].append({"component": "case", "field": "color", "operator": "contains", "value": "黑"})
        if "海景房" in text:
            output["must_satisfy"].append({"component": "case", "field": "case_style", "operator": "contains", "value": "海景房"})
        elif appearance.get("case_style") == "panoramic":
            output["prefer_satisfy"].append({"component": "case", "field": "case_style", "operator": "contains", "value": "海景房"})
        if any(token in text for token in ["侧透", "玻璃侧透"]):
            output["prefer_satisfy"].append({"component": "case", "field": "case_style", "operator": "contains_any", "value": ["侧透", "玻璃"]})
        if re.search(r"(itx|mini-?itx)\s*机箱", lower, re.I):
            output["must_satisfy"].append({"component": "case", "field": "case_size_class", "operator": "contains_any", "value": ["itx", "sff", "迷你", "小型"]})
        if any(token in compact for token in ["支持长显卡", "长显卡", "升级显卡"]):
            output["must_satisfy"].append({"component": "case", "field": "max_gpu_length_mm", "operator": ">=", "value": 340})

    def _extract_psu_constraints(self, text: str, lower: str, output: dict[str, list[Any]]) -> None:
        for match in re.finditer(r"(\d{3,4})\s*w\s*(?:电源)?", lower, re.I):
            output["must_satisfy"].append({"component": "psu", "field": "wattage_w", "operator": ">=", "value": int(match.group(1))})
        if "金牌" in text:
            output["prefer_satisfy"].append({"component": "psu", "field": "efficiency_rating", "operator": "contains_any", "value": ["Gold", "金牌"]})
        if "白金牌" in text:
            output["prefer_satisfy"].append({"component": "psu", "field": "efficiency_rating", "operator": "contains_any", "value": ["Platinum", "白金"]})

    def _extract_cooling_constraints(self, text: str, compact: str, output: dict[str, list[Any]]) -> None:
        if "360水冷" in compact or "360一体水" in compact:
            output["must_satisfy"].append({"component": "cooling", "field": "cooling_type", "operator": "contains", "value": "水冷"})
            output["must_satisfy"].append({"component": "cooling", "field": "radiator_size_mm", "operator": ">=", "value": 360})
        elif "水冷" in text:
            output["must_satisfy"].append({"component": "cooling", "field": "cooling_type", "operator": "contains", "value": "水冷"})
        if "风冷" in text:
            output["must_satisfy"].append({"component": "cooling", "field": "cooling_type", "operator": "contains", "value": "风冷"})

    def _extract_risk_avoidance_constraints(self, compact: str, output: dict[str, list[Any]]) -> None:
        if any(token in compact for token in ["不要矿卡", "拒绝矿卡", "非矿卡"]):
            output["avoid"].append({"component": "gpu", "field": "name", "operator": "contains_any", "value": ["矿", "二手", "拆机"]})
        if any(token in compact for token in ["不要二手", "全新", "不接受二手"]):
            for component in ["cpu", "gpu", "motherboard", "memory", "ssd", "cooling", "psu", "case"]:
                output["avoid"].append({"component": component, "field": "name", "operator": "contains_any", "value": ["二手", "拆机", "矿"]})

    def _compile_item(
        self,
        item: Any,
        source_bucket: str,
        output: dict[str, list[Any]],
        warnings: list[dict[str, Any]],
    ) -> None:
        if isinstance(item, dict):
            if source_bucket == "must_satisfy" and not self._is_executable_constraint(item):
                output["prefer_satisfy"].append(item)
                warnings.append({"tag": item, "source_bucket": source_bucket, "action": "move_to_prefer_satisfy", "reason": "invalid_hard_constraint"})
                return
            output[source_bucket].append(item)
            return

        tag = str(item or "").strip()
        if not tag:
            return

        rule = self.rules.get(tag) or self._prefix_rule_for(tag, source_bucket)
        if rule and source_bucket in list(rule.get("source_buckets") or []):
            self._apply_rule(tag=tag, rule=rule, source_bucket=source_bucket, output=output, warnings=warnings)
            return

        self._apply_unknown_policy(tag, source_bucket, output, warnings)

    def _apply_rule(
        self,
        tag: str,
        rule: dict[str, Any],
        source_bucket: str,
        output: dict[str, list[Any]],
        warnings: list[dict[str, Any]],
    ) -> None:
        action = str(rule.get("action") or "keep")
        target_bucket = str(rule.get("target_bucket") or source_bucket)

        if action == "drop":
            warnings.append({"tag": tag, "source_bucket": source_bucket, "action": "drop", "reason": rule.get("reason")})
            return

        if action == "move_tag":
            if target_bucket in TARGET_BUCKETS:
                output[target_bucket].append(tag)
            return

        if action == "replace_with_constraints":
            constraints = [item for item in list(rule.get("constraints") or []) if self._is_executable_constraint(item)]
            if not constraints:
                self._apply_unknown_policy(tag, source_bucket, output, warnings, reason="mapping_has_no_executable_constraints")
                return
            if target_bucket not in TARGET_BUCKETS:
                self._apply_unknown_policy(tag, source_bucket, output, warnings, reason="mapping_has_invalid_target_bucket")
                return
            output[target_bucket].extend(constraints)
            return

        if source_bucket in TARGET_BUCKETS:
            output[source_bucket].append(tag)

    def _apply_unknown_policy(
        self,
        tag: str,
        source_bucket: str,
        output: dict[str, list[Any]],
        warnings: list[dict[str, Any]],
        reason: str = "unknown_semantic_constraint",
    ) -> None:
        policy = str(self.unknown_policy.get(source_bucket) or "keep")
        if source_bucket == "must_satisfy" and policy == "move_to_prefer_satisfy":
            output["prefer_satisfy"].append(tag)
            warnings.append({"tag": tag, "source_bucket": source_bucket, "action": "move_to_prefer_satisfy", "reason": reason})
            return
        if source_bucket in TARGET_BUCKETS:
            output[source_bucket].append(tag)

    def _prefix_rule_for(self, tag: str, source_bucket: str) -> dict[str, Any] | None:
        for rule in self.prefix_rules:
            if source_bucket not in list(rule.get("source_buckets") or []):
                continue
            prefix = str(rule.get("prefix") or "")
            if prefix and tag.startswith(prefix):
                return dict(rule)
        return None

    @staticmethod
    def _is_executable_constraint(item: Any) -> bool:
        if not isinstance(item, dict):
            return False
        if item.get("keyword") or item.get("keywords"):
            return bool(item.get("component") or item.get("component_type") or item.get("category"))
        return REQUIRED_CONSTRAINT_KEYS.issubset(item)
