from __future__ import annotations

from typing import Any

from pc_build_agent.schemas.requirement_profile_schema import (
    RequirementProfile,
    RequirementProfileOutput,
    SelectionContext,
    dedupe_list,
    dump_model,
)


class RequirementOrchestrator:
    def __init__(
        self,
        performance_agent: Any,
        appearance_agent: Any,
        price_agent: Any,
        other_agent: Any,
    ):
        self.performance_agent = performance_agent
        self.appearance_agent = appearance_agent
        self.price_agent = price_agent
        self.other_agent = other_agent

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

        return self.build_requirement_profile(
            user_text=user_text,
            performance={"performance": performance_data},
            appearance={"appearance": appearance_data},
            price=price,
            other=other,
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
    ) -> dict:
        performance_data = self.unwrap(performance, "performance")
        appearance_data = self.unwrap(appearance, "appearance")
        price_data = self.unwrap(price, "price")
        other_data = self.unwrap(other, "other")

        profile = RequirementProfile(
            original_user_text=user_text,
            performance=performance_data,
            appearance=appearance_data,
            price=price_data,
            other=other_data,
            selection_context=self.build_selection_context(
                performance_data,
                appearance_data,
                price_data,
                other_data,
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
    ) -> SelectionContext:
        price_ctx = price.get("selection_context_for_parts_agent", {})
        other_ctx = other.get("constraints_for_selection_agent", {})
        appearance_ctx = appearance.get("constraints_for_selection_agent", {})
        performance_ctx = performance.get("constraints_for_selection_agent", {})

        must_satisfy: list[str] = []
        must_satisfy += price_ctx.get("must_satisfy", [])
        must_satisfy += other_ctx.get("must_have_features", [])
        must_satisfy += performance_ctx.get("must_have_features", [])

        prefer_satisfy: list[str] = []
        prefer_satisfy += price_ctx.get("prefer_satisfy", [])
        prefer_satisfy += other_ctx.get("prefer_features", [])
        prefer_satisfy += appearance_ctx.get("prefer_features", [])

        avoid: list[str] = []
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

        return SelectionContext(
            must_satisfy=dedupe_list(must_satisfy),
            prefer_satisfy=dedupe_list(prefer_satisfy),
            avoid=dedupe_list(avoid),
            protected_components=dedupe_list(protected_components),
            cost_cut_components=dedupe_list(cost_cut_components),
            budget_context=budget_context,
            compatibility_checks=dedupe_list(compatibility_checks),
            cross_module_signals=other.get("cross_module_signals", {}),
        )

    def merge_missing_information(self, *sections: dict) -> list[str]:
        merged: list[str] = []
        for section in sections:
            merged += section.get("missing_information", [])
        return dedupe_list(merged)
