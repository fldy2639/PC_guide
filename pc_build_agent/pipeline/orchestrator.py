from __future__ import annotations

from typing import Any

from pc_build_agent.agents.output_render import build_jd_links, render_final_markdown
from pc_build_agent.agents.requirement_agent import safe_parse, summarize_requirements
from pc_build_agent.agents.selection import retrieve_candidates
from pc_build_agent.agents.validation_engine import validate_and_select
from pc_build_agent.config import settings
from pc_build_agent.models.schemas import RecommendRequest, RecommendResponse, RecommendResponseData
from pc_build_agent.services.deepseek_client import get_client
from pc_build_agent.services.product_repository import get_product_repository
from pc_build_agent.services.session_store import get_session_store


def _debug_llm_payload(trace: list[dict[str, Any]] | None, enabled: bool) -> dict[str, Any] | None:
    if not enabled:
        return None
    return {
        "enabled": True,
        "model": settings.deepseek_model,
        "steps": trace or [],
        "note": (
            "调试信息包含完整 messages 与上游返回的 assistant_message。"
            "若使用 DeepSeek 推理模型，assistant_message.reasoning_content 一般为思维链；"
            "deepseek-chat 等模型通常仅有 content。"
            "请勿在生产环境对外暴露。"
        ),
    }


def _merge_transcript(turns: list) -> str:
    lines: list[str] = []
    for t in turns:
        prefix = "用户" if t.role == "user" else "助手"
        lines.append(f"{prefix}：{t.content}".strip())
    return "\n".join(lines).strip()


def recommend(req: RecommendRequest) -> RecommendResponse:
    store = get_session_store()
    repo = get_product_repository()
    client = get_client()

    debug_on = bool(settings.pc_guide_debug_llm or req.debug_llm)
    trace: list[dict[str, Any]] | None = [] if debug_on else None

    sid = req.session_id
    if not sid:
        sid = store.create_session()
    elif not store.session_exists(sid):
        sid = store.create_session()

    store.append_message(sid, "user", req.user_query.strip())

    turns = store.list_turns(sid, limit=40)
    transcript = _merge_transcript(turns)

    try:
        parsed = safe_parse(transcript, client=client, trace_sink=trace)
    except Exception as exc:  # noqa: BLE001
        msg = f"需求理解失败：{exc}"
        store.append_message(sid, "assistant", msg, meta={"type": "error"})
        return RecommendResponse(
            code=1,
            message="parse_failed",
            data=RecommendResponseData(
                need_clarification=False,
                session_id=sid,
                recommendation_markdown=msg,
                debug_llm=_debug_llm_payload(trace, debug_on),
            ),
        )

    if parsed.need_clarification:
        q = parsed.clarification_question or "可以再补充一下预算区间和主要用途吗？是否需要显示器？"
        store.append_message(sid, "assistant", q, meta={"type": "clarification", "missing": parsed.missing_fields})
        return RecommendResponse(
            code=0,
            message="need_clarification",
            data=RecommendResponseData(
                need_clarification=True,
                clarification_question=q,
                missing_fields=list(parsed.missing_fields or []),
                clarification_cards=list(parsed.clarification_cards or []),
                session_id=sid,
                weights=dict(parsed.weights or {}),
                weights_explanation=parsed.explanation,
                requirement_summary=summarize_requirements(parsed),
                debug_llm=_debug_llm_payload(trace, debug_on),
            ),
        )

    pool = repo.load()
    sel = retrieve_candidates(parsed, pool)
    outcome = validate_and_select(parsed, sel.sorted_by_category)

    md = render_final_markdown(parsed, outcome, polish=False)

    store.append_message(sid, "assistant", md[:12000], meta={"type": "recommendation", "status": outcome.status})

    reason_lines: list[str] = []
    if parsed.explanation:
        reason_lines.append(parsed.explanation)

    compat_notes = list((outcome.compatibility_check or {}).get("warnings") or [])
    risk_notes = list((outcome.risk_check or {}).get("warnings") or [])

    data = RecommendResponseData(
        need_clarification=False,
        session_id=sid,
        requirement_summary=summarize_requirements(parsed),
        weights=dict(parsed.weights or {}),
        weights_explanation=parsed.explanation,
        candidates_preview=sel.top3_preview,
        status=outcome.status,
        final_build=outcome.final_build,
        total_price=outcome.total_price,
        budget_check=outcome.budget_check,
        compatibility_check=outcome.compatibility_check,
        risk_check=outcome.risk_check,
        unmet_constraints=outcome.unmet_constraints,
        alternative_suggestions=outcome.alternative_suggestions,
        recommendation_markdown=md,
        recommendation_reason=reason_lines,
        compatibility_notes=compat_notes,
        risk_notes=risk_notes,
        jd_purchase_links=build_jd_links(outcome.final_build),
        debug_llm=_debug_llm_payload(trace, debug_on),
    )

    msg = "success"
    if outcome.status == "need_user_confirmation":
        msg = "need_user_confirmation"
    elif outcome.status == "failed_with_alternative":
        msg = "failed_with_alternative"

    return RecommendResponse(code=0, message=msg, data=data)
