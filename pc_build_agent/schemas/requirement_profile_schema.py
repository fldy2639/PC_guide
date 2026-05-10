from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


def dump_model(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def dedupe_list(items: list[Any]) -> list[Any]:
    result: list[Any] = []
    for item in items:
        if item not in result:
            result.append(item)
    return result


class SelectionContext(BaseModel):
    must_satisfy: list[Any] = Field(default_factory=list)
    prefer_satisfy: list[Any] = Field(default_factory=list)
    avoid: list[Any] = Field(default_factory=list)
    protected_components: list[str] = Field(default_factory=list)
    cost_cut_components: list[str] = Field(default_factory=list)
    budget_context: dict[str, Any] = Field(default_factory=dict)
    compatibility_checks: list[str] = Field(default_factory=list)
    cross_module_signals: dict[str, Any] = Field(default_factory=dict)


class RequirementProfile(BaseModel):
    original_user_text: str = ""
    performance: dict[str, Any] = Field(default_factory=dict)
    appearance: dict[str, Any] = Field(default_factory=dict)
    price: dict[str, Any] = Field(default_factory=dict)
    other: dict[str, Any] = Field(default_factory=dict)
    capability_profile: dict[str, Any] = Field(default_factory=dict)
    specified_parts: list[Any] = Field(default_factory=list)
    selection_context: SelectionContext = Field(default_factory=SelectionContext)
    missing_information: list[str] = Field(default_factory=list)


class RequirementProfileOutput(BaseModel):
    requirement_profile: RequirementProfile = Field(default_factory=RequirementProfile)
