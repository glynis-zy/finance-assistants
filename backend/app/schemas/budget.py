"""预算域 Schema（docs/api.md §3，Stage 3 年度口径修正）。

金额用 Decimal，Pydantic v2 序列化为字符串。
"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def validate_allocation_curve(curve: list[Decimal] | None) -> list[Decimal] | None:
    """校验分摊曲线：长度 12、每项 >= 0、合计 = 1（允许 1e-6 量级误差）。

    `None` 视为未提供（仅兼容历史数据，新建必填）。
    """
    if curve is None:
        return None
    if len(curve) != 12:
        raise ValueError("allocation_curve 长度必须为 12")
    total = Decimal(0)
    for v in curve:
        if v < 0:
            raise ValueError("allocation_curve 每项必须 >= 0")
        total += v
    if abs(total - Decimal(1)) > Decimal("0.0001"):
        raise ValueError("allocation_curve 合计必须为 1（允许 0.0001 误差）")
    return curve


class BudgetCreateRequest(BaseModel):
    """新建预算（POST /api/budgets）。"""

    department_id: int
    project_id: int
    cost_category_id: int
    budget_year: str = Field(pattern=r"^\d{4}$")
    amount: Decimal = Field(gt=0)
    allocation_curve: list[Decimal] = Field(min_length=12, max_length=12)

    @model_validator(mode="after")
    def _check_curve(self) -> "BudgetCreateRequest":
        validate_allocation_curve(self.allocation_curve)
        return self


class BudgetUpdateRequest(BaseModel):
    """调整预算（PUT /api/budgets/{id}），金额与曲线均可选。"""

    amount: Decimal | None = Field(default=None, gt=0)
    allocation_curve: list[Decimal] | None = None
    reason: str | None = Field(default=None, max_length=256)

    @model_validator(mode="after")
    def _check_curve(self) -> "BudgetUpdateRequest":
        if self.allocation_curve is not None:
            validate_allocation_curve(self.allocation_curve)
        return self


class BudgetOut(BaseModel):
    """预算出参。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    department_id: int
    project_id: int
    cost_category_id: int
    budget_year: str
    amount: Decimal
    allocation_curve: list[float] | None
    created_at: datetime
    updated_at: datetime


class BudgetCreatedOut(BaseModel):
    """新建/调整预算响应（contract：budget_id/period/amount）。"""

    budget_id: int
    budget_year: str
    amount: Decimal
    adjustment_id: int | None = None


class DeviationOut(BaseModel):
    """偏差明细出参。"""

    id: int
    department_id: int
    department_name: str
    project_id: int
    project_name: str
    cost_category_id: int
    cost_category_name: str
    period: str
    budget_amount: Decimal
    actual_amount: Decimal
    deviation_amount: Decimal
    deviation_ratio: Decimal | None
    level: str
    owner: str | None
    trigger_reason: str | None


class DeviationGroupOut(BaseModel):
    """偏差汇总分组。"""

    key: int
    name: str
    budget_total: Decimal
    actual_total: Decimal
    deviation_amount: Decimal
    deviation_ratio: Decimal
    level: str


class MonitorStatusOut(BaseModel):
    """监控任务状态。"""

    last_run_at: datetime | None
    status: str  # done/queued/running/failed
    snapshot: dict[str, object] | None = None
