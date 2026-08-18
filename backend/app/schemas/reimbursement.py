"""报销域 Schema（docs/api.md §2）。金额用 Decimal，Pydantic v2 序列化为字符串。"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ReimbursementItemIn(BaseModel):
    """报销明细入参。"""

    cost_category_id: int
    amount: Decimal
    invoice_key: str | None = None
    description: str | None = None


class ReimbursementCreate(BaseModel):
    """新建/整体更新报销单入参。"""

    department_id: int
    project_id: int | None = None
    total_amount: Decimal
    currency: str = "CNY"
    items: list[ReimbursementItemIn] = Field(min_length=1)
    remark: str | None = None


class ReimbursementItemOut(BaseModel):
    """报销明细出参。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    cost_category_id: int
    amount: Decimal
    invoice_key: str | None
    description: str | None


class AttachmentOut(BaseModel):
    """附件出参。"""

    attachment_id: int
    category: str
    file_name: str
    size: int
    url: str


class UploadResponse(BaseModel):
    """附件上传响应。"""

    attachments: list[AttachmentOut]


class ReimbursementOut(BaseModel):
    """报销单详情出参。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    no: str
    applicant_id: int
    department_id: int
    project_id: int | None
    total_amount: Decimal
    currency: str
    status: str
    remark: str | None
    return_reason: str | None
    submitted_at: datetime | None
    created_at: datetime
    updated_at: datetime
    items: list[ReimbursementItemOut]


class ReimbursementListOut(BaseModel):
    """报销单列表项。"""

    id: int
    no: str
    applicant_name: str
    department_name: str
    project_name: str | None
    total_amount: Decimal
    status: str
    conclusion: str | None
    created_at: datetime


class ReimbursementDetailOut(ReimbursementOut):
    """报销单详情（主信息 + 附件 + 最新结论）。"""

    attachments: list[AttachmentOut] = []
    conclusion: AuditConclusionOut | None = None


class SubmitResponse(BaseModel):
    """提交审核响应。"""

    task_id: int
    reimbursement_id: int
    status: str


class AuditConclusionOut(BaseModel):
    """审核结论出参。"""

    result: str
    recommended_category: dict[str, Any] | None = None
    check_items: list[dict[str, Any]] | None = None
    risk_items: list[dict[str, Any]] | None = None
    reason: str | None = None


class AuditTaskOut(BaseModel):
    """审核任务轮询出参。"""

    task_id: int
    reimbursement_id: int
    status: str
    conclusion: AuditConclusionOut | None = None
    error: str | None = None


class ManualReviewRequest(BaseModel):
    """人工复核入参。"""

    conclusion: Literal["approved", "returned"]
    reason: str = Field(min_length=1)


class ReturnRequest(BaseModel):
    """财务退回入参。"""

    reason: str = Field(min_length=1)
