# -*- coding: utf-8 -*-
"""FastAPI 应用入口：仅提供 JSON API 与 OpenAPI 文档，不再托管前端静态资源（前后端分离）。"""
# __future__.annotations：推迟求值类型注解，便于前向引用类型名
from __future__ import annotations

# load_dotenv：在 import 其他业务模块前将 .env 载入 os.environ，供 pydantic-settings 读取
from dotenv import load_dotenv

load_dotenv()

# FastAPI：Web 框架，负责路由、依赖注入、OpenAPI 生成
from fastapi import FastAPI
# JSONResponse：显式返回 application/json 的根路径说明
from fastapi.responses import JSONResponse
# CORSMiddleware：为浏览器跨域 XHR/fetch 添加 Access-Control-* 响应头
from fastapi.middleware.cors import CORSMiddleware

# 请求/响应 Pydantic 模型：与前端 JSON 契约一致
from pc_build_agent.models.schemas import RecommendRequest, RecommendResponse
# 编排入口：单接口内完成会话、解析、召回、校验、渲染
from pc_build_agent.pipeline.orchestrator import recommend
# 读取 CORS 白名单等配置
from pc_build_agent.config import settings


def _parse_cors_origins(raw: str) -> list[str]:
    """将逗号分隔的 Origin 字符串解析为列表；自动 strip 并丢弃空项。"""
    # 若未配置则 raw 可能为空，split 后过滤空白
    return [part.strip() for part in (raw or "").split(",") if part.strip()]


# 创建应用实例：title/version 会显示在 /docs 文档页标题
app = FastAPI(title="京东装机导购 Agent API", version="v1")


# 根据配置注册 CORS：仅当白名单非空时启用，避免生产误配为「无限制」
_cors_list = _parse_cors_origins(settings.pc_guide_cors_origins)
if _cors_list:
    # add_middleware：后添加的中间件更先执行（洋葱外层）；此处只处理 CORS 预检与实际响应头
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_list,  # 允许的浏览器 Origin，必须与前端页面地址完全一致（含端口）
        allow_credentials=False,  # 当前 API 不依赖 Cookie；False 时前端可用默认 fetch 无需 credentials
        allow_methods=["*"],  # 允许 OPTIONS 预检及 GET/POST 等动词（开发便利；可按需收紧）
        allow_headers=["*"],  # 允许任意请求头（如 Content-Type: application/json）
    )


@app.get("/")
def root() -> JSONResponse:
    """根路径：返回服务说明 JSON；前端已独立部署，此处不再返回 index.html。"""
    # content：给运维或开发者快速确认服务名与文档入口
    return JSONResponse(
        {
            "service": "pc-build-agent-api",
            "docs": "/docs",
            "health": "/health",
            "recommend": "/api/pc-build-agent/recommend",
            "note": "前端请单独启动（见仓库 README）；通过 PC_GUIDE_CORS_ORIGINS 配置跨域白名单。",
        }
    )


@app.get("/health")
def health() -> dict:
    """健康检查：负载均衡或 K8s 探针可轮询此接口，无需鉴权。"""
    # 固定结构，便于脚本判断 {"status":"ok"}
    return {"status": "ok"}


@app.post("/api/pc-build-agent/recommend", response_model=RecommendResponse)
def recommend_endpoint(req: RecommendRequest) -> RecommendResponse:
    """核心推荐接口：写入用户消息、调用 LLM 解析需求、召回、校验并返回结构化结果。"""
    # recommend 为纯函数式编排，异常在内部已部分捕获并转为 code/message
    return recommend(req)


@app.post("/api/pc-build-agent/parse-requirements")
def parse_stub() -> dict:
    """占位接口：提示客户端统一走 recommend（历史设计预留，避免旧客户端误调）。"""
    # 明确文案，减少重复维护两套解析链
    return {"message": "请直接调用 /api/pc-build-agent/recommend（内部已包含需求理解）"}


@app.post("/api/pc-build-agent/render-image")
def render_image_stub() -> dict:
    """效果图渲染占位：V1 未实现，返回 pending 与空 URL。"""
    # 与研发设计文档中「预留渲染」一致，便于前端分支判断
    return {"status": "pending", "image_url": ""}


# 注意：已移除 StaticFiles 挂载与 FileResponse 返回前端 HTML，实现前后端仓库内职责分离。
# 前端位于 frontend/ 目录，请使用「静态文件服务器」单独监听端口（如 python -m http.server 5173）。
