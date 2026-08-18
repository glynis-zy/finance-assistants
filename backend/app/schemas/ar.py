"""应收域 Schema（docs/api.md §4，Stage 4 factors 三字段结构）。"""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ReceivableCreateRequest(BaseModel):
    """登记应收（不传 status，服务端初始化 open）。"""

    customer_id: int
    contract_id: int
    invoice_no: str | None = None
    amount: Decimal = Field(gt=0)
    due_date: date


class PaymentCreateRequest(BaseModel):
    """登记回款。"""

    receivable_id: int
    customer_id: int
    amount: Decimal = Field(gt=0)
    received_at: datetime | None = None
    remark: str | None = None


class CollectionRecordCreateRequest(BaseModel):
    """登记催收记录。"""

    customer_id: int
    channel: str | None = None
    action: str | None = None
    result: str | None = None
    remark: str | None = None
    occurred_at: datetime | None = None


class ReceivableOut(BaseModel):
    """应收列表出参。"""

    model_config = ConfigDict(from_attributes=True)

    receivable_id: int
    customer_id: int
    customer_name: str
    contract_no: str | None
    amount: Decimal
    due_date: date
    overdue_days: int
    status: str
    outstanding_balance: Decimal


class CreatedOut(BaseModel):
    """创建类响应。"""

    id: int
    extra: dict[str, object] = Field(default_factory=dict)


class RiskRankingItemOut(BaseModel):
    """风险排名项。"""

    customer_id: int
    customer_name: str
    risk_score: int
    risk_level: str
    overdue_amount: Decimal | None
    expected_payment_date: date | None
    expected_overdue_days: int | None
    collection_priority: int


class CustomerDetailOut(BaseModel):
    """客户应收明细 + 因子明细。"""

    customer_id: int
    customer_name: str
    receivables: list[dict[str, object]]
    factors: dict[str, object]
    total_score: int
    risk_level: str
    expected_payment_date: date | None
    expected_overdue_days: int | None
    overdue_amount: Decimal | None


class RiskStatusOut(BaseModel):
    """最近一次全量评分任务状态。"""

    status: str  # done/running/queued/failed/never_run
    started_at: datetime | None = None
    finished_at: datetime | None = None
    customer_count: int = 0
    high_risk_count: int = 0
    error: str | None = None
