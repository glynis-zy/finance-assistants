"""认证服务。"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import UnauthorizedError
from app.core.security import verify_password
from app.models.rbac import SysUser


def authenticate(db: Session, username: str, password: str) -> SysUser:
    """校验用户名密码，返回用户；失败抛 401。"""
    user = db.scalar(select(SysUser).where(SysUser.username == username))
    if user is None or not verify_password(password, user.password_hash):
        raise UnauthorizedError("用户名或密码错误")
    if not user.enabled:
        raise UnauthorizedError("账号已停用")
    return user
