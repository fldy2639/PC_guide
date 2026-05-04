from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pc_build_agent.prompts.performance_prompts import PERFORMANCE_EXTRACTION_PROMPT, PERFORMANCE_SUMMARY_PROMPT
from pc_build_agent.schemas.performance_schema import (
    ComponentPriorityItem,
    PerformanceAgentOutput,
    PerformanceLlmExtraction,
    PerformanceOutput,
    PerformanceRule,
)

if TYPE_CHECKING:
    from pc_build_agent.services.deepseek_client import DeepSeekClient


PRIMARY_USAGE_MAP = {
    "游戏": "gaming",
    "直播": "streaming",
    "学习": "study",
    "办公": "office",
    "设计": "design",
    "剪辑": "video_editing",
    "建模": "modeling",
    "AI": "ai",
    "科研计算": "scientific_computing",
}

COMPONENT_DISPLAY_NAMES = {
    "cpu_single_core": "CPU单核性能",
    "cpu_multi_core": "CPU多核性能",
    "gpu": "显卡性能",
    "gpu_encoding": "显卡编码能力",
    "vram": "显存",
    "ram": "内存",
    "ssd": "固态硬盘",
    "cooling": "散热",
    "psu": "电源",
    "motherboard": "主板",
    "network": "网络",
}

REASON_TEMPLATES = {
    "cpu_single_core": "该需求强调高帧率、低延迟或软件响应速度，因此CPU单核性能重要。",
    "cpu_multi_core": "该需求涉及多任务、编译、剪辑、仿真或训练，因此CPU多核性能重要。",
    "gpu": "该需求涉及3A游戏、图形渲染、视频加速或AI计算，因此显卡性能重要。",
    "gpu_encoding": "该需求涉及直播、录制或推流，因此显卡编码能力重要。",
    "vram": "该需求涉及高分辨率画质、AI模型、渲染或大型素材，因此显存容量重要。",
    "ram": "该需求涉及多任务、开发环境、剪辑、建模或模型运行，因此内存容量重要。",
    "ssd": "该需求涉及系统响应、游戏加载、素材读取或模型文件存储，因此SSD容量和速度重要。",
    "cooling": "该需求涉及长时间高负载运行，因此散热会影响性能释放和稳定性。",
    "psu": "该需求涉及独立显卡或高负载硬件，因此电源稳定性和功率余量重要。",
    "motherboard": "该需求涉及扩展能力、接口数量或平台稳定性，因此主板需要满足基本扩展要求。",
    "network": "该需求涉及在线游戏、直播、会议或云服务，因此网络稳定性重要。",
}

DEFAULT_WEIGHT = 0.8
STRENGTH_WEIGHT = {"strong": 1.0, "medium": 0.6, "weak": 0.3}
CLAUSE_PATTERNS = re.compile(r"[，,。；;！!？?\n]+")
TARGET_PATTERNS = {
    "resolution": re.compile(r"\b(1080p|2k|4k|8k)\b", re.I),
    "fps": re.compile(r"\b(60hz|75hz|120hz|144hz|165hz|180hz|240hz|300hz|360hz|60帧|120帧|144帧|240帧)\b", re.I),
    "quality": re.compile(r"(高画质|全高画质|极致画质|画质拉满|最高画质|光追)", re.I),
}


