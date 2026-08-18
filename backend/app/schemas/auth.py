"""认证接口 Schema。"""

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    """登录请求。"""

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class UserInfo(BaseModel):
    """当前用户信息（含角色与权限码，前端渲染菜单/按钮用）。"""

    id: int
    username: str
    name: str
    roles: list[str]
    permissions: list[str]


class LoginResponse(BaseModel):
    """登录响应。"""

    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserInfo
