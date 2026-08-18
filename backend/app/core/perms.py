"""权限码常量与角色默认权限映射。

权限码与 docs/api.md §0.4 权限码总表一致；角色默认授权用于 seed 与 L1 校验。
"""

from enum import StrEnum

from app.models.rbac import SysUser


class Permission(StrEnum):
    """权限码（domain:action）。"""

    REIMB_CREATE = "reimb:create"
    REIMB_VIEW_OWN = "reimb:view_own"
    REIMB_AUDIT = "reimb:audit"
    REIMB_MANUAL_REVIEW = "reimb:manual_review"
    LEDGER_VIEW = "ledger:view"
    LEDGER_IMPORT = "ledger:import"
    BUDGET_MANAGE = "budget:manage"
    BUDGET_VIEW = "budget:view"
    THRESHOLD_MANAGE = "threshold:manage"
    AR_MANAGE = "ar:manage"
    AR_VIEW = "ar:view"
    USER_MANAGE = "user:manage"
    ROLE_MANAGE = "role:manage"
    SYS_MANAGE = "sys:manage"
    COST_CATEGORY_MANAGE = "cost_category:manage"
    ALERT_VIEW = "alert:view"
    ALERT_MANAGE = "alert:manage"


# 角色 → 默认权限码（finance 含 budget:view，v1.0 冻结口径）
ROLE_PERMISSIONS: dict[str, list[str]] = {
    "applicant": [Permission.REIMB_CREATE.value, Permission.REIMB_VIEW_OWN.value],
    "finance": [
        Permission.REIMB_AUDIT.value,
        Permission.REIMB_MANUAL_REVIEW.value,
        Permission.LEDGER_VIEW.value,
        Permission.LEDGER_IMPORT.value,
        Permission.BUDGET_VIEW.value,
        Permission.ALERT_VIEW.value,
    ],
    "budget_manager": [
        Permission.BUDGET_MANAGE.value,
        Permission.BUDGET_VIEW.value,
        Permission.THRESHOLD_MANAGE.value,
        Permission.ALERT_VIEW.value,
    ],
    "ar_specialist": [
        Permission.AR_MANAGE.value,
        Permission.AR_VIEW.value,
        Permission.ALERT_VIEW.value,
    ],
    "admin": [
        Permission.USER_MANAGE.value,
        Permission.ROLE_MANAGE.value,
        Permission.SYS_MANAGE.value,
        Permission.COST_CATEGORY_MANAGE.value,
        Permission.ALERT_VIEW.value,
        Permission.ALERT_MANAGE.value,
    ],
}


def user_permissions(user: SysUser) -> set[str]:
    """展开用户全部角色所拥有的权限码集合。"""
    perms: set[str] = set()
    for role in user.roles:
        for perm in role.permissions:
            perms.add(perm.code)
    return perms