class PerformanceRequirementAgent:
    def __init__(self, rule_path: str | Path | None = None, llm: "DeepSeekClient" | None = None):
        default_rule_path = Path(__file__).resolve().parents[1] / "rules" / "performance_rules.json"
        self.rule_path = Path(rule_path or default_rule_path)
        self.rules = self.load_rules(self.rule_path)
        self.llm = llm

    @staticmethod
    def normalize_text(text: str) -> str:
        text = text.strip().lower()
        text = text.replace("，", ",").replace("。", ".")
        return text

    @staticmethod
    def _compact(text: str) -> str:
        return re.sub(r"\s+", "", text.lower())

    def load_rules(self, rule_path: Path) -> list[PerformanceRule]:
        raw = json.loads(rule_path.read_text(encoding="utf-8"))
        return [self._validate_model(PerformanceRule, item) for item in raw]

    def _keyword_hit(self, normalized_text: str, compact_text: str, keyword: str) -> bool:
        normalized_keyword = keyword.lower()
        compact_keyword = self._compact(keyword)
        return normalized_keyword in normalized_text or compact_keyword in compact_text

    def _split_clauses(self, user_text: str) -> list[str]:
        clauses = [part.strip() for part in CLAUSE_PATTERNS.split(user_text) if part.strip()]
        return clauses or [user_text.strip()]

    def _clause_weight(self, clause: str) -> tuple[str, float]:
        normalized = clause.lower()
        strong_markers = ["主要", "经常", "核心", "必须", "重点", "天天", "专门", "就是为了"]
        medium_markers = ["也会", "还会", "兼顾", "有时候", "同时"]
        weak_markers = ["偶尔", "可能", "轻度", "顺便", "不常用"]
        if any(marker in normalized for marker in strong_markers):
            return "strong", STRENGTH_WEIGHT["strong"]
        if any(marker in normalized for marker in weak_markers):
            return "weak", STRENGTH_WEIGHT["weak"]
        if any(marker in normalized for marker in medium_markers):
            return "medium", STRENGTH_WEIGHT["medium"]
        return "default", DEFAULT_WEIGHT

    def _rule_strength(self, user_text: str, rule: PerformanceRule, hit_keywords: list[str]) -> tuple[str, float]:
        best_label: str | None = None
        best_weight: float | None = None
        for clause in self._split_clauses(user_text):
            normalized_clause = clause.lower()
            compact_clause = self._compact(clause)
            if any(self._keyword_hit(normalized_clause, compact_clause, keyword) for keyword in hit_keywords):
                label, weight = self._clause_weight(clause)
                if best_weight is None or weight > best_weight:
                    best_label, best_weight = label, weight
        return best_label or "default", best_weight if best_weight is not None else DEFAULT_WEIGHT

    def match_rules(self, user_text: str) -> list[dict[str, Any]]:
        normalized_text = self.normalize_text(user_text)
        compact_text = self._compact(user_text)
        matches: list[dict[str, Any]] = []
        for rule in self.rules:
            hit_keywords = [keyword for keyword in rule.keywords if self._keyword_hit(normalized_text, compact_text, keyword)]
            if not hit_keywords:
                continue
            strength_label, strength_weight = self._rule_strength(user_text, rule, hit_keywords)
            matches.append(
                {
                    "rule": rule,
                    "hit_keywords": hit_keywords,
                    "strength_label": strength_label,
                    "strength_weight": strength_weight,
                }
            )
        return matches

    def extract_with_llm(self, user_text: str) -> PerformanceLlmExtraction | None:
        if not self.llm or not self.llm.api_key:
            return None
        prompt = PERFORMANCE_EXTRACTION_PROMPT.replace("{user_text}", user_text)
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_text},
        ]
        raw = self.llm.chat_json(messages, step="performance_extraction")
        return self._validate_model(PerformanceLlmExtraction, raw)

    def _merge_with_llm(self, rule_matches: list[dict[str, Any]], llm_extraction: PerformanceLlmExtraction | None) -> list[dict[str, Any]]:
        if not llm_extraction:
            return rule_matches

        normalized_tags = {match["rule"].normalized_tag for match in rule_matches}
        for item in llm_extraction.demand_strength:
            normalized_tags.add(item.keyword_or_usage)

        augmented = list(rule_matches)
        for rule in self.rules:
            if rule.normalized_tag not in set(llm_extraction.inferred_secondary_usage or []):
                continue
            if any(existing["rule"].rule_id == rule.rule_id for existing in augmented):
                continue
            weight = DEFAULT_WEIGHT
            label = "default"
            for strength in llm_extraction.demand_strength:
                if strength.keyword_or_usage == rule.normalized_tag:
                    label = strength.strength
                    weight = STRENGTH_WEIGHT.get(label, DEFAULT_WEIGHT)
                    break
            augmented.append(
                {
                    "rule": rule,
                    "hit_keywords": [],
                    "strength_label": label,
                    "strength_weight": weight,
                }
            )
        return augmented

    def calculate_component_scores(self, matches: list[dict[str, Any]]) -> dict[str, float]:
        scores: dict[str, float] = {}
        for match in matches:
            rule: PerformanceRule = match["rule"]
            weight = float(match["strength_weight"])
            for component, base_score in rule.component_scores.items():
                scores[component] = scores.get(component, 0.0) + float(base_score) * weight
        return scores

    def rank_components(self, component_scores: dict[str, float]) -> list[ComponentPriorityItem]:
        ordered = sorted(component_scores.items(), key=lambda item: (-item[1], item[0]))
        result: list[ComponentPriorityItem] = []
        for index, (component, score) in enumerate(ordered, start=1):
            result.append(
                ComponentPriorityItem(
                    component=component,
                    importance=index,
                    score=round(score, 2),
                    reason=REASON_TEMPLATES.get(component, f"{COMPONENT_DISPLAY_NAMES.get(component, component)}需要重点考虑。"),
                )
            )
        return result

    @staticmethod
    def score_to_constraint(score: float) -> str:
        if score >= 5.0:
            return "高优先级"
        if score >= 3.5:
            return "中高优先级"
        if score >= 2.0:
            return "中优先级"
        if score >= 1.0:
            return "低优先级"
        return "非核心"

    def _extract_targets(self, user_text: str, llm_extraction: PerformanceLlmExtraction | None) -> dict[str, Any]:
        targets = {"resolution": None, "fps": None, "quality": None, "software_scale": None}
        normalized = user_text.lower()
        for key, pattern in TARGET_PATTERNS.items():
            match = pattern.search(normalized)
            if match:
                targets[key] = match.group(1)
        if llm_extraction:
            for key, value in (llm_extraction.performance_targets or {}).items():
                if targets.get(key) in (None, "") and value not in (None, ""):
                    targets[key] = value
        return targets

    def _build_missing_information(
        self,
        matches: list[dict[str, Any]],
        targets: dict[str, Any],
        llm_extraction: PerformanceLlmExtraction | None,
    ) -> list[str]:
        missing: list[str] = []
        tags = {match["rule"].normalized_tag for match in matches}
        primary = {match["rule"].primary_category for match in matches}
        if "游戏" in primary and not targets.get("resolution"):
            missing.append("目标分辨率")
        if "fps_esports" in tags and not targets.get("fps"):
            missing.append("目标帧率")
        if ("aaa_gaming" in tags or "high_quality_ray_tracing" in tags) and not targets.get("quality"):
            missing.append("目标画质")
        if llm_extraction:
            for item in llm_extraction.missing_information:
                if item and item not in missing:
                    missing.append(item)
        return missing

    def _build_summary(self, output: PerformanceOutput) -> str:
        if self.llm and self.llm.api_key:
            output_json = json.dumps(self._model_to_dict(output), ensure_ascii=False)
            messages = [
                {"role": "system", "content": PERFORMANCE_SUMMARY_PROMPT.format(structured_result=output_json)},
                {"role": "user", "content": output_json},
            ]
            try:
                summary = self.llm.chat_text(messages, temperature=0.2, step="performance_summary")
                if summary:
                    return summary[:80]
            except Exception:
                pass

        focus = "、".join(output.performance_focus[:4]) if output.performance_focus else "性能均衡"
        primary = "、".join(output.primary_usage[:2]) if output.primary_usage else "综合使用"
        secondary = "、".join(output.secondary_usage[:3])
        if secondary:
            return f"用户主要关注{primary}，细分场景包括{secondary}，性能重点是{focus}。"
        return f"用户主要关注{primary}，性能重点是{focus}。"

    def analyze(self, user_text: str) -> dict[str, Any]:
        rule_matches = self.match_rules(user_text)
        llm_extraction = self.extract_with_llm(user_text)
        matches = self._merge_with_llm(rule_matches, llm_extraction)
        component_scores = self.calculate_component_scores(matches)
        component_priority = self.rank_components(component_scores)

        matched_keywords: list[str] = []
        performance_focus: list[str] = []
        primary_usage: list[str] = []
        secondary_usage: list[str] = []
        for match in matches:
            rule: PerformanceRule = match["rule"]
            for keyword in match["hit_keywords"]:
                if keyword not in matched_keywords:
                    matched_keywords.append(keyword)
            if rule.primary_category:
                usage = PRIMARY_USAGE_MAP.get(rule.primary_category, rule.primary_category)
                if usage not in primary_usage:
                    primary_usage.append(usage)
            if rule.normalized_tag and rule.normalized_tag not in secondary_usage:
                secondary_usage.append(rule.normalized_tag)
            for focus in rule.performance_focus:
                if focus not in performance_focus:
                    performance_focus.append(focus)

        targets = self._extract_targets(user_text, llm_extraction)
        missing_information = self._build_missing_information(matches, targets, llm_extraction)
        hardware_constraints = {
            item.component: self.score_to_constraint(item.score)
            for item in component_priority
        }
        output = PerformanceOutput(
            matched_keywords=matched_keywords,
            primary_usage=primary_usage,
            secondary_usage=secondary_usage,
            performance_focus=performance_focus,
            component_priority=component_priority,
            hardware_constraints=hardware_constraints,
            missing_information=missing_information,
            performance_targets=targets,
        )
        output.performance_summary = self._build_summary(output)
        return self._model_to_dict(PerformanceAgentOutput(performance=output))

    def apply_other_signals(self, performance_result: dict[str, Any], other_result: dict[str, Any]) -> dict[str, Any]:
        result = dict(performance_result or {})
        signal_names = self._get_signal_names(other_result, "performance_signals")
        if not signal_names:
            return result

        performance_focus = list(result.get("performance_focus") or [])
        hardware_constraints = dict(result.get("hardware_constraints") or {})
        extra_constraints = list(result.get("extra_performance_constraints") or [])
        missing_information = list(result.get("missing_information") or [])
        warnings = list(result.get("warnings") or [])
        component_priority = list(result.get("component_priority") or [])

        if "multi_monitor_display_output_required" in signal_names:
            for item in ["多显示器输出", "高分辨率显示稳定性"]:
                if item not in performance_focus:
                    performance_focus.append(item)
            if "display_output" not in hardware_constraints:
                hardware_constraints["display_output"] = "需要检查核显、主板或显卡显示输出能力"
            if "multi_monitor_display_output_required" not in extra_constraints:
                extra_constraints.append("multi_monitor_display_output_required")

        if "large_storage_required" in signal_names:
            if "大容量存储" not in performance_focus:
                performance_focus.append("大容量存储")
            if "storage_capacity" not in hardware_constraints:
                hardware_constraints["storage_capacity"] = "2TB_or_more"
            if not self._raise_component_priority(component_priority, "ssd"):
                if "large_storage_required" not in extra_constraints:
                    extra_constraints.append("large_storage_required")

        if "wireless_network_stability_required" in signal_names:
            scenarios = set(result.get("primary_usage") or []) | set(result.get("secondary_usage") or [])
            if scenarios.intersection({"gaming", "streaming", "fps_esports", "game_streaming"}):
                for item in ["无线网络稳定性", "低延迟连接"]:
                    if item not in performance_focus:
                        performance_focus.append(item)
                hardware_constraints["network"] = "需要稳定WiFi或有线网络条件"
                if not self._raise_component_priority(component_priority, "network"):
                    if "wireless_network_stability_required" not in extra_constraints:
                        extra_constraints.append("wireless_network_stability_required")

        result["performance_focus"] = list(dict.fromkeys(performance_focus))
        result["hardware_constraints"] = hardware_constraints
        result["extra_performance_constraints"] = list(dict.fromkeys(extra_constraints))
        result["missing_information"] = list(dict.fromkeys(missing_information))
        result["warnings"] = list(dict.fromkeys(warnings))
        result["component_priority"] = component_priority
        return result

    def _get_signal_names(self, other_result: dict[str, Any], group: str) -> list[str]:
        other = other_result.get("other", other_result)
        signals = other.get("cross_module_signals", {}).get(group, [])
        return [s.get("signal") if isinstance(s, dict) else s for s in signals]

    def _raise_component_priority(self, component_priority: list[Any], component_name: str) -> bool:
        if not component_priority:
            return False

        index = None
        for i, item in enumerate(component_priority):
            if isinstance(item, dict) and item.get("component") == component_name:
                index = i
                break
            if hasattr(item, "component") and getattr(item, "component") == component_name:
                index = i
                break

        if index is None:
            return False
        if index == 0:
            return True

        component_priority[index - 1], component_priority[index] = component_priority[index], component_priority[index - 1]
        for pos, item in enumerate(component_priority, start=1):
            if isinstance(item, dict):
                item["importance"] = pos
            elif hasattr(item, "importance"):
                setattr(item, "importance", pos)
        return True

    @staticmethod
    def _model_to_dict(model: Any) -> dict[str, Any]:
        if hasattr(model, "model_dump"):
            return model.model_dump()
        return model.dict()

    @staticmethod
    def _validate_model(model_cls: type[Any], data: Any) -> Any:
        if hasattr(model_cls, "model_validate"):
            return model_cls.model_validate(data)
        return model_cls.parse_obj(data)
