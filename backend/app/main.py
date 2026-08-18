"""FastAPI 应用入口（含前端静态资源托管）。"""

import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import get_settings
from app.core.exceptions import AppError
from app.routers import (
    admin,
    alerts,
    ar,
    auth,
    base_data,
    budgets,
    deviations,
    health,
    ledger,
    reimbursements,
    sys_params,
)

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """业务异常 → 统一响应体（code/message/request_id）。"""
    content: dict[str, Any] = {
        "code": exc.code.value,
        "message": exc.message,
        "request_id": str(uuid.uuid4()),
    }
    if exc.detail is not None:
        content["detail"] = exc.detail
    return JSONResponse(status_code=exc.status_code, content=content)


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Pydantic 校验失败 → 422 VALIDATION_ERROR。"""
    detail = [
        {"field": ".".join(str(x) for x in e.get("loc", [])), "message": str(e.get("msg", ""))}
        for e in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={
            "code": "VALIDATION_ERROR",
            "message": "参数校验失败",
            "request_id": str(uuid.uuid4()),
            "detail": detail,
        },
    )


@app.exception_handler(Exception)
async def internal_handler(request: Request, exc: Exception) -> JSONResponse:
    """未捕获异常兜底 500。"""
    return JSONResponse(
        status_code=500,
        content={
            "code": "INTERNAL_ERROR",
            "message": "服务内部错误",
            "request_id": str(uuid.uuid4()),
        },
    )


app.include_router(health.router)
app.include_router(auth.router, prefix=settings.api_prefix)
app.include_router(sys_params.router, prefix=settings.api_prefix)
app.include_router(reimbursements.router, prefix=settings.api_prefix)
app.include_router(reimbursements.audit_router, prefix=settings.api_prefix)
app.include_router(budgets.router, prefix=settings.api_prefix)
app.include_router(deviations.router, prefix=settings.api_prefix)
app.include_router(ar.router, prefix=settings.api_prefix)
app.include_router(alerts.router, prefix=settings.api_prefix)
app.include_router(base_data.router, prefix=settings.api_prefix)
app.include_router(ledger.router, prefix=settings.api_prefix)
app.include_router(admin.router, prefix=settings.api_prefix)


# 前端静态资源（原生单页，无构建链）
if FRONTEND_DIR.is_dir():
    app.mount(
        "/static",
        StaticFiles(directory=str(FRONTEND_DIR)),
        name="frontend",
    )


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    """单页入口（未匹配前端路由时兜底）。"""
    return FileResponse(str(FRONTEND_DIR / "index.html"))
