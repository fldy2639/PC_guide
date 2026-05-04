from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ComponentBudgetPolicyItem(BaseModel):
    component: str
    chinese_name: str
    performance_relevance: str
    appearance_relevance: str
    other_relevance: str
    budget_priority: str
    price_control_level: str
    protected: bool
    can_cut_cost: bool
    can_upgrade_if_budget_allows: bool
    must_preserve_attributes: list[str] = Field(default_factory=list)
    relaxable_attributes: list[str] = Field(default_factory=list)
    selection_instruction: str = ""
    reason: str = ""


class PriceOutput(BaseModel):
    budget_extraction: dict[str, Any] = Field(default_factory=dict)
    budget_scope: dict[str, Any] = Field(default_factory=dict)
    budget_pressure: dict[str, Any] = Field(default_factory=dict)
    performance_price_impact: dict[str, Any] = Field(default_factory=dict)
    appearance_price_impact: dict[str, Any] = Field(default_factory=dict)
    other_price_impact: dict[str, Any] = Field(default_factory=dict)
    component_budget_policy: list[ComponentBudgetPolicyItem] = Field(default_factory=list)
    budget_allocation_profile: dict[str, Any] = Field(default_factory=dict)
    tradeoff_strategy: dict[str, Any] = Field(default_factory=dict)
    selection_context_for_parts_agent: dict[str, Any] = Field(default_factory=dict)
    missing_information: list[str] = Field(default_factory=list)


class PriceAgentOutput(BaseModel):
    price: PriceOutput
