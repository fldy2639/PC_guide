from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PerformanceInput(BaseModel):
    user_text: str


class PerformanceRule(BaseModel):
    rule_id: str
    primary_category: str
    secondary_category: str
    normalized_tag: str
    keywords: list[str] = Field(default_factory=list)
    performance_focus: list[str] = Field(default_factory=list)
    component_priority: list[str] = Field(default_factory=list)
    component_scores: dict[str, int] = Field(default_factory=dict)
    rule_description: str


class DemandStrengthItem(BaseModel):
    keyword_or_usage: str
    strength: str
    reason: str = ""


class PerformanceLlmExtraction(BaseModel):
    mentioned_keywords: list[str] = Field(default_factory=list)
    inferred_usage: list[str] = Field(default_factory=list)
    inferred_secondary_usage: list[str] = Field(default_factory=list)
    demand_strength: list[DemandStrengthItem] = Field(default_factory=list)
    performance_targets: dict[str, Any] = Field(default_factory=dict)
    missing_information: list[str] = Field(default_factory=list)


class ComponentPriorityItem(BaseModel):
    component: str
    importance: int
    score: float
    reason: str


class PerformanceOutput(BaseModel):
    matched_keywords: list[str] = Field(default_factory=list)
    primary_usage: list[str] = Field(default_factory=list)
    secondary_usage: list[str] = Field(default_factory=list)
    performance_summary: str = ""
    performance_focus: list[str] = Field(default_factory=list)
    component_priority: list[ComponentPriorityItem] = Field(default_factory=list)
    hardware_constraints: dict[str, str] = Field(default_factory=dict)
    missing_information: list[str] = Field(default_factory=list)
    performance_targets: dict[str, Any] = Field(default_factory=dict)


class PerformanceAgentOutput(BaseModel):
    performance: PerformanceOutput
