"""数据库 engine 与会话工厂。"""

from collections.abc import Generator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

_settings = get_settings()

_connect_args: dict[str, object] = {}
if _settings.database_url.startswith("sqlite"):
    # SQLite 单文件并发访问需要关闭线程检查
    _connect_args["check_same_thread"] = False

engine: Engine = create_engine(
    _settings.database_url, connect_args=_connect_args, pool_pre_ping=True
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖：每个请求一个 Session，用完关闭。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
