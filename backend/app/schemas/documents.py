"""文档结构化字段（Pydantic 强校验，禁止自由文本字段）。"""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class InvoiceData(BaseModel):
    """发票结构化字段。"""

    invoice_no: str
    amount: Decimal
    buyer_name: str
    invoice_date: date
    invoice_type: str
    description: str | None = None


class TravelData(BaseModel):
    """行程单结构化字段。"""

    trip_no: str
    from_city: str
    to_city: str
    trip_date: date
    amount: Decimal
    description: str | None = None


class ApprovalData(BaseModel):
    """审批单结构化字段。"""

    approval_no: str
    approval_amount: Decimal
    project_name: str
    applicant_name: str
    approval_date: date


DOC_SCHEMAS: dict[str, type[BaseModel]] = {
    "invoice": InvoiceData,
    "travel": TravelData,
    "approval": ApprovalData,
}
