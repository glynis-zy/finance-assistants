"""SQLAlchemy ORM 模型（共享基础层 + 三助手域 + 预警域）。

导入所有模型，确保 `Base.metadata` 完整，供 Alembic 与建表使用。
"""

from app.models.alert import Alert, Notification
from app.models.ar_domain import (
    ArPayment,
    ArReceivable,
    ArRiskScore,
    CollectionRecord,
)
from app.models.base_data import (
    Attachment,
    AuditLog,
    Budget,
    BudgetAdjustment,
    Contract,
    CostCategory,
    Customer,
    ExpenseLedger,
    FileStore,
    OrgDepartment,
    Project,
    SysParam,
)
from app.models.budget_domain import BudgetDeviation, BudgetSnapshot, StatSignal
from app.models.rbac import RolePermission, SysPermission, SysRole, SysUser, UserRole
from app.models.reimbursement import (
    AuditConclusion,
    AuditTask,
    DocParseResult,
    Reimbursement,
    ReimbursementAttachment,
    ReimbursementItem,
)

__all__ = [
    "Alert",
    "Notification",
    "ArPayment",
    "ArReceivable",
    "ArRiskScore",
    "CollectionRecord",
    "Attachment",
    "AuditLog",
    "Budget",
    "BudgetAdjustment",
    "Contract",
    "CostCategory",
    "Customer",
    "ExpenseLedger",
    "FileStore",
    "OrgDepartment",
    "Project",
    "SysParam",
    "BudgetDeviation",
    "BudgetSnapshot",
    "StatSignal",
    "RolePermission",
    "SysPermission",
    "SysRole",
    "SysUser",
    "UserRole",
    "AuditConclusion",
    "AuditTask",
    "DocParseResult",
    "Reimbursement",
    "ReimbursementAttachment",
    "ReimbursementItem",
]
