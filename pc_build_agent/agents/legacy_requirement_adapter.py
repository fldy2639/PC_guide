from __future__ import annotations

from typing import Any

from pc_build_agent.models.schemas import ParsedRequirements, RequirementsModel


def _validate_model(model_cls: type[Any], data: Any) -> Any:
    if hasattr(model_cls, "model_validate"):
        return model_cls.model_validate(data)
    return model_cls.parse_obj(data)


class LegacyRequirementAdapter:
    @classmethod
    def from_requirement_profile(cls, profile_output: dict[str, Any]) -> ParsedRequirements:
        profile = dict((profile_output or {}).get("requirement_profile") or {})
        performance = dict(profile.get("performance") or {})
        appearance = dict(profile.get("appearance") or {})
        price = dict(profile.get("price") or {})
        other = dict(profile.get("other") or {})

        legacy_other = cls._build_legacy_other(other)
        need_monitor = legacy_other.get("need_monitor")

        requirements_payload = {
            "budget": cls._build_budget(price),
            "usage": cls._build_usage(performance),
            "performance": performance,
            "appearance": appearance,
            "price": price,
            "other": legacy_other,
            "display": {"need_monitor": need_monitor} if need_monitor is not None else {},
            "specified_parts": [],
            "brand_preferences": [],
            "avoid_preferences": [],
            "other_constraints": cls._build_other_constraints(legacy_other),
        }

        parsed = ParsedRequirements(
            need_clarification=False,
            clarification_question=None,
            missing_fields=list(profile.get("missing_information") or []),
            next_action=None,
            clarification_cards=[],
            requirements=_validate_model(RequirementsModel, requirements_payload),
            capability_profile=dict(profile.get("capability_profile") or {}),
            selection_context=dict(profile.get("selection_context") or {}),
            weights={"performance": 0.4, "price": 0.3, "appearance": 0.2, "other": 0.1},
            explanation="requirement_profile_adapter",
        )
        parsed.__dict__["requirement_profile"] = profile
        return parsed

    @classmethod
    def _build_budget(cls, price: dict[str, Any]) -> dict[str, Any]:
        extraction = dict(price.get("budget_extraction") or {})
        strictness = None
        if extraction.get("hard_limit") is True:
            strictness = "hard"
        elif extraction.get("budget_flexibility") in ["soft", "small_overspend", "flexible"]:
            strictness = "medium"
        return {
            "min": extraction.get("min_budget"),
            "max": extraction.get("max_budget"),
            "currency": "CNY",
            "strictness": strictness,
        }

    @classmethod
    def _build_usage(cls, performance: dict[str, Any]) -> list[str]:
        primary_usage_map = {
            "gaming": "游戏",
            "streaming": "直播",
            "study": "学习",
            "office": "办公",
            "design": "设计",
            "video_editing": "剪辑",
            "modeling": "建模",
            "ai": "AI",
            "scientific_computing": "科研计算",
        }
        secondary_usage_map = {
            "fps_esports": "电竞游戏",
            "aaa_gaming": "3A游戏",
            "game_streaming": "游戏直播",
            "local_llm_inference": "本地模型",
            "programming_development": "编程开发",
            "general_study": "学习",
            "general_office": "办公",
        }

        usage: list[str] = []
        for item in performance.get("matched_keywords") or []:
            if item and item not in usage:
                usage.append(item)
        for item in performance.get("secondary_usage") or []:
            label = secondary_usage_map.get(str(item), str(item))
            if label not in usage:
                usage.append(label)
        for item in performance.get("primary_usage") or []:
            label = primary_usage_map.get(str(item), str(item))
            if label not in usage:
                usage.append(label)
        return usage

    @classmethod
    def _build_legacy_other(cls, other: dict[str, Any]) -> dict[str, Any]:
        purchase_scope = dict(other.get("purchase_scope") or {})
        owned_parts = dict(other.get("owned_parts") or {})
        connectivity = dict(other.get("connectivity") or {})
        purchase_risk = dict(other.get("purchase_risk") or {})
        warranty_service = dict(other.get("warranty_service") or {})
        upgrade_plan = dict(other.get("upgrade_plan") or {})
        special_requirements = dict(other.get("special_requirements") or {})

        need_monitor = None
        if purchase_scope.get("include_monitor") is True:
            need_monitor = True
        elif purchase_scope.get("only_host") is True or purchase_scope.get("include_monitor") is False:
            need_monitor = False
        elif owned_parts.get("has_monitor") is True:
            need_monitor = False

        upgradeability_requirement = upgrade_plan.get("upgrade_priority")
        if upgradeability_requirement == "unknown":
            upgradeability_requirement = None

        return {
            "need_monitor": need_monitor,
            "has_monitor": owned_parts.get("has_monitor"),
            "resolution": None,
            "refresh_rate": None,
            "need_wifi": connectivity.get("need_wifi"),
            "need_bluetooth": connectivity.get("need_bluetooth"),
            "need_genuine_os": purchase_scope.get("include_os"),
            "accept_second_hand": purchase_risk.get("accept_used_parts"),
            "accept_tray_cpu": purchase_risk.get("accept_bulk_cpu"),
            "accept_overseas_version": None,
            "need_full_system_warranty": warranty_service.get("need_warranty") or warranty_service.get("prefer_full_machine_warranty"),
            "upgradeability_requirement": upgradeability_requirement,
            "storage_capacity_requirement": special_requirements.get("storage_capacity_requirement"),
        }

    @classmethod
    def _build_other_constraints(cls, legacy_other: dict[str, Any]) -> list[str]:
        constraints: list[str] = []
        for key in [
            "need_wifi",
            "need_bluetooth",
            "need_genuine_os",
            "accept_second_hand",
            "accept_tray_cpu",
            "accept_overseas_version",
            "need_full_system_warranty",
            "upgradeability_requirement",
        ]:
            value = legacy_other.get(key)
            if value not in (None, "", False):
                constraints.append(f"{key}={value}")
        return constraints
