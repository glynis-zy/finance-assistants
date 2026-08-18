"""健康检查接口（运维探针，不挂 /api 前缀）。"""

from fastapi import APIRouter

router = APIRouter(tags=["健康检查"])


@router.get("/health")
def health() -> dict[str, str]:
    """返回服务存活状态。"""
    return {"status": "ok"}
