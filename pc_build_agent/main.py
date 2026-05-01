from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from pc_build_agent.models.schemas import RecommendRequest, RecommendResponse
from pc_build_agent.pipeline.orchestrator import recommend


FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(title="京东装机导购 Agent", version="v1")


@app.get("/")
def root() -> FileResponse:
    """导购前端（京东风格静态页）"""
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/pc-build-agent/recommend", response_model=RecommendResponse)
def recommend_endpoint(req: RecommendRequest) -> RecommendResponse:
    return recommend(req)


@app.post("/api/pc-build-agent/parse-requirements")
def parse_stub() -> dict:
    return {"message": "请直接调用 /api/pc-build-agent/recommend（内部已包含需求理解）"}


@app.post("/api/pc-build-agent/render-image")
def render_image_stub() -> dict:
    return {"status": "pending", "image_url": ""}


app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")
