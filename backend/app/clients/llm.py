"""LLM 适配层（依赖倒置，厂商可换）。

LLM 只做：字段结构化提取（Pydantic 校验）、科目推荐规则盲区兜底。不做任何结论判定
（docs/DESIGN.md §1.1）。LLM 失败不得阻断审核链，按 fail-closed 降级为「字段缺失」风险项。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.core.config import get_settings


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
    """real 模式：调用 DeepSeek（Stage 2 未接入，未配置 Key 即失败）。"""

    def extract(self, doc_type: str, fields: dict[str, object]) -> dict[str, object]:
        settings = get_settings()
        if not settings.llm_api_key:
            raise RuntimeError("LLM_API_KEY 未配置，real 模式无法提取")
        raise RuntimeError("real LLM 未实现")

    def recommend_category(self, description: str) -> CategoryCandidate | None:
        settings = get_settings()
        if not settings.llm_api_key:
            raise RuntimeError("LLM_API_KEY 未配置，real 模式无法推荐")
        raise RuntimeError("real LLM 未实现")


class AutoLLM(LLMClient):
    """auto 模式：先 real，失败回退 preset。"""

    def __init__(self) -> None:
        self._real = RealLLM()
        self._preset = PresetLLM()

    def extract(self, doc_type: str, fields: dict[str, object]) -> dict[str, object]:
        try:
            return self._real.extract(doc_type, fields)
        except RuntimeError:
            return self._preset.extract(doc_type, fields)

    def recommend_category(self, description: str) -> CategoryCandidate | None:
        try:
            return self._real.recommend_category(description)
        except RuntimeError:
            return self._preset.recommend_category(description)


def get_llm_client() -> LLMClient:
    """按配置返回 LLM 客户端。"""
    settings = get_settings()
    if settings.llm_mode == "preset":
        return PresetLLM()
    if settings.llm_mode == "real":
        return RealLLM()
    return AutoLLM()
