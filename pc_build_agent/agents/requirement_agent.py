from __future__ import annotations

from typing import Any

from pc_build_agent.agents.appearance_requirement_agent import AppearanceRequirementAgent
from pc_build_agent.agents.legacy_requirement_adapter import LegacyRequirementAdapter
from pc_build_agent.agents.other_requirement_agent import OtherRequirementAgent
from pc_build_agent.agents.performance_requirement_agent import PerformanceRequirementAgent
from pc_build_agent.agents.price_requirement_agent import PriceRequirementAgent
from pc_build_agent.agents.requirement_orchestrator import RequirementOrchestrator
from pc_build_agent.models.schemas import ParsedRequirements
from pc_build_agent.services.deepseek_client import DeepSeekClient, get_client
from pc_build_agent.services.requirement_knowledge_repository import RequirementKnowledgeRepository


SYSTEM_PROMPT = """你是一名专业的装机需求分析助手。你的任务是从对话文本中提取结构化装机需求，并直接产出可供下游选配模块消费的结果。

对话文本包含多轮「用户 / 助手」消息合并而成；请以**最后一次用户诉求为准**，并兼顾前文补充信息。

你需要把需求尽量拆成 4 个一级指标：
1. performance：使用场景、具体软件/游戏/任务、性能目标、关键硬件参数。
2. appearance：主机大小、主机样式、颜色材质、灯光与静音偏好。
3. price：最低预算、最高预算、预算强度、性价比偏好、是否允许小幅超预算。
4. other：是否已有显示器、是否需要显示器、分辨率/刷新率、是否需要无线网卡/蓝牙、是否需要正版系统、是否接受二手/散片/海外版、是否需要整机质保、是否有升级空间要求。

同时为了兼容现有下游模块，你还需要补充这些兼容字段：
- budget：从 price 中整理出 min/max/currency/strictness。
- usage：从 performance 中提炼为用途列表。
- display.need_monitor：是否需要显示器，务必布尔或 null。
- specified_parts：用户指定的品类与文本；品类请使用中文：处理器、显卡、主板、内存、硬盘、机箱、电源、散热、风扇、显示器。
- brand_preferences、avoid_preferences、other_constraints。

权重 weights：
- 根据用户表达强度分配 performance、price、appearance、other 四项，且总和必须等于 1。
- 用户强调预算不可超 -> 提高 price。
- 强调游戏性能/分辨率 -> 提高 performance。
- 强调白色海景房/RGB -> 提高 appearance。
- 静音/小机箱等可归入 other。

输出原则：
- 不要触发追问中断，下游必须能继续执行。
- 即使信息不完整，也要基于已有文本给出最合理的结构化推断。
- 不确定的信息写入 missing_fields，并保持 need_clarification=false。
- clarification_question 设为 null，clarification_cards 设为空数组。

输出必须是 JSON（不要 Markdown），字段：
{
  "need_clarification": false,
  "clarification_question": string | null,
  "missing_fields": string[],
  "next_action": string | null,
  "clarification_cards": [
    {
      "id": string,
      "title": string,
      "multi_select": boolean,
      "options": [{"value": string, "label": string}]
    }
  ],
  "requirements": object,
  "weights": object,
  "explanation": string
}

requirements 的结构请尽量贴合下列字段（缺失用 null 或空数组）：
{
  "budget": {"min": number|null, "max": number|null, "currency": "CNY", "strictness": string|null},
  "usage": string[],
  "performance": {
    "matched_keywords": string[],
    "primary_usage": string[],
    "secondary_usage": string[],
    "performance_summary": string,
    "performance_focus": string[],
    "component_priority": object[],
    "hardware_constraints": object,
    "missing_information": string[],
    "performance_targets": object
  },
  "appearance": {
    "size": string|null,
    "style": string|null,
    "color": string|null,
    "material": string|null,
    "rgb_preference": string|null,
    "noise_preference": string|null
  },
  "price": {
    "min": number|null,
    "max": number|null,
    "currency": "CNY",
    "strictness": string|null,
    "priority": string|null,
    "allow_over_budget": boolean|null,
    "over_budget_policy": string|null,
    "value_preference": string|null
  },
  "other": {
    "need_monitor": boolean|null,
    "has_monitor": boolean|null,
    "resolution": string|null,
    "refresh_rate": string|null,
    "need_wifi": boolean|null,
    "need_bluetooth": boolean|null,
    "need_genuine_os": boolean|null,
    "accept_second_hand": boolean|null,
    "accept_tray_cpu": boolean|null,
    "accept_overseas_version": boolean|null,
    "need_full_system_warranty": boolean|null,
    "upgradeability_requirement": string|null
  },
  "display": {"need_monitor": boolean|null},
  "specified_parts": [
    {"category": string, "user_text": string, "match_mode": "fuzzy", "constraint_level": "hard"}
  ],
  "brand_preferences": string[],
  "avoid_preferences": string[],
  "other_constraints": string[]
}
"""


