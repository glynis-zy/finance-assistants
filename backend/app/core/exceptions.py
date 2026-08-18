"""统一业务异常。

所有业务错误抛出 `AppError` 及其子类，由全局异常处理器转为统一响应体
（docs/api.md §0.1：`{code, message, request_id}`）。
"""

from app.core.errors import ErrorCode


class AppError(Exception):
    """业务异常基类。"""

    def __init__(
        self,
        status_code: int,
        code: ErrorCode,
        message: str,
        detail: list[dict[str, str]] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.detail = detail


class UnauthorizedError(AppError):
    """未登录 / 令牌失效。"""

    def __init__(self, message: str = "未登录或令牌失效") -> None:
        super().__init__(401, ErrorCode.UNAUTHORIZED, message)


class ForbiddenError(AppError):
    """L1 角色权限不足。"""

    def __init__(self, message: str = "无权限执行该操作") -> None:
        super().__init__(403, ErrorCode.FORBIDDEN, message)


class ForbiddenScopeError(AppError):
    """L2 数据越权。"""

    def __init__(self, message: str = "数据越权") -> None:
        super().__init__(403, ErrorCode.FORBIDDEN_SCOPE, message)


class NotFoundError(AppError):
    """资源不存在。"""

    def __init__(self, message: str = "资源不存在") -> None:
        super().__init__(404, ErrorCode.NOT_FOUND, message)


class InvalidStateError(AppError):
    """L3 状态权限不允许。"""

    def __init__(self, message: str = "当前状态不允许该操作") -> None:
        super().__init__(409, ErrorCode.INVALID_STATE, message)


class ResourceConflictError(AppError):
    """资源唯一约束冲突。"""

    def __init__(self, message: str = "资源冲突") -> None:
        super().__init__(409, ErrorCode.RESOURCE_CONFLICT, message)


class ValidationError(AppError):
    """参数校验失败（422）。"""

    def __init__(
        self, message: str = "参数校验失败", detail: list[dict[str, str]] | None = None
    ) -> None:
        super().__init__(422, ErrorCode.VALIDATION_ERROR, message, detail)
