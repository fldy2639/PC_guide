from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


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


class ComponentPriorityItemModel(BaseModel):
    component: str
    importance: int
    score: float
    reason: str


class OtherRequirementsModel(BaseModel):
    need_monitor: bool | None = None
    has_monitor: bool | None = None
    resolution: str | None = None
    refresh_rate: str | None = None
    need_wifi: bool | None = None
    need_bluetooth: bool | None = None
    need_genuine_os: bool | None = None
    accept_second_hand: bool | None = None
    accept_tray_cpu: bool | None = None
    accept_overseas_version: bool | None = None
    need_full_system_warranty: bool | None = None
    upgradeability_requirement: str | None = None


def _primary_usage_labels(primary_usage: Any) -> list[str]:
    mapping = {
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
    labels: list[str] = []
    for item in primary_usage or []:
        if not item:
            continue
        key = str(item).strip()
        labels.append(mapping.get(key, key))
    return labels


def _secondary_usage_labels(secondary_usage: Any) -> list[str]:
    mapping = {
        "fps_esports": "电竞游戏",
        "aaa_gaming": "3A游戏",
        "high_quality_ray_tracing": "高画质光追",
        "light_gaming": "轻度游戏",
        "emulator_multi_instance": "模拟器多开",
        "game_streaming": "游戏直播",
        "general_streaming": "纯直播",
        "general_study": "普通学习",
        "programming_development": "编程开发",
        "data_analysis_modeling": "数据分析建模",
        "general_office": "普通办公",
        "office_multitasking": "多任务办公",
        "graphic_design": "平面设计",
        "light_video_editing": "轻度视频剪辑",
        "professional_video_editing": "专业视频剪辑",
        "3d_modeling_rendering": "3D建模渲染",
        "cad_industrial_design": "CAD工业设计",
        "local_llm_inference": "本地大模型推理",
        "ai_image_generation": "AI绘图",
        "deep_learning_training": "深度学习训练",
        "simulation_computing": "仿真计算",
    }
    labels: list[str] = []
    for item in secondary_usage or []:
        if not item:
            continue
        key = str(item).strip()
        labels.append(mapping.get(key, key))
    return labels


def _normalize_requirement_payload(req: dict[str, Any]) -> dict[str, Any]:
    out = dict(req or {})

    price = out.get("price")
    budget = dict(out.get("budget") or {})
    if isinstance(price, dict):
        for key in ["min", "max", "currency", "strictness"]:
            if budget.get(key) is None and price.get(key) is not None:
                budget[key] = price.get(key)
    if budget:
        out["budget"] = budget

    performance = out.get("performance")
    if isinstance(performance, dict):
        usage = list(out.get("usage") or [])
        if not usage:
            usage = _secondary_usage_labels(performance.get("secondary_usage"))
        if not usage:
            usage = _primary_usage_labels(performance.get("primary_usage"))
        if usage:
            out["usage"] = usage

    other = out.get("other")
    if isinstance(other, dict):
        display = dict(out.get("display") or {})
        if not display and other.get("need_monitor") is not None:
            display["need_monitor"] = other.get("need_monitor")
        if not display and isinstance(other.get("display"), dict):
            if other["display"].get("need_monitor") is not None:
                display["need_monitor"] = other["display"].get("need_monitor")
        if display:
            out["display"] = display

        other_constraints = list(out.get("other_constraints") or [])
        for key in [
            "resolution",
            "refresh_rate",
            "need_wifi",
            "need_bluetooth",
            "need_genuine_os",
            "accept_second_hand",
            "accept_tray_cpu",
            "accept_overseas_version",
            "need_full_system_warranty",
            "upgradeability_requirement",
        ]:
            value = other.get(key)
            if value not in (None, "", False):
                other_constraints.append(f"{key}={value}")
        if other_constraints:
            out["other_constraints"] = other_constraints

    return out


class RequirementsModel(BaseModel):
    budget: BudgetModel | None = None
    usage: list[str] = Field(default_factory=list)
    performance: dict[str, Any] = Field(default_factory=dict)
    appearance: dict[str, Any] = Field(default_factory=dict)
    @field_validator("appearance", mode="before")
    @classmethod
    def none_to_empty_appearance(cls, value):
        return {} if value is None else value

    price: dict[str, Any] = Field(default_factory=dict)
    other: OtherRequirementsModel = Field(default_factory=OtherRequirementsModel)
    display: DisplayModel | None = None
    specified_parts: list[SpecifiedPartModel] = Field(default_factory=list)
    brand_preferences: list[str] = Field(default_factory=list)
    avoid_preferences: list[str] = Field(default_factory=list)
    other_constraints: list[str] = Field(default_factory=list)

    @field_validator("performance", "price", mode="before")
    @classmethod
    def none_to_empty_dict(cls, value):
        return {} if value is None else value

    @field_validator("other", mode="before")
    @classmethod
    def none_to_other_model(cls, value):
        return {} if value is None else value


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
        req = _normalize_requirement_payload(raw.get("requirements") or {})
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