def _latest_user_utterance(transcript: str) -> str:
    lines = [line.strip() for line in transcript.splitlines() if line.strip()]
    for line in reversed(lines):
        if line.startswith("用户："):
            return line.split("用户：", 1)[1].strip()
    return transcript.strip()


def _model_to_dict(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _flatten_other_result_for_price(other_result: dict[str, Any]) -> dict[str, Any]:
    purchase_scope = dict(other_result.get("purchase_scope") or {})
    connectivity = dict(other_result.get("connectivity") or {})
    purchase_risk = dict(other_result.get("purchase_risk") or {})
    warranty_service = dict(other_result.get("warranty_service") or {})
    upgrade_plan = dict(other_result.get("upgrade_plan") or {})
    special_requirements = dict(other_result.get("special_requirements") or {})

    need_wifi = connectivity.get("need_wifi")
    need_bluetooth = connectivity.get("need_bluetooth")
    need_wifi_bluetooth = True if (need_wifi is True or need_bluetooth is True) else None

    return {
        "only_host": purchase_scope.get("only_host"),
        "include_monitor": purchase_scope.get("include_monitor"),
        "include_peripherals": purchase_scope.get("include_peripherals"),
        "include_os": purchase_scope.get("include_os"),
        "include_assembly_service": purchase_scope.get("include_assembly_service"),
        "need_wifi_bluetooth": need_wifi_bluetooth,
        "accept_used_parts": purchase_risk.get("accept_used_parts"),
        "need_warranty": warranty_service.get("need_warranty"),
        "upgrade_space_required": upgrade_plan.get("upgrade_space_required"),
        "storage_capacity_requirement": special_requirements.get("storage_capacity_requirement"),
    }


def enrich_other(
    parsed: ParsedRequirements,
    transcript: str,
    client: DeepSeekClient | None = None,
    knowledge_repo: RequirementKnowledgeRepository | None = None,
) -> ParsedRequirements:
    user_text = _latest_user_utterance(transcript)
    agent = OtherRequirementAgent(llm=client, knowledge_repo=knowledge_repo)
    result = agent.analyze(user_text)
    other_result = dict(result.get("other") or {})
    parsed.__dict__["_other_agent_result"] = other_result

    legacy_other = parsed.requirements.other
    purchase_scope = dict(other_result.get("purchase_scope") or {})
    owned_parts = dict(other_result.get("owned_parts") or {})
    connectivity = dict(other_result.get("connectivity") or {})
    purchase_risk = dict(other_result.get("purchase_risk") or {})
    warranty_service = dict(other_result.get("warranty_service") or {})
    upgrade_plan = dict(other_result.get("upgrade_plan") or {})

    if legacy_other.has_monitor is None and owned_parts.get("has_monitor") is not None:
        legacy_other.has_monitor = bool(owned_parts.get("has_monitor"))
    if legacy_other.need_wifi is None and connectivity.get("need_wifi") is not None:
        legacy_other.need_wifi = bool(connectivity.get("need_wifi"))
    if legacy_other.need_bluetooth is None and connectivity.get("need_bluetooth") is not None:
        legacy_other.need_bluetooth = bool(connectivity.get("need_bluetooth"))
    if legacy_other.accept_second_hand is None and purchase_risk.get("accept_used_parts") is not None:
        legacy_other.accept_second_hand = bool(purchase_risk.get("accept_used_parts"))
    if legacy_other.need_full_system_warranty is None and warranty_service.get("need_warranty") is not None:
        legacy_other.need_full_system_warranty = bool(warranty_service.get("need_warranty"))
    if legacy_other.upgradeability_requirement is None and upgrade_plan.get("upgrade_priority") not in [None, "unknown"]:
        legacy_other.upgradeability_requirement = str(upgrade_plan.get("upgrade_priority"))

    need_monitor = None
    if purchase_scope.get("include_monitor") is True:
        need_monitor = True
    elif purchase_scope.get("only_host") is True or purchase_scope.get("include_monitor") is False:
        need_monitor = False
    elif owned_parts.get("has_monitor") is True:
        need_monitor = False

    if need_monitor is not None and legacy_other.need_monitor is None:
        legacy_other.need_monitor = need_monitor

    parsed.requirements.other = legacy_other
    if parsed.requirements.display is not None and parsed.requirements.display.need_monitor is None and need_monitor is not None:
        parsed.requirements.display.need_monitor = need_monitor

    missing = list(parsed.missing_fields or [])
    for item in other_result.get("missing_information") or []:
        if item not in missing:
            missing.append(item)
    parsed.missing_fields = missing
    return parsed


def enrich_appearance(
    parsed: ParsedRequirements,
    transcript: str,
    client: DeepSeekClient | None = None,
    knowledge_repo: RequirementKnowledgeRepository | None = None,
) -> ParsedRequirements:
    user_text = _latest_user_utterance(transcript)
    agent = AppearanceRequirementAgent(llm=client, knowledge_repo=knowledge_repo)
    result = agent.analyze(user_text)
    appearance = dict(parsed.requirements.appearance or {})
    appearance.update(result.get("appearance") or {})
    parsed.requirements.appearance = appearance

    missing = list(parsed.missing_fields or [])
    for item in appearance.get("missing_information") or []:
        if item not in missing:
            missing.append(item)
    parsed.missing_fields = missing
    return parsed


def enrich_performance(
    parsed: ParsedRequirements,
    transcript: str,
    client: DeepSeekClient | None = None,
    knowledge_repo: RequirementKnowledgeRepository | None = None,
) -> ParsedRequirements:
    user_text = _latest_user_utterance(transcript)
    agent = PerformanceRequirementAgent(llm=client, knowledge_repo=knowledge_repo)
    result = agent.analyze(user_text)
    perf = dict((parsed.requirements.performance or {}))
    perf.update(result.get("performance") or {})
    parsed.requirements.performance = perf

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

    usage = list(parsed.requirements.usage or [])
    for item in perf.get("matched_keywords") or []:
        if item not in usage:
            usage.append(item)
    for item in perf.get("secondary_usage") or []:
        label = secondary_usage_map.get(str(item), str(item))
        if label not in usage:
            usage.append(label)
    for item in perf.get("primary_usage") or []:
        label = primary_usage_map.get(str(item), str(item))
        if label not in usage:
            usage.append(label)
    if usage:
        parsed.requirements.usage = usage

    missing = list(parsed.missing_fields or [])
    for item in perf.get("missing_information") or []:
        if item not in missing:
            missing.append(item)
    parsed.missing_fields = missing

    price = dict(parsed.requirements.price or {})
    budget = parsed.requirements.budget
    if budget:
        if price.get("min") is None:
            price["min"] = budget.min
        if price.get("max") is None:
            price["max"] = budget.max
        if not price.get("currency"):
            price["currency"] = budget.currency
        if not price.get("strictness"):
            price["strictness"] = budget.strictness
    parsed.requirements.price = price

    other = parsed.requirements.other
    if parsed.requirements.display and parsed.requirements.display.need_monitor is not None and other.need_monitor is None:
        other.need_monitor = parsed.requirements.display.need_monitor
    targets = perf.get("performance_targets") or {}
    if targets.get("resolution") and not other.resolution:
        other.resolution = str(targets.get("resolution"))
    if targets.get("fps") and not other.refresh_rate:
        other.refresh_rate = str(targets.get("fps"))
    parsed.requirements.other = other
    return parsed


def enrich_price(
    parsed: ParsedRequirements,
    transcript: str,
    client: DeepSeekClient | None = None,
    knowledge_repo: RequirementKnowledgeRepository | None = None,
) -> ParsedRequirements:
    user_text = _latest_user_utterance(transcript)
    agent = PriceRequirementAgent(llm=client, knowledge_repo=knowledge_repo)
    other_agent_result = parsed.__dict__.get("_other_agent_result")
    if isinstance(other_agent_result, dict):
        other_payload = _flatten_other_result_for_price(other_agent_result)
    else:
        other_payload = _model_to_dict(parsed.requirements.other)
    payload = {
        "user_text": user_text,
        "performance_result": {"performance": dict(parsed.requirements.performance or {})},
        "appearance_result": {"appearance": dict(parsed.requirements.appearance or {})},
        "other_result": {"other": other_payload},
    }
    result = agent.analyze(payload)
    price = dict(parsed.requirements.price or {})
    price.update(result.get("price") or {})
    parsed.requirements.price = price

    budget_extraction = price.get("budget_extraction") or {}
    budget = parsed.requirements.budget
    if budget is None:
        from pc_build_agent.models.schemas import BudgetModel

        budget = BudgetModel()
        parsed.requirements.budget = budget
    if budget.min is None and budget_extraction.get("min_budget") is not None:
        budget.min = float(budget_extraction["min_budget"])
    if budget.max is None and budget_extraction.get("max_budget") is not None:
        budget.max = float(budget_extraction["max_budget"])
    if budget.strictness is None:
        if budget_extraction.get("hard_limit") is True:
            budget.strictness = "hard"
        elif budget_extraction.get("budget_flexibility") in ["soft", "small_overspend", "flexible"]:
            budget.strictness = "medium"
    if not budget.currency:
        budget.currency = "CNY"

    other = parsed.requirements.other
    budget_scope = price.get("budget_scope") or {}
    if budget_scope.get("include_monitor") is True and other.need_monitor is None:
        other.need_monitor = True
    if budget_scope.get("include_monitor") is False and other.need_monitor is None:
        other.need_monitor = False
    parsed.requirements.other = other
    if parsed.requirements.display and parsed.requirements.display.need_monitor is None and other.need_monitor is not None:
        parsed.requirements.display.need_monitor = other.need_monitor

    missing = list(parsed.missing_fields or [])
    for item in price.get("missing_information") or []:
        if item not in missing:
            missing.append(item)
    parsed.missing_fields = missing
    return parsed


def build_messages(transcript: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": transcript},
    ]


def parse_requirements(
    transcript: str,
    client: DeepSeekClient | None = None,
    trace_sink: list[dict[str, Any]] | None = None,
) -> ParsedRequirements:
    c = client or get_client()
    raw = c.chat_json(build_messages(transcript), trace_sink=trace_sink, step="requirement_parse")
    return ParsedRequirements.from_llm_dict(raw)


def summarize_requirements(parsed: ParsedRequirements) -> str:
    req = parsed.requirements
    parts: list[str] = []
    if req.budget and (req.budget.min is not None or req.budget.max is not None):
        lo = req.budget.min
        hi = req.budget.max
        if lo is not None and hi is not None:
            parts.append(f"预算约 {int(lo)}-{int(hi)} 元")
        elif hi is not None:
            parts.append(f"预算上限约 {int(hi)} 元")
        elif lo is not None:
            parts.append(f"预算下限约 {int(lo)} 元")
    perf = req.performance or {}
    perf_summary = str(perf.get("performance_summary") or "").strip()
    if perf_summary:
        parts.append(perf_summary)
    elif req.usage:
        parts.append("用途：" + "、".join(req.usage))
    disp = req.display
    if disp and disp.need_monitor is True:
        parts.append("需要显示器")
    elif disp and disp.need_monitor is False:
        parts.append("不需要显示器")
    ap = req.appearance or {}
    if ap.get("color") or ap.get("style") or ap.get("size"):
        blob = f"{ap.get('color') or ''} {ap.get('style') or ''} {ap.get('size') or ''}".strip()
        if blob:
            parts.append(f"外观偏好：{blob}")
    return "；".join(parts) if parts else "用户需求摘要生成中"


def coerce_defaults(parsed: ParsedRequirements) -> ParsedRequirements:
    """少量兜底：权重归一、currency 填充"""
    w = parsed.weights or {}
    keys = ["performance", "price", "appearance", "other"]
    total = sum(float(w.get(k, 0) or 0) for k in keys)
    if total <= 0:
        w = {"performance": 0.45, "price": 0.35, "appearance": 0.15, "other": 0.05}
        total = 1.0
    else:
        w = {k: float(w.get(k, 0) or 0) / total for k in keys}
    parsed.weights = w

    if parsed.requirements.budget and not parsed.requirements.budget.currency:
        parsed.requirements.budget.currency = "CNY"

    return parsed


def finalize_for_selection(parsed: ParsedRequirements) -> ParsedRequirements:
    """第一层只保留缺失信息提示，不再阻断第二层选配流程。"""
    parsed.need_clarification = False
    parsed.clarification_question = None
    parsed.clarification_cards = []
    if parsed.next_action == "clarify":
        parsed.next_action = "proceed_to_selection"
    return coerce_defaults(parsed)


def safe_parse(
    transcript: str,
    client: DeepSeekClient | None = None,
    trace_sink: list[dict[str, Any]] | None = None,
) -> ParsedRequirements:
    user_text = _latest_user_utterance(transcript)
    knowledge_repo = RequirementKnowledgeRepository()
    orchestrator = RequirementOrchestrator(
        performance_agent=PerformanceRequirementAgent(llm=client, knowledge_repo=knowledge_repo),
        appearance_agent=AppearanceRequirementAgent(llm=client, knowledge_repo=knowledge_repo),
        price_agent=PriceRequirementAgent(llm=client, knowledge_repo=knowledge_repo),
        other_agent=OtherRequirementAgent(llm=client, knowledge_repo=knowledge_repo),
        knowledge_repo=knowledge_repo,
    )

    try:
        profile_output = orchestrator.analyze(user_text)
        parsed = LegacyRequirementAdapter.from_requirement_profile(profile_output)
        parsed = finalize_for_selection(parsed)
        parsed.__dict__["requirement_profile"] = profile_output.get("requirement_profile", {})
        return parsed
    except Exception:
        parsed = parse_requirements(transcript, client=client, trace_sink=trace_sink)
        parsed = enrich_appearance(parsed, transcript, client=client, knowledge_repo=knowledge_repo)
        parsed = enrich_performance(parsed, transcript, client=client, knowledge_repo=knowledge_repo)
        parsed = enrich_other(parsed, transcript, client=client, knowledge_repo=knowledge_repo)
        other_agent_result = parsed.__dict__.get("_other_agent_result")
        if isinstance(other_agent_result, dict):
            other_payload = _flatten_other_result_for_price(other_agent_result)
        else:
            other_payload = _model_to_dict(parsed.requirements.other)
        price_agent = PriceRequirementAgent(llm=client, knowledge_repo=knowledge_repo)
        price_result = price_agent.analyze(
            user_text=user_text,
            performance_result={"performance": dict(parsed.requirements.performance or {})},
            appearance_result={"appearance": dict(parsed.requirements.appearance or {})},
            other_result={"other": other_payload},
        )
        price = dict(parsed.requirements.price or {})
        price.update(price_result.get("price") or {})
        parsed.requirements.price = price
        parsed.__dict__["requirement_profile"] = {
            "original_user_text": user_text,
            "performance": dict(parsed.requirements.performance or {}),
            "appearance": dict(parsed.requirements.appearance or {}),
            "price": dict(parsed.requirements.price or {}),
            "other": _model_to_dict(parsed.requirements.other),
            "selection_context": {},
            "missing_information": list(parsed.missing_fields or []),
        }
        return finalize_for_selection(parsed)
