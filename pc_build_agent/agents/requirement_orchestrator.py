from __future__ import annotations

from typing import Any

from pc_build_agent.schemas.requirement_profile_schema import (
    RequirementProfile,
    RequirementProfileOutput,
    SelectionContext,
    dedupe_list,
    dump_model,
)
from pc_build_agent.agents.selection_constraint_translator import SelectionConstraintTranslator
from pc_build_agent.services.requirement_knowledge_repository import RequirementKnowledgeRepository


class RequirementOrchestrator:
    def __init__(
        self,
        performance_agent: Any,
        appearance_agent: Any,
        price_agent: Any,
        other_agent: Any,
        knowledge_repo: RequirementKnowledgeRepository | None = None,
    ):
        self.performance_agent = performance_agent
        self.appearance_agent = appearance_agent
        self.price_agent = price_agent
        self.other_agent = other_agent
        self.knowledge_repo = knowledge_repo or RequirementKnowledgeRepository()
        self.selection_constraint_translator = SelectionConstraintTranslator(
            self.knowledge_repo.get_selection_constraint_mapping()
        )

    def analyze(self, user_text: str) -> dict:
        performance = self.performance_agent.analyze(user_text)
        appearance = self.appearance_agent.analyze(user_text)
        other = self.other_agent.analyze(user_text)
        budget_extraction = self.price_agent.extract_budget(user_text)

        performance_data = self.unwrap(performance, "performance")
        appearance_data = self.unwrap(appearance, "appearance")

        if hasattr(self.performance_agent, "apply_other_signals"):
            performance_data = self.performance_agent.apply_other_signals(
                performance_result=performance_data,
                other_result=other,
            )

        if hasattr(self.appearance_agent, "apply_other_signals"):
            appearance_data = self.appearance_agent.apply_other_signals(
                appearance_result=appearance_data,
                other_result=other,
            )

        price = self.price_agent.analyze(
            user_text=user_text,
            performance_result=performance_data,
            appearance_result=appearance_data,
            other_result=other,
            budget_extraction=budget_extraction,
        )

        conflict_warnings = self._evaluate_conflict_rules(
            user_text=user_text,
            performance=performance_data,
            appearance=appearance_data,
            price=self.unwrap(price, "price"),
            other=self.unwrap(other, "other"),
        )

        return self.build_requirement_profile(
            user_text=user_text,
            performance={"performance": performance_data},
            appearance={"appearance": appearance_data},
            price=price,
            other=other,
            conflict_warnings=conflict_warnings,
        )

    def unwrap(self, result: dict, key: str) -> dict:
        return result.get(key, result)

    def build_requirement_profile(
        self,
        user_text: str,
        performance: dict,
        appearance: dict,
        price: dict,
        other: dict,
        conflict_warnings: list[dict[str, Any]] | None = None,
    ) -> dict:
        performance_data = self.unwrap(performance, "performance")
        appearance_data = self.unwrap(appearance, "appearance")
        price_data = self.unwrap(price, "price")
        other_data = self.unwrap(other, "other")
        conflict_warnings = list(conflict_warnings or [])
        if conflict_warnings:
            performance_warnings = list(performance_data.get("warnings") or [])
            appearance_warnings = list(appearance_data.get("conflicts_or_warnings") or [])
            price_risk_flags = list((price_data.get("budget_pressure") or {}).get("risk_flags") or [])
            for item in conflict_warnings:
                message = str(item.get("message") or "")
                if message and message not in performance_warnings:
                    performance_warnings.append(message)
                if message and message not in appearance_warnings:
                    appearance_warnings.append(message)
                flag = f"conflict:{item.get('rule_id')}"
                if flag not in price_risk_flags:
                    price_risk_flags.append(flag)
            performance_data["warnings"] = performance_warnings
            appearance_data["conflicts_or_warnings"] = appearance_warnings
            price_data.setdefault("budget_pressure", {})
            price_data["budget_pressure"]["risk_flags"] = price_risk_flags

        profile = RequirementProfile(
            original_user_text=user_text,
            performance=performance_data,
            appearance=appearance_data,
            price=price_data,
            other=other_data,
            capability_profile=self.build_capability_profile(
                performance_data,
                appearance_data,
                price_data,
                other_data,
                user_text=user_text,
            ),
            selection_context=self.build_selection_context(
                performance_data,
                appearance_data,
                price_data,
                other_data,
                conflict_warnings=conflict_warnings,
                user_text=user_text,
            ),
            missing_information=self.merge_missing_information(
                performance_data,
                appearance_data,
                price_data,
                other_data,
            ),
        )
        return dump_model(RequirementProfileOutput(requirement_profile=profile))

    def build_selection_context(
        self,
        performance: dict,
        appearance: dict,
        price: dict,
        other: dict,
        conflict_warnings: list[dict[str, Any]] | None = None,
        user_text: str = "",
    ) -> SelectionContext:
        price_ctx = price.get("selection_context_for_parts_agent", {})
        other_ctx = other.get("constraints_for_selection_agent", {})
        appearance_ctx = appearance.get("constraints_for_selection_agent", {})
        performance_ctx = performance.get("constraints_for_selection_agent", {})

        must_satisfy: list[Any] = []
        must_satisfy += price_ctx.get("must_satisfy", [])
        must_satisfy += other_ctx.get("must_have_features", [])
        must_satisfy += performance_ctx.get("must_have_features", [])

        prefer_satisfy: list[Any] = []
        prefer_satisfy += price_ctx.get("prefer_satisfy", [])
        prefer_satisfy += other_ctx.get("prefer_features", [])
        prefer_satisfy += appearance_ctx.get("prefer_features", [])

        avoid: list[Any] = []
        avoid += price_ctx.get("avoid", [])
        avoid += other_ctx.get("avoid_features", [])
        avoid += appearance_ctx.get("avoid_features", [])

        protected_components = price_ctx.get("protected_components", [])
        cost_cut_components = price_ctx.get("cost_cut_components", [])

        budget_context = {
            "total_budget": price_ctx.get("total_budget", {}),
            "budget_scope": price.get("budget_scope", {}),
            "budget_pressure": price.get("budget_pressure", {}),
        }

        compatibility_checks: list[str] = []
        compatibility_checks += price_ctx.get("required_compatibility_checks", [])
        compatibility_checks += other_ctx.get("compatibility_checks", [])
        compatibility_checks += appearance_ctx.get("must_check", [])
        compatibility_checks += performance_ctx.get("compatibility_checks", [])

        cross_module_signals = dict(other.get("cross_module_signals", {}) or {})
        if conflict_warnings:
            cross_module_signals["conflict_warnings"] = conflict_warnings

        return self.normalize_selection_context(
            SelectionContext(
                must_satisfy=dedupe_list(must_satisfy),
                prefer_satisfy=dedupe_list(prefer_satisfy),
                avoid=dedupe_list(avoid),
                protected_components=dedupe_list(protected_components),
                cost_cut_components=dedupe_list(cost_cut_components),
                budget_context=budget_context,
                compatibility_checks=dedupe_list(compatibility_checks),
                cross_module_signals=cross_module_signals,
            ),
            {
                "original_user_text": user_text,
                "performance": performance,
                "appearance": appearance,
                "price": price,
                "other": other,
            },
        )

    def normalize_selection_context(self, context: SelectionContext, profile: dict[str, Any] | None = None) -> SelectionContext:
        return self.selection_constraint_translator.compile_context(context, profile=profile)

    def build_capability_profile(
        self,
        performance: dict[str, Any],
        appearance: dict[str, Any],
        price: dict[str, Any],
        other: dict[str, Any],
        user_text: str = "",
    ) -> dict[str, Any]:
        scenario_tags = dedupe_list(
            list(performance.get("primary_usage") or [])
            + list(performance.get("secondary_usage") or [])
            + list(performance.get("capability_profile_ids") or [])
        )
        component_weights = dict(performance.get("reference_component_weights") or {})
        capabilities = list(performance.get("capabilities") or [])
        selection_context = self.build_selection_context(performance, appearance, price, other, user_text=user_text)

        if not any([scenario_tags, component_weights, capabilities, selection_context.protected_components, selection_context.cost_cut_components]):
            return {}

        return {
            "scenario_tags": scenario_tags,
            "capabilities": capabilities,
            "component_weights": component_weights,
            "protected_components": list(selection_context.protected_components or []),
            "cost_cut_components": list(selection_context.cost_cut_components or []),
            "must_satisfy": list(selection_context.must_satisfy or []),
            "prefer_satisfy": list(selection_context.prefer_satisfy or []),
            "avoid": list(selection_context.avoid or []),
        }

    def merge_missing_information(self, *sections: dict) -> list[str]:
        merged: list[str] = []
        for section in sections:
            merged += section.get("missing_information", [])
        return dedupe_list(merged)

    def _evaluate_conflict_rules(
        self,
        user_text: str,
        performance: dict[str, Any],
        appearance: dict[str, Any],
        price: dict[str, Any],
        other: dict[str, Any],
    ) -> list[dict[str, Any]]:
        rules = self.knowledge_repo.get_conflict_rules()
        if not rules:
            return []

        warnings: list[dict[str, Any]] = []
        secondary_usage = set(performance.get("secondary_usage") or [])
        primary_usage = set(performance.get("primary_usage") or [])
        focus = set(performance.get("performance_focus") or [])
        extraction = dict(price.get("budget_extraction") or {})
        max_budget = extraction.get("max_budget")
        target_budget = extraction.get("target_budget")
        budget_anchor = max_budget if max_budget is not None else target_budget
        appearance_style = str(appearance.get("case_style") or "")
        appearance_color = str(appearance.get("color") or "")
        appearance_rgb = str(appearance.get("rgb") or "")
        appearance_noise = str(appearance.get("noise") or "")
        case_size = str(appearance.get("case_size") or "")
        purchase_scope = dict(other.get("purchase_scope") or {})
        purchase_risk = dict(other.get("purchase_risk") or {})
        warranty_service = dict(other.get("warranty_service") or {})

        for rule in rules:
            rule_id = str(rule.get("rule_id") or "")
            matched = False
            if rule_id == "low_budget_4k_aaa":
                matched = (
                    budget_anchor is not None
                    and budget_anchor <= 6000
                    and "aaa_gaming" in secondary_usage
                    and (
                        (performance.get("performance_targets") or {}).get("resolution") in {"4k", "4K"}
                        or "高画质" in focus
                        or "4k" in user_text.lower()
                    )
                )
            elif rule_id == "low_budget_ai_training":
                matched = budget_anchor is not None and budget_anchor <= 12000 and "deep_learning_training" in secondary_usage
            elif rule_id == "budget_vs_white_panoramic":
                matched = budget_anchor is not None and budget_anchor <= 7000 and appearance_style == "panoramic" and appearance_color == "white"
            elif rule_id == "high_performance_vs_small_case":
                matched = case_size == "itx_compact" and bool(
                    {"aaa_gaming", "deep_learning_training", "3d_modeling_rendering", "professional_video_editing"} & secondary_usage
                )
            elif rule_id == "high_performance_vs_low_noise":
                matched = appearance_noise in {"silent", "low_noise"} and bool(
                    {"aaa_gaming", "deep_learning_training", "professional_video_editing", "3d_modeling_rendering"} & secondary_usage
                )
            elif rule_id == "host_only_vs_include_monitor":
                text = user_text.replace(" ", "")
                matched = purchase_scope.get("only_host") is True and (
                    purchase_scope.get("include_monitor") is True or "含显示器" in text or "带显示器" in text or "包含显示器" in text
                )
            elif rule_id == "no_rgb_vs_rgb_appearance":
                text = user_text.lower().replace(" ", "")
                matched = appearance_rgb == "no_rgb" and ("电竞风" in user_text or "rgb" in text or "炫酷" in user_text)
            elif rule_id == "multitask_streaming_editing_vs_low_memory":
                matched = bool({"game_streaming", "professional_video_editing", "light_video_editing"} & secondary_usage)
            if matched:
                warnings.append(
                    {
                        "rule_id": rule_id,
                        "severity": rule.get("severity", "medium"),
                        "message": rule.get("message", ""),
                        "suggested_resolutions": list(rule.get("suggested_resolutions") or []),
                    }
                )
        return warnings
