from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


_ROOT = Path(__file__).resolve().parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    pc_guide_db_path: Path = _ROOT.parent / "data" / "pc_guide_sessions.sqlite"
    pc_guide_products_path: Path = _ROOT / "data" / "products.json"
    pc_guide_rules_path: Path = _ROOT / "data" / "rules.json"

    # 为 True 时在接口 data.debug_llm 中附带最近一次模型调用的请求/响应（含 reasoning_content，若上游返回）
    pc_guide_debug_llm: bool = False


settings = Settings()
