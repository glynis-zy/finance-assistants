"""LLM 适配层（依赖倒置，厂商可换）。

LLM 只做：字段结构化提取（Pydantic 校验）、科目推荐规则盲区兜底。不做任何结论判定
（docs/DESIGN.md §1.1）。LLM 失败不得阻断审核链，按 fail-closed 降级为「字段缺失」风险项。
real 模式失败直接失败；auto 模式失败回退 preset。
"""

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.clients.deepseek_llm import DeepSeekClient
from app.core.config import get_settings

logger = logging.getLogger(__name__)

# 各票据类型期望提取的字段（与 presets / schemas.documents 对齐，LLM 提取后仍走 Pydantic 校验）
_FIELD_LISTS: dict[str, str] = {
    "invoice": "invoice_no, amount, buyer_name, invoice_date, invoice_type, description",
    "travel": "trip_no, from_city, to_city, trip_date, amount, description",
    "approval": "approval_no, approval_amount, project_name, applicant_name, approval_date",
}

# 科目推荐白名单（业务层 DB 科目为准；LLM 超出白名单直接拒绝，不产生不存在科目）
_CATEGORY_WHITELIST: dict[str, str] = {
    "TRAVEL": "差旅费",
    "OFFICE": "办公费",
    "ENTERTAIN": "业务招待费",
    "MEETING": "会议费",
}

_EXTRACT_SYSTEM = (
    "你是财务票据信息提取助手。只输出一个 JSON 对象，不要输出任何其他内容。"
    '金额字段用字符串（如 "1000.00"），日期格式 YYYY-MM-DD，无法确定的字段置 null。'
)
_CATEGORY_SYSTEM = (
    '你是费用科目分类助手。只输出一个 JSON 对象，格式为 {"category_code": "TRAVEL", '
    '"confidence": 0.9}，不要输出任何其他内容。科目代码只能从以下选择：'
    + "、".join(f"{k}({v})" for k, v in _CATEGORY_WHITELIST.items())
    + "。confidence 为 0~1 之间的小数，表示对分类的判断把握。"
)


@dataclass
class CategoryCandidate:
    """科目推荐候选。"""

    category_code: str
    confidence: float


class LLMClient(ABC):
    """LLM 统一接口。"""

    @abstractmethod
    def extract(self, doc_type: str, fields: dict[str, object]) -> dict[str, object]:
        """对 OCR 结果做字段结构化提取（调用方 Pydantic 强校验）。"""

    @abstractmethod
    def recommend_category(self, description: str) -> CategoryCandidate | None:
        """科目推荐规则盲区兜底，返回候选 + 置信度。"""


class PresetLLM(LLMClient):
    """preset 模式：字段原样返回；科目兜底返回固定候选。"""

    def extract(self, doc_type: str, fields: dict[str, object]) -> dict[str, object]:
        return dict(fields)

    def recommend_category(self, description: str) -> CategoryCandidate | None:
        return CategoryCandidate(category_code="TRAVEL", confidence=0.9)


class RealLLM(LLMClient):
    """real 模式：调用 DeepSeek（OpenAI-compatible），失败即失败。"""

    def __init__(self) -> None:
        settings = get_settings()
        self._client = DeepSeekClient(
            settings.llm_api_key,
            settings.llm_base_url,
            settings.llm_model,
            timeout=settings.llm_timeout_seconds,
        )

    def extract(self, doc_type: str, fields: dict[str, object]) -> dict[str, object]:
        settings = get_settings()
        if not settings.llm_api_key:
            raise RuntimeError("LLM_API_KEY 未配置，real 模式无法提取")
        field_list = _FIELD_LISTS.get(doc_type)
        if field_list is None:
            raise RuntimeError(f"real 模式不支持文档类型: {doc_type}")
        user = (
            f"请从以下 OCR 结果中提取{doc_type}信息，输出严格 JSON。"
            f"键必须为：{field_list}。\nOCR 结果：\n{json.dumps(fields, ensure_ascii=False)}"
        )
        return self._client.chat_json(_EXTRACT_SYSTEM, user)

    def recommend_category(self, description: str) -> CategoryCandidate | None:
        settings = get_settings()
        if not settings.llm_api_key:
            raise RuntimeError("LLM_API_KEY 未配置，real 模式无法推荐")
        user = f"报销描述：{description}。请给出最合适的费用科目。"
        result = self._client.chat_json(_CATEGORY_SYSTEM, user)
        code = result.get("category_code")
        if not isinstance(code, str) or code not in _CATEGORY_WHITELIST:
            logger.warning("LLM 推荐科目不在白名单，拒绝: %s", code)
            return None
        try:
            confidence = float(result.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        return CategoryCandidate(category_code=code, confidence=min(max(confidence, 0.0), 1.0))


class AutoLLM(LLMClient):
    """auto 模式：先 real，失败回退 preset。"""

    def __init__(self) -> None:
        self._real = RealLLM()
        self._preset = PresetLLM()

    def extract(self, doc_type: str, fields: dict[str, object]) -> dict[str, object]:
        try:
            return self._real.extract(doc_type, fields)
        except RuntimeError as exc:
            logger.warning("LLM real 失败回退 preset: %s", exc)
            return self._preset.extract(doc_type, fields)

    def recommend_category(self, description: str) -> CategoryCandidate | None:
        try:
            return self._real.recommend_category(description)
        except RuntimeError as exc:
            logger.warning("LLM real 失败回退 preset: %s", exc)
            return self._preset.recommend_category(description)


def get_llm_client() -> LLMClient:
    """按配置返回 LLM 客户端。"""
    settings = get_settings()
    if settings.llm_mode == "preset":
        return PresetLLM()
    if settings.llm_mode == "real":
        return RealLLM()
    return AutoLLM()
