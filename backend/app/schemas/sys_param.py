"""系统参数 Schema。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SysParamOut(BaseModel):
    """系统参数响应。"""

    model_config = ConfigDict(from_attributes=True)

    key: str
    value: str
    value_type: str
    description: str | None = None
    updated_by: str | None = None
    updated_at: datetime


class SysParamUpdateRequest(BaseModel):
    """系统参数更新请求。"""

    value: str = Field(min_length=1, max_length=512)
