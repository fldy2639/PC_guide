from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RecommendRequest(BaseModel):
    user_query: str
    user_id: str | None = None
    session_id: str | None = None
    version: str = "v1"
    # 调试：为 True 时在响应 data.debug_llm 中返回模型调用轨迹（或与 PC_GUIDE_DEBUG_LLM 同时为真）
    debug_llm: bool = False


class ClarificationCardOption(BaseModel):
    value: str
    label: str


class ClarificationCard(BaseModel):
    id: str
    title: str
    multi_select: bool = False
    options: list[ClarificationCardOption] = Field(default_factory=list)


class BudgetModel(BaseModel):
    min: float | None = None
    max: float | None = None
    currency: str = "CNY"
    strictness: str | None = None


class DisplayModel(BaseModel):
    need_monitor: bool | None = None


class SpecifiedPartModel(BaseModel):
    category: str
    user_text: str
    match_mode: str = "fuzzy"
    constraint_level: str = "hard"


class RequirementsModel(BaseModel):
    budget: BudgetModel | None = None
    usage: list[str] = Field(default_factory=list)
    performance: dict[str, Any] = Field(default_factory=dict)
    appearance: dict[str, Any] = Field(default_factory=dict)
    price: dict[str, Any] = Field(default_factory=dict)
    display: DisplayModel | None = None
    specified_parts: list[SpecifiedPartModel] = Field(default_factory=list)
    brand_preferences: list[str] = Field(default_factory=list)
    avoid_preferences: list[str] = Field(default_factory=list)
    other_constraints: list[str] = Field(default_factory=list)


class ParsedRequirements(BaseModel):
    need_clarification: bool
    clarification_question: str | None = None
    missing_fields: list[str] = Field(default_factory=list)
    next_action: str | None = None
    clarification_cards: list[ClarificationCard] = Field(default_factory=list)
    requirements: RequirementsModel = Field(default_factory=RequirementsModel)
    weights: dict[str, float] = Field(default_factory=dict)
    explanation: str = ""

    @classmethod
    def from_llm_dict(cls, raw: dict[str, Any]) -> ParsedRequirements:
        req = raw.get("requirements") or {}
        cards_raw = raw.get("clarification_cards") or []
        cards: list[ClarificationCard] = []
        for c in cards_raw:
            opts = [
                ClarificationCardOption(value=o["value"], label=o["label"])
                for o in (c.get("options") or [])
                if isinstance(o, dict) and "value" in o and "label" in o
            ]
            cards.append(
                ClarificationCard(
                    id=str(c.get("id", "choice")),
                    title=str(c.get("title", "请选择")),
                    multi_select=bool(c.get("multi_select", False)),
                    options=opts,
                )
            )
        return cls(
            need_clarification=bool(raw.get("need_clarification")),
            clarification_question=raw.get("clarification_question"),
            missing_fields=list(raw.get("missing_fields") or []),
            next_action=raw.get("next_action"),
            clarification_cards=cards,
            requirements=RequirementsModel.model_validate(req),
            weights=dict(raw.get("weights") or {}),
            explanation=str(raw.get("explanation") or ""),
        )


class ProductRecord(BaseModel):
    sku_id: str
    category: str
    name: str
    price: float
    jd_url: str | None = None
    tags: list[str] = Field(default_factory=list)


class BuildLine(BaseModel):
    category: str
    sku_id: str
    name: str
    price: float
    jd_url: str | None = None
    quantity: int = 1


class RecommendResponseData(BaseModel):
    need_clarification: bool = False
    clarification_question: str | None = None
    missing_fields: list[str] = Field(default_factory=list)
    clarification_cards: list[ClarificationCard] = Field(default_factory=list)
    session_id: str | None = None

    requirement_summary: str = ""
    weights: dict[str, float] = Field(default_factory=dict)
    weights_explanation: str = ""

    candidates_preview: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)

    status: str | None = None
    final_build: list[BuildLine] = Field(default_factory=list)
    total_price: float = 0
    budget_check: dict[str, Any] = Field(default_factory=dict)
    compatibility_check: dict[str, Any] = Field(default_factory=dict)
    risk_check: dict[str, Any] = Field(default_factory=dict)
    unmet_constraints: list[str] = Field(default_factory=list)
    alternative_suggestions: list[str] = Field(default_factory=list)

    recommendation_markdown: str = ""
    recommendation_reason: list[str] = Field(default_factory=list)
    compatibility_notes: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)
    jd_purchase_links: list[dict[str, Any]] = Field(default_factory=list)

    # 调试专用：模型请求/响应摘要（含思维链字段 reasoning_content，取决于模型与上游 API）
    debug_llm: dict[str, Any] | None = None


class RecommendResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: RecommendResponseData
