# -*- coding: utf-8 -*-
"""应用级配置：从环境变量与可选 .env 文件加载，供 main / services / agents 读取。"""
# pathlib.Path：跨平台路径对象，便于拼接 SQLite、JSON 数据文件路径
from pathlib import Path

# pydantic_settings：把环境变量自动校验并映射到 Settings 字段类型
from pydantic_settings import BaseSettings, SettingsConfigDict

# __file__ 为本文件路径；resolve() 解析为绝对路径；parent 为 pc_build_agent 包目录
_ROOT = Path(__file__).resolve().parent


class Settings(BaseSettings):
    """全局配置模型：字段名小写对应环境变量名大写加下划线（如 deepseek_api_key -> DEEPSEEK_API_KEY）。"""

    # 允许从项目根 .env 读取 UTF-8 编码；extra="ignore" 表示忽略未声明的环境变量，避免启动报错
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # DeepSeek（或兼容 OpenAI Chat Completions 的网关）API 密钥；空字符串表示未配置，调用解析将失败
    deepseek_api_key: str = ""
    # Chat Completions 接口基址，默认官方 DeepSeek
    deepseek_base_url: str = "https://api.deepseek.com"
    # 默认对话模型标识，可按账号可用模型调整
    deepseek_model: str = "deepseek-chat"

    # 会话 SQLite 文件路径：默认放在仓库根下 data/ 目录（与 README 一致）
    pc_guide_db_path: Path = _ROOT.parent / "data" / "pc_guide_sessions.sqlite"
    # Mock 商品池 JSON：相对包内 data 目录
    pc_guide_products_path: Path = _ROOT / "data" / "products.json"
    # 规则库 JSON：功耗、板型、冷排等校验规则
    pc_guide_rules_path: Path = _ROOT / "data" / "rules.json"
    # 性能需求理解规则库 JSON：使用场景、软件/游戏、性能重点、配件权重
    pc_guide_performance_rules_path: Path = _ROOT / "rules" / "performance_rules.json"

    # 为 True 时 recommend 等接口可在 data.debug_llm 附带模型请求/响应轨迹（生产勿开）
    pc_guide_debug_llm: bool = False

    # 前后端分离：浏览器跨域访问 API 时允许的 Origin 列表，逗号分隔；须含前端页面完整协议+主机+端口
    # 例：http://127.0.0.1:5173,http://localhost:5173
    pc_guide_cors_origins: str = (
        "http://127.0.0.1:5173,http://localhost:5173,"
        "http://127.0.0.1:8080,http://localhost:8080,"
        "http://127.0.0.1:3000,http://localhost:3000"
    )


# 进程内单例：各模块 `from pc_build_agent.config import settings` 共享同一配置实例
settings = Settings()
