"""全局配置。

改造说明：上游项目依赖 PostgreSQL + Redis + 通义千问，本机无 Docker / MySQL / Redis，
且 DeepSeek 不提供 Embedding 接口，因此这里收敛为「单机可运行」配置：
    - 存储：SQLite（无需额外服务）
    - 检索：本地 BM25（无需向量库 / Embedding 模型）
    - 推理：DeepSeek（OpenAI 兼容协议）
"""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"


class Settings(BaseSettings):
    PROJECT_NAME: str = "智能客服 Agent 系统"
    VERSION: str = "1.0.0"
    API_PREFIX: str = "/api/v1"

    # ---------- 大模型 ----------
    LLM_BASE_URL: str = "https://api.deepseek.com"
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "deepseek-flash"
    LLM_TIMEOUT: int = 90

    # ---------- 存储 ----------
    DB_PATH: Path = DATA_DIR / "app.db"
    KB_DIR: Path = DATA_DIR / "knowledge"
    UPLOAD_DIR: Path = DATA_DIR / "uploads"

    # ---------- 认证 ----------
    SECRET_KEY: str = "please-change-this-secret"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24

    # ---------- 退款风控阈值 ----------
    HIGH_RISK_REFUND_AMOUNT: float = 2000.0
    MEDIUM_RISK_REFUND_AMOUNT: float = 500.0

    # ---------- 检索参数 ----------
    CHUNK_SIZE: int = 420
    CHUNK_OVERLAP: int = 80
    TOP_K: int = 4
    MIN_COVERAGE: float = 0.15  # 查询词 IDF 覆盖率下限，低于该值视为「知识库未命中」

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def DATABASE_URL(self) -> str:
        return f"sqlite+aiosqlite:///{self.DB_PATH.as_posix()}"


settings = Settings()
