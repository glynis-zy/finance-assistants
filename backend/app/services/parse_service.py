"""解析流水线：OCR 看懂 → LLM 理解 → Pydantic 校验 → 快照持久化。

审核重放默认读取已保存解析快照（doc_parse_result），不重新调用 OCR/LLM
（docs/requirements.md §5 确定性 / 可审计性）。
"""

from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clients import llm as llm_module
from app.clients import ocr as ocr_module
from app.core.config import get_settings
from app.domain.risk_engine.types import ParsedDocument
from app.models.base_data import Attachment
from app.models.enums import DocParseStatus
from app.models.reimbursement import DocParseResult, Reimbursement
from app.schemas.documents import DOC_SCHEMAS


def _validate(category: str, fields: dict[str, Any]) -> BaseModel | None:
    """用 Pydantic 强校验字段，失败返回 None（字段缺失/非法）。"""
    schema = DOC_SCHEMAS.get(category)
    if schema is None:
        return None
    try:
        return schema.model_validate(fields)
    except ValidationError:
        return None


def parse_attachments(
    db: Session, reimbursement: Reimbursement, attachments: list[Attachment]
) -> list[ParsedDocument]:
    """解析报销单全部附件，返回 ParsedDocument 列表（重放时复用快照）。"""
    settings = get_settings()
    ocr = ocr_module.get_ocr_client()
    llm = llm_module.get_llm_client()
    results: list[ParsedDocument] = []

    for att in attachments:
        # 快照重放：已有解析结果则复用，不重调 OCR/LLM
        existing = db.scalar(
            select(DocParseResult).where(
                DocParseResult.attachment_id == att.id,
                DocParseResult.status == DocParseStatus.DONE.value,
            )
        )
        if existing is not None and existing.parsed_json is not None:
            confidence = existing.confidence or 0.0
            low = confidence < settings.ocr_confidence_threshold
            data = None if low else _validate(att.category, existing.parsed_json)
            results.append(
                ParsedDocument(
                    category=att.category,
                    confidence=confidence,
                    low_confidence=low,
                    data=data,
                )
            )
            continue

        # 新解析：OCR
        try:
            ocr_result = ocr.parse(att.category, f"attachment-{att.id}", None)
        except Exception:
            ocr_result = None
        if ocr_result is None:
            results.append(
                ParsedDocument(
                    category=att.category,
                    confidence=0.0,
                    low_confidence=True,
                    data=None,
                    error="OCR 解析失败",
                )
            )
            continue

        low = ocr_result.confidence < settings.ocr_confidence_threshold

        # LLM 结构化提取（失败不阻断，降级为字段缺失 → fail-closed）
        try:
            fields = llm.extract(att.category, ocr_result.fields)
        except Exception:
            fields = {}

        data = None if low else _validate(att.category, fields)

        db.add(
            DocParseResult(
                attachment_id=att.id,
                reimbursement_id=reimbursement.id,
                doc_type=att.category,
                parsed_json=fields,
                confidence=ocr_result.confidence,
                status=DocParseStatus.DONE.value,
            )
        )

        results.append(
            ParsedDocument(
                category=att.category,
                confidence=ocr_result.confidence,
                low_confidence=low,
                data=data,
            )
        )

    return results
