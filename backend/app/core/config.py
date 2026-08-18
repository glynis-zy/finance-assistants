"""应用配置。

统一从环境变量 / .env 读取，`get_settings()` 单例缓存。
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置项。

    数据库默认 SQLite 便于本地免 Docker 跑通链路；生产切 MySQL 8。
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # 数据库（`sqlite:///./dev.db` 或 `mysql+pymysql://user:pwd@host:3306/db`）
    database_url: str = "sqlite:///./dev.db"

    # JWT 认证
    jwt_secret_key: str = "dev-secret-change-me-in-prod-0123456789abcdef"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 120

    # Redis / Celery（Redis 仅作 broker，权威状态落 DB）
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = ""
    celery_result_backend: str = ""

    # 应用
    app_name: str = "财务智能助手平台"
    api_prefix: str = "/api"
    debug: bool = False

    @property
    def celery_broker(self) -> str:
        """Celery broker URL，缺省回退到 redis_url。"""
        return self.celery_broker_url or self.redis_url

    @property
    def celery_backend(self) -> str:
        """Celery result backend，缺省回退到 redis_url。"""
        return self.celery_result_backend or self.redis_url


@lru_cache
def get_settings() -> Settings:
    """返回缓存的应用配置单例。"""
    return Settings()
