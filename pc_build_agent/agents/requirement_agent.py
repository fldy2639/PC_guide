from __future__ import annotations

from typing import Any

from pc_build_agent.models.schemas import ParsedRequirements
from pc_build_agent.services.deepseek_client import DeepSeekClient, get_client


SYSTEM_PROMPT = """你是一名专业的装机需求分析助手。你的任务是从对话文本中提取结构化装机需求。

对话文本包含多轮「用户 / 助手」消息合并而成；请以**最后一次用户诉求为准**，并兼顾前文补充信息。

你需要识别：
1. 预算范围（min/max）、货币（默认 CNY）、严格程度 strictness（soft/medium/hard）。
2. 使用场景 usage（如：3A游戏、网游、办公、剪辑、直播、AI、本地模型等）。
3. 性能目标 performance（分辨率、帧率、游戏类型等；可为空对象）。
4. 外观偏好 appearance（颜色、海景房、RGB、静音、小机箱等；可为空对象）。
5. 价格敏感度 price（priority、allow_over_budget、over_budget_policy）。
6. display.need_monitor：是否需要显示器（务必布尔）。
7. specified_parts：用户指定的品类与文本；品类请使用中文：处理器、显卡、主板、内存、硬盘、机箱、电源、散热、风扇、显示器。
8. 品牌偏好 brand_preferences、排除 avoid_preferences、其他约束 other_constraints。

权重 weights：
- 根据用户表达强度分配 performance、price、appearance、other 四项，且总和必须等于 1。
- 用户强调预算不可超 -> 提高 price。
- 强调游戏性能/分辨率 -> 提高 performance。
- 强调白色海景房/RGB -> 提高 appearance。
- 静音/小机箱等可归入 other。

追问规则（最多追问一次）：
- 缺预算或缺用途 -> need_clarification=true。
- 「整套预算」但不清楚是否包含显示器 -> need_clarification=true。
- 明显冲突（例如极低预算 + 4K 高画质 3A）-> need_clarification=true。

卡片式追问 clarification_cards（可选但推荐）：
- 当 need_clarification=true 时，尽量输出 1~3 张卡片，让用户一键选择。
- 每张卡包含：id、title、multi_select、options[{value,label}]。
- 示例：预算卡片给 3~5 个区间；显示器卡片给「只要主机/包含显示器/暂不确定」。

输出必须是 JSON（不要 Markdown），字段：
{
  "need_clarification": boolean,
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
  "performance": object,
  "appearance": object,
  "price": object,
  "display": {"need_monitor": boolean|null},
  "specified_parts": [
    {"category": string, "user_text": string, "match_mode": "fuzzy", "constraint_level": "hard"}
  ],
  "brand_preferences": string[],
  "avoid_preferences": string[],
  "other_constraints": string[]
}
"""


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
    if req.usage:
        parts.append("用途：" + "、".join(req.usage))
    disp = req.display
    if disp and disp.need_monitor is True:
        parts.append("需要显示器")
    elif disp and disp.need_monitor is False:
        parts.append("不需要显示器")
    ap = req.appearance or {}
    if ap.get("color") or ap.get("style"):
        blob = f"{ap.get('color') or ''} {ap.get('style') or ''}".strip()
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


def safe_parse(
    transcript: str,
    client: DeepSeekClient | None = None,
    trace_sink: list[dict[str, Any]] | None = None,
) -> ParsedRequirements:
    parsed = parse_requirements(transcript, client=client, trace_sink=trace_sink)
    return coerce_defaults(parsed)
