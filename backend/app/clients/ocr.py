"""OCR 适配层（依赖倒置，厂商可换，见 docs/DESIGN.md §1.4）。

三模式（tech-stack §3）：
- preset：返回预设解析结果，不调外部 API，无需 Key 完整跑通；
- real：调用真实厂商（百度），未配置 Key 则失败；
- auto：先 real，失败回退 preset。
"""

from abc import ABC, abstractmethod
from copy import deepcopy
from dataclasses import dataclass

from app.clients.presets import PRESETS
from app.core.config import get_settings


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


class RealOCR(OCRClient):
    """real 模式：调用百度 OCR（Stage 2 未接入，未配置 Key 即失败）。"""

    def parse(self, doc_type: str, file_name: str, content: bytes | None) -> OCRResult:
        settings = get_settings()
        if not settings.ocr_api_key:
            raise RuntimeError("OCR_API_KEY 未配置，real 模式无法解析")
        # Stage 2 未接入真实 OCR 厂商；接入后在此返回真实结果
        raise RuntimeError("real OCR 未实现")


class AutoOCR(OCRClient):
    """auto 模式：先 real，失败回退 preset。"""

    def __init__(self) -> None:
        self._real = RealOCR()
        self._preset = PresetOCR()

    def parse(self, doc_type: str, file_name: str, content: bytes | None) -> OCRResult:
        try:
            return self._real.parse(doc_type, file_name, content)
        except RuntimeError:
            return self._preset.parse(doc_type, file_name, content)


def get_ocr_client() -> OCRClient:
    """按配置返回 OCR 客户端。"""
    settings = get_settings()
    if settings.ocr_mode == "preset":
        return PresetOCR()
    if settings.ocr_mode == "real":
        return RealOCR()
    return AutoOCR()
