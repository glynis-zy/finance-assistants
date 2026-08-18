"""科目推荐（docs/requirements.md §4.2.2）：规则映射 → LLM 兜底 → 置信度判断。

规则命中保持确定性；LLM 只给候选无最终拍板权；未达置信度阈值 → 无法推荐（manual_review）。
"""

from dataclasses import dataclass, field
from typing import Any, cast

from sqlalchemy.orm import Session

from app.clients.llm import LLMClient
from app.core.config import get_settings
from app.domain.risk_engine.types import ParsedDocument
from app.models.base_data import CostCategory


@dataclass
class CategoryRecommendation:
    """科目推荐结果。"""

    category: CostCategory | None
    source: str  # rule / llm / none
    confidence: float | None
    candidates: list[dict[str, Any]] = field(default_factory=lambda: [])


def _descriptions(docs: list[ParsedDocument]) -> list[str]:
    out: list[str] = []
    for d in docs:
        if d.data is not None:
            desc = d.data.model_dump().get("description")
            if desc:
                out.append(str(desc))
    return out


def _rule_match(desc: str, categories: list[CostCategory]) -> CostCategory | None:
    """规则映射：描述关键词命中科目 keyword_map。"""
    for cat in categories:
        if not cat.enabled:
            continue
        keywords: list[str] = cast(list[str], cat.keyword_map) if cat.keyword_map else []
        for kw in keywords:
            if kw in desc:
                return cat
    return None


def _find_category(code: str, categories: list[CostCategory]) -> CostCategory | None:
    for cat in categories:
        if cat.code == code:
            return cat
    return None


def recommend_category(
    db: Session, docs: list[ParsedDocument], categories: list[CostCategory], llm: LLMClient
) -> CategoryRecommendation:
    """推荐费用科目，按规则 → LLM → 置信度顺序。"""
    settings = get_settings()
    descriptions = _descriptions(docs)

    # 1. 规则映射（确定性）
    for desc in descriptions:
        cat = _rule_match(desc, categories)
        if cat is not None:
            return CategoryRecommendation(
                category=cat,
                source="rule",
                confidence=1.0,
                candidates=[{"code": cat.code, "name": cat.name, "confidence": 1.0}],
            )

    # 2. LLM 兜底
    desc = descriptions[0] if descriptions else ""
    try:
        candidate = llm.recommend_category(desc)
    except Exception:
        candidate = None
    if candidate is not None:
        cat = _find_category(candidate.category_code, categories)
        if (
            cat is not None
            and cat.enabled
            and candidate.confidence >= settings.llm_confidence_threshold
        ):
            return CategoryRecommendation(
                category=cat,
                source="llm",
                confidence=candidate.confidence,
                candidates=[
                    {"code": cat.code, "name": cat.name, "confidence": candidate.confidence}
                ],
            )
        # 低置信度或科目无效 → 无法推荐
        return CategoryRecommendation(
            category=None,
            source="llm",
            confidence=candidate.confidence,
            candidates=[{"code": candidate.category_code, "confidence": candidate.confidence}],
        )

    return CategoryRecommendation(category=None, source="none", confidence=None, candidates=[])
