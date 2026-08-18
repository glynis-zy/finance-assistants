"""配置加载测试。"""

from app.core.config import get_settings


def test_settings_loads() -> None:
    settings = get_settings()
    assert settings.app_name
    assert settings.jwt_algorithm == "HS256"
    assert settings.jwt_expire_minutes > 0


def test_celery_broker_falls_back_to_redis() -> None:
    settings = get_settings()
    assert settings.celery_broker == settings.redis_url
    assert settings.celery_backend == settings.redis_url
