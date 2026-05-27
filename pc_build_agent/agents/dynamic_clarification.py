from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pc_build_agent.agents.flexible_text_signals import extract_component_specs, profile_text
from pc_build_agent.models.schemas import ClarificationCard, ClarificationCardOption, ParsedRequirements


@dataclass
class ClarificationDecision:
    need_clarification: bool = False
    question: str | None = None
    missing_fields: list[str] = field(default_factory=list)
    cards: list[ClarificationCard] = field(default_factory=list)


class DynamicClarificationAgent:
    """Decides when the API should pause for a quick follow-up instead of forcing a weak build."""

    BYPASS_TOKENS = [
        "先给方案",
        "先推荐",
        "不用追问",
        "别追问",
        "直接给",
        "继续生成",
        "按默认",
    ]
    NO_APPEARANCE_PREFERENCE_TOKENS = [
        "外观随意",
        "外观无所谓",
        "外观不重要",
        "外观都行",
        "外观默认",
        "颜值无所谓",
        "颜值不重要",
    ]
    APPEARANCE_SIGNAL_TOKENS = [
        "外观",
        "颜值",
        "机箱",
        "白色",
        "黑色",
        "海景房",
        "rgb",
        "RGB",
        "灯效",
        "无光",
        "简洁",
        "简约",
        "低调",
        "小主机",
        "itx",
        "ITX",
        "静音",
        "安静",
    ]

    def evaluate(self, parsed: ParsedRequirements, transcript: str = "") -> ClarificationDecision:
        latest = self._latest_user_utterance(transcript)
        if any(token in latest for token in self.BYPASS_TOKENS):
            return ClarificationDecision()

        conflict = self._blocking_conflict(parsed)
        if conflict:
            return ClarificationDecision(
                need_clarification=True,
                question=conflict["question"],
                missing_fields=[conflict["field"]],
                cards=[conflict["card"]],
            )

        missing: list[str] = []
        cards: list[ClarificationCard] = []

        if not self._has_budget(parsed):
            missing.append("预算范围")
            cards.append(
                self._card(
                    "budget_range",
                    "预算范围",
                    [
                        ("预算 4000-6000 元", "4000-6000 元"),
                        ("预算 6000-8000 元", "6000-8000 元"),
                        ("预算 8000-12000 元", "8000-12000 元"),
                        ("预算 12000 元以上", "12000 元以上"),
                    ],
                )
            )

        if not self._has_usage(parsed) and not (self._has_budget(parsed) and self._has_actionable_specs(parsed, latest)):
            missing.append("主要用途")
            cards.append(
                self._card(
                    "primary_usage",
                    "主要用途",
                    [
                        ("主要玩 3A / 电竞游戏", "3A / 电竞游戏"),
                        ("主要剪辑、渲染或 AI", "剪辑 / 渲染 / AI"),
                        ("主要办公、学习或编程", "办公 / 学习 / 编程"),
                    ],
                )
            )

        if not self._has_appearance(parsed, latest):
            missing.append("外观偏好")
            cards.append(
                self._card(
                    "appearance_preference",
                    "外观偏好",
                    [
                        ("外观无所谓，优先兼容和散热", "外观无所谓"),
                        ("简洁低调，不要明显灯光", "简洁低调"),
                        ("白色海景房，适当 RGB", "白色海景房"),
                    ],
                )
            )

        if not missing:
            return ClarificationDecision()

        question = self._question_for(missing)
        return ClarificationDecision(
            need_clarification=True,
            question=question,
            missing_fields=missing,
            cards=cards[:3],
        )

    def _has_budget(self, parsed: ParsedRequirements) -> bool:
        budget = parsed.requirements.budget
        if budget and (budget.min is not None or budget.max is not None):
            return True
        price = dict(parsed.requirements.price or {})
        extraction = dict(price.get("budget_extraction") or {})
        return any(extraction.get(key) is not None for key in ["min_budget", "max_budget", "target_budget"])

    def _has_usage(self, parsed: ParsedRequirements) -> bool:
        if parsed.requirements.usage:
            return True
        performance = dict(parsed.requirements.performance or {})
        return bool(
            performance.get("primary_usage")
            or performance.get("secondary_usage")
            or performance.get("matched_keywords")
        )

    def _has_actionable_specs(self, parsed: ParsedRequirements, latest: str) -> bool:
        if getattr(parsed.requirements, "specified_parts", None):
            return True
        profile = getattr(parsed, "requirement_profile", None)
        if not isinstance(profile, dict):
            profile = parsed.__dict__.get("requirement_profile", {})
        specified_parts = list((profile or {}).get("specified_parts") or [])
        if specified_parts:
            return True
        text = " ".join([profile_text(profile or {}), latest]).strip()
        return bool(extract_component_specs(text))

    def _has_appearance(self, parsed: ParsedRequirements, latest: str) -> bool:
        if any(token in latest for token in self.NO_APPEARANCE_PREFERENCE_TOKENS):
            return True
        if any(token in latest for token in self.APPEARANCE_SIGNAL_TOKENS):
            return True

        profile = getattr(parsed, "requirement_profile", None)
        if not isinstance(profile, dict):
            profile = parsed.__dict__.get("requirement_profile", {})

        appearance = {}
        appearance.update(dict(parsed.requirements.appearance or {}))
        appearance.update(dict((profile or {}).get("appearance") or {}))

        meaningful_keys = [
            "case_size",
            "size",
            "case_style",
            "style",
            "color",
            "material",
            "rgb",
            "rgb_preference",
            "noise",
            "noise_preference",
            "appearance_priority",
        ]
        for key in meaningful_keys:
            value = appearance.get(key)
            if self._is_meaningful_appearance_value(value):
                return True
        return bool(appearance.get("matched_keywords"))

    def _is_meaningful_appearance_value(self, value: Any) -> bool:
        if value in (None, "", [], {}):
            return False
        if isinstance(value, str):
            return value.strip().lower() not in {"unknown", "未知", "null", "none"}
        return True

    def _blocking_conflict(self, parsed: ParsedRequirements) -> dict[str, Any] | None:
        profile = getattr(parsed, "requirement_profile", None)
        if not isinstance(profile, dict):
            profile = parsed.__dict__.get("requirement_profile", {})
        selection_context = dict((profile or {}).get("selection_context") or {})
        signals = dict(selection_context.get("cross_module_signals") or {})
        conflicts = list(signals.get("conflict_warnings") or [])
        if not any(item.get("rule_id") == "host_only_vs_include_monitor" for item in conflicts if isinstance(item, dict)):
            return None
        return {
            "field": "预算是否包含显示器",
            "question": "我看到你同时提到“只要主机”和“包含显示器”。这次预算到底按哪种口径算？",
            "card": self._card(
                "budget_scope",
                "预算口径",
                [
                    ("只配主机，不含显示器", "只配主机"),
                    ("预算包含显示器", "包含显示器"),
                    ("我已有显示器和键鼠", "已有显示器和键鼠"),
                ],
            ),
        }

    def _question_for(self, missing: list[str]) -> str:
        if len(missing) == 1:
            return f"为了更快给到靠谱方案，我还需要确认：{missing[0]}。"
        return "为了更快给到靠谱方案，我还需要确认：" + "、".join(missing[:2]) + "。"

    def _card(self, card_id: str, title: str, options: list[tuple[str, str]]) -> ClarificationCard:
        return ClarificationCard(
            id=card_id,
            title=title,
            multi_select=False,
            options=[ClarificationCardOption(value=value, label=label) for value, label in options],
        )

    def _latest_user_utterance(self, transcript: str) -> str:
        lines = [line.strip() for line in str(transcript or "").splitlines() if line.strip()]
        for line in reversed(lines):
            if line.startswith("用户："):
                return line.split("用户：", 1)[1].strip()
        return str(transcript or "").strip()
