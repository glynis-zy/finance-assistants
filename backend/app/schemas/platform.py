"""平台共享 Schema（docs/api.md §5 预警 / §6 基础数据 / 系统管理）。"""

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AlertOut(BaseModel):
    """预警出参。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    alert_type: str
    level: str
    summary: str
    detail: dict[str, Any] | None
    created_at: datetime
    read: bool


class AlertReadOut(BaseModel):
    """标记已读响应。"""

    id: int
    read: bool


class CostCategoryCreate(BaseModel):
    """新建科目。"""

    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=64)
    parent_id: int | None = None
    enabled: bool = True
    invoice_type_map: dict[str, Any] | None = None
    keyword_map: dict[str, Any] | None = None


class CostCategoryUpdate(BaseModel):
    """更新科目（code 不可改）。"""

    name: str | None = None
    parent_id: int | None = None
    enabled: bool | None = None
    invoice_type_map: dict[str, Any] | None = None
    keyword_map: dict[str, Any] | None = None


class CostCategoryOut(BaseModel):
    """科目出参。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    parent_id: int | None
    enabled: bool
    invoice_type_map: Any | None
    keyword_map: Any | None  # JSON 列边界：seed 存 list，接口可兼容 dict/list


class DepartmentOut(BaseModel):
    """部门出参。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    manager: str | None


class ProjectOut(BaseModel):
    """项目出参。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    department_id: int
    owner: str | None


class CustomerOut(BaseModel):
    """客户出参。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    rating: str | None
    credit: Decimal | None


class ContractOut(BaseModel):
    """合同出参。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    contract_no: str
    customer_id: int
    amount: Decimal
    payment_term: int
    status: str


class LedgerOut(BaseModel):
    """台账出参。"""

    id: int
    source: str
    cost_category_id: int
    cost_category_name: str
    department_id: int
    department_name: str
    project_id: int | None
    project_name: str | None
    period: str
    amount: Decimal
    occurred_at: datetime
    ref_no: str | None


class LedgerImportResult(BaseModel):
    """台账导入结果。"""

    imported_count: int
    failed_rows: list[dict[str, object]] = Field(default_factory=list[dict[str, object]])


class UserCreate(BaseModel):
    """新建用户。"""

    username: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=6, max_length=128)
    roles: list[str] = Field(min_length=1)


class UserOut(BaseModel):
    """用户出参。"""

    id: int
    username: str
    name: str
    roles: list[str]
    enabled: bool


class RoleOut(BaseModel):
    """角色出参（含权限码）。"""

    code: str
    name: str
    permissions: list[str]
