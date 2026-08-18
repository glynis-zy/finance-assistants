"""FastAPI 应用入口。"""

import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.exceptions import AppError
from app.routers import ar, auth, budgets, deviations, health, reimbursements, sys_params

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)


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
