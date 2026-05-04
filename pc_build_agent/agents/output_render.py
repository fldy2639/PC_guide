from __future__ import annotations

from pc_build_agent.agents.validation_engine import ValidationOutcome
from pc_build_agent.models.schemas import BuildLine, ParsedRequirements
from pc_build_agent.services.deepseek_client import DeepSeekClient, get_client


def render_markdown_deterministic(parsed: ParsedRequirements, outcome: ValidationOutcome) -> str:
    title = "## 推荐方案"
    head = outcome.status

    lines: list[str] = [title, ""]

    lines.append(f"- **流程状态**：`{head}`")
    if parsed.explanation:
        lines.append(f"- **需求理解**：{parsed.explanation}")
    lines.append("")

    if outcome.status == "failed_with_alternative":
        lines.append("### 暂时无法给出闭环方案")
        if outcome.unmet_constraints:
            lines.append("- **未满足约束**：" + "、".join(outcome.unmet_constraints))
        if outcome.alternative_suggestions:
            lines.append("- **建议**：")
            for s in outcome.alternative_suggestions:
                lines.append(f"  - {s}")
        return "\n".join(lines)

    lines.append("我会基于你的预算与用途偏好选择配件，并在代码规则层做兼容性/功耗校验。")
    lines.append("")

    lines.append("| 类别 | 配件详情 | 数量 | 参考价 | 京东购买入口 |")
    lines.append("|---|---|---:|---:|---|")
    for item in outcome.final_build:
        url = item.jd_url or "（链接占位）"
        lines.append(f"| {item.category} | {item.name} | {item.quantity} | ¥{item.price:.0f} | {url} |")

    lines.append("")
    lines.append(f"**预计总价：¥{outcome.total_price:.0f}**")
    lines.append("")

    bc = outcome.budget_check or {}
    lines.append("### 预算说明")
    lines.append(f"- **检查结论**：{bc.get('status')}")
    if bc.get("target_max") is not None:
        lines.append(f"- **预算上限参考**：¥{float(bc['target_max']):.0f}")
    lines.append("")

    lines.append("### 兼容性说明")
    cc = outcome.compatibility_check or {}
    lines.append(f"- **结论**：{cc.get('status')}")
    warns = cc.get("warnings") or []
    for w in warns:
        lines.append(f"- {w}")
    lines.append("")

    lines.append("### 风险提示")
    rc = outcome.risk_check or {}
    lines.append(f"- **结论**：{rc.get('status')}")
    rw = rc.get("warnings") or []
    for w in rw:
        lines.append(f"- {w}")

    if outcome.status == "need_user_confirmation":
        lines.append("")
        lines.append("### 需要你确认")
        lines.append("- 当前方案略超预算上限：如果你接受小幅超支，我可以按此清单下单组合；否则请回复「严格不超预算」让我继续降配。")

    return "\n".join(lines)


def polish_markdown(base_md: str, client: DeepSeekClient | None = None) -> str:
    """可选：模型润色排版（不改变表格事实）"""
    c = client or get_client()
    if not c.api_key:
        return base_md
    messages = [
        {
            "role": "system",
            "content": "你是京东装机导购助手。请在保持表格与价格数字不被篡改的前提下，优化中文措辞与段落结构；不要编造配件型号与链接。",
        },
        {"role": "user", "content": base_md},
    ]
    try:
        return c.chat_text(messages, temperature=0.3)
    except Exception:
        return base_md


def render_final_markdown(parsed: ParsedRequirements, outcome: ValidationOutcome, polish: bool = False) -> str:
    md = render_markdown_deterministic(parsed, outcome)
    if polish:
        return polish_markdown(md)
    return md


def build_jd_links(build: list[BuildLine]) -> list[dict]:
    out = []
    for x in build:
        out.append({"category": x.category, "name": x.name, "price": x.price, "jd_url": x.jd_url})
    return out
