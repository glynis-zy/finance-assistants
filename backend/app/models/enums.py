"""业务枚举常量（与 docs/api.md §0.5 一致）。

状态字段以字符串落库，枚举仅作为代码内取值契约，避免 DB 层枚举迁移负担。
"""

from enum import StrEnum


class ReimbursementStatus(StrEnum):
    """报销单状态机。"""

    DRAFT = "draft"
    PENDING = "pending"
    MANUAL_REVIEW = "manual_review"
    APPROVED = "approved"
    RETURNED = "returned"


class AuditResult(StrEnum):
    """审核结论。"""

    APPROVED = "approved"
    RETURNED = "returned"
    MANUAL_REVIEW = "manual_review"


class TaskStatus(StrEnum):
    """审核任务状态。"""

    QUEUED = "queued"
    PARSING = "parsing"
    DONE = "done"
    FAILED = "failed"


class DocParseStatus(StrEnum):
    """文档解析状态。"""

    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"


class AttachmentCategory(StrEnum):
    """附件分类。"""

    INVOICE = "invoice"
    TRAVEL = "travel"
    APPROVAL = "approval"


class DeviationLevel(StrEnum):
    """预算偏差等级（独立枚举，不与预警共用）。"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class AlertLevel(StrEnum):
    """预警等级。"""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertType(StrEnum):
    """预警类型。"""

    BUDGET = "budget"
    AR = "ar"


class RiskLevel(StrEnum):
    """应收风险档位。"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ReceivableStatus(StrEnum):
    """应收单状态（由服务端按累计到账维护，逾期为动态判断不作为状态）。"""

    OPEN = "open"
    PARTIAL = "partial"
    SETTLED = "settled"


class LedgerSource(StrEnum):
    """台账来源。"""

    REIMB = "reimb"
    IMPORT = "import"
