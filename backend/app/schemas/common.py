"""公共 Schema：统一错误体与分页包装。"""

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ErrorResponse(BaseModel):
    """统一失败响应体（docs/api.md §0.1）。"""

    code: str
    message: str
    request_id: str | None = None


class PageResult(BaseModel, Generic[T]):
    """统一分页包装（docs/api.md §0.2）。"""

    total: int
    page: int
    page_size: int
    items: list[T]
