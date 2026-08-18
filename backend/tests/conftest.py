# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""pytest 公共 fixture：内存 SQLite + TestClient。"""

from collections.abc import Generator
from pathlib import Path

import app.models  # noqa: F401  # type: ignore
import pytest
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    """内存 SQLite 独立会话，测试后清理。"""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture()
def client(
    db_session: Session, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Generator[TestClient, None, None]:
    """带依赖覆盖的 TestClient，并让 Celery 任务同步执行、复用测试 DB。"""

    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    # 附件真实写盘隔离：upload_dir 指向临时目录，测试不留垃圾文件
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))

    # Celery 任务 run_audit_task 用测试 DB 的 session factory（内存 SQLite）
    test_engine = db_session.get_bind()
    test_factory = sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr("app.db.session.SessionLocal", test_factory)

    # Celery eager：delay 同步执行；任务异常不传播（靠任务状态判断）
    from app.tasks.celery_app import celery_app

    monkeypatch.setattr(celery_app.conf, "task_always_eager", True)
    monkeypatch.setattr(celery_app.conf, "task_eager_propagates", False)

    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
