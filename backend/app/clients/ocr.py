"""OCR 适配层（依赖倒置，厂商可换，见 docs/DESIGN.md §1.4）。

三模式（tech-stack §3）：
- preset：返回预设解析结果，不调外部 API，无需 Key 完整跑通；
- real：调用百度 OCR（baidu_ocr 协议封装），失败即失败；
- auto：先 real，失败回退 preset。
"""

# 厂商响应映射边界（words_result 为厂商自由 JSON 结构）
# pyright: reportUnknownVariableType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnnecessaryIsInstance=false

import logging
import re
from abc import ABC, abstractmethod
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from app.clients.baidu_ocr import BaiduOCRClient
from app.clients.presets import PRESETS
from app.core.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class OCRResult:
    """OCR 解析结果。"""

    doc_type: str
    fields: dict[str, object]
    confidence: float
    mode: str


class OCRClient(ABC):
    """OCR 统一接口。"""

    @abstractmethod
    def parse(self, doc_type: str, file_name: str, content: bytes | None) -> OCRResult:
        """解析附件，返回结构化字段与置信度。"""


class PresetOCR(OCRClient):
    """preset 模式：返回预设结果。"""

    def parse(self, doc_type: str, file_name: str, content: bytes | None) -> OCRResult:
        return OCRResult(
            doc_type=doc_type,
            fields=deepcopy(PRESETS.get(doc_type, {})),
            confidence=0.95,
            mode="preset",
        )


def _normalize_date(raw: object) -> str | None:
    """发票日期 "2016年06月02日" → "2016-06-02"；其他格式原样返回。"""
    if not isinstance(raw, str) or not raw.strip():
        return None
    m = re.fullmatch(r"(\d{4})年(\d{2})月(\d{2})日", raw.strip())
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return raw.strip() or None


def _invoice_fields(words: dict[str, Any]) -> dict[str, object]:
    """增值税发票 words_result → Document Schema 字段（缺失置 None，fail-closed）。"""
    commodities = words.get("CommodityName") or []
    desc = ""
    if isinstance(commodities, list):
        names = [c.get("word") for c in commodities if isinstance(c, dict) and c.get("word")]
        desc = "、".join(str(n) for n in names)
    amount = words.get("AmountInFiguers") or words.get("TotalAmount") or None
    return {
        "invoice_no": words.get("InvoiceNum") or None,
        "amount": amount,
        "buyer_name": words.get("PurchaserName") or None,
        "invoice_date": _normalize_date(words.get("InvoiceDate")),
        "invoice_type": words.get("InvoiceTypeOrg") or words.get("InvoiceType") or None,
        "description": desc or None,
    }


class RealOCR(OCRClient):
    """real 模式：调用百度 OCR（发票专用接口 / 通用 OCR）。"""

    def __init__(self) -> None:
        settings = get_settings()
        self._client = BaiduOCRClient(
            settings.ocr_api_key,
            settings.ocr_secret_key,
            timeout=settings.ocr_timeout_seconds,
        )

    def parse(self, doc_type: str, file_name: str, content: bytes | None) -> OCRResult:
        settings = get_settings()
        if not settings.ocr_api_key or not settings.ocr_secret_key:
            raise RuntimeError("OCR_API_KEY/OCR_SECRET_KEY 未配置，real 模式无法解析")
        if content is None or not content:
            raise RuntimeError("real 模式解析需要附件文件内容")
        if doc_type == "invoice":
            words = self._client.recognize_invoice(content)
            return OCRResult(
                doc_type=doc_type,
                fields=_invoice_fields(words),
                confidence=0.95,
                mode="real",
            )
        # travel / approval：通用 OCR 全文 → 交 LLM extract 结构化
        rows = self._client.recognize_general(content)
        text = "\n".join(str(r.get("words", "")) for r in rows if isinstance(r, dict))
        return OCRResult(
            doc_type=doc_type,
            fields={"raw_text": text or "", "description": (text or "")[:200]},
            confidence=0.9,
            mode="real",
        )


class AutoOCR(OCRClient):
    """auto 模式：先 real，失败回退 preset。"""

    def __init__(self) -> None:
        self._real = RealOCR()
        self._preset = PresetOCR()

    def parse(self, doc_type: str, file_name: str, content: bytes | None) -> OCRResult:
        try:
            return self._real.parse(doc_type, file_name, content)
        except RuntimeError as exc:
            logger.warning("OCR real 失败回退 preset: %s", exc)
            return self._preset.parse(doc_type, file_name, content)


def get_ocr_client() -> OCRClient:
    """按配置返回 OCR 客户端。"""
    settings = get_settings()
    if settings.ocr_mode == "preset":
        return PresetOCR()
    if settings.ocr_mode == "real":
        return RealOCR()
    return AutoOCR()
