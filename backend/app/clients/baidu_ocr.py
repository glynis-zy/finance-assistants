"""百度 OCR 协议封装（厂商边界，业务层不出现百度专有协议）。
- 凭证 → access_token（默认 30 天，进程内缓存，过期前 5 分钟自动刷新）
- invoice → 增值税发票识别 vat_invoice（结构化字段）
- travel / approval → 通用文字识别 general_basic（全文文本，交 LLM 提取）
- timeout / HTTP 错误 / 厂商业务错误（error_code）均抛 RuntimeError
- 日志与异常消息禁止出现 Key / Secret / token（详见 _safe_message）

接口依据百度官方文档（2026-08 核对）：
- token: https://aip.baidubce.com/oauth/2.0/token
- vat_invoice: https://aip.baidubce.com/rest/2.0/ocr/v1/vat_invoice
- general_basic: https://aip.baidubce.com/rest/2.0/ocr/v1/general_basic
"""

# 厂商 JSON 响应边界（json.loads 返回 Any 属适配层正常放宽）
# pyright: reportUnknownVariableType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false

import base64
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

_TOKEN_URL = "https://aip.baidubce.com/oauth/2.0/token"
_INVOICE_URL = "https://aip.baidubce.com/rest/2.0/ocr/v1/vat_invoice"
_GENERAL_URL = "https://aip.baidubce.com/rest/2.0/ocr/v1/general_basic"
# token 有效期默认 30 天；到期前 5 分钟视为过期提前刷新
_TOKEN_EXPIRE_PAD_SECONDS = 300


def _safe_message(prefix: str, body: dict[str, Any]) -> str:
    """构造不含凭证/token 的错误消息（厂商错误码与描述可记，密钥字段剔除）。"""
    code = body.get("error_code", body.get("error"))
    msg = body.get("error_msg", body.get("error_description", ""))
    return f"{prefix} {code}: {msg}".strip()


class BaiduOCRClient:
    """百度 OCR REST 客户端（标准库 urllib，不引第三方依赖）。"""

    def __init__(self, api_key: str, secret_key: str, timeout: int = 15) -> None:
        self._api_key = api_key
        self._secret_key = secret_key
        self._timeout = timeout
        self._token: str | None = None
        self._token_expire_at: float = 0.0

    # ------------------------------------------------------------ token

    def get_access_token(self) -> str:
        """获取 access_token（进程内缓存，过期前自动刷新）。"""
        now = time.monotonic()
        if self._token is not None and now < self._token_expire_at:
            return self._token
        params = urllib.parse.urlencode(
            {
                "grant_type": "client_credentials",
                "client_id": self._api_key,
                "client_secret": self._secret_key,
            }
        )
        body = self._post_form(_TOKEN_URL, params)
        token = body.get("access_token")
        if not token:
            raise RuntimeError(_safe_message("百度 OCR 获取 token 失败", body))
        self._token = str(token)
        try:
            expire_in = max(int(body.get("expires_in", 0)), _TOKEN_EXPIRE_PAD_SECONDS)
        except (TypeError, ValueError):
            expire_in = _TOKEN_EXPIRE_PAD_SECONDS
        self._token_expire_at = now + expire_in
        return self._token

    # ------------------------------------------------------------ 识别

    def recognize_invoice(self, image: bytes) -> dict[str, Any]:
        """增值税发票识别：返回 words_result 结构化字段 dict。"""
        token = self.get_access_token()
        result = self._ocr_post(_INVOICE_URL, token, image)
        words = result.get("words_result")
        if not isinstance(words, dict):
            raise RuntimeError("百度 OCR 发票结果非法：缺少 words_result")
        return words

    def recognize_general(self, image: bytes) -> list[dict[str, Any]]:
        """通用文字识别：返回 words_result 行列表（全文拼接由调用方处理）。"""
        token = self.get_access_token()
        result = self._ocr_post(_GENERAL_URL, token, image)
        words = result.get("words_result")
        if not isinstance(words, list):
            raise RuntimeError("百度 OCR 通用结果非法：缺少 words_result")
        return words

    # ------------------------------------------------------------ HTTP

    def _ocr_post(self, url: str, token: str, image: bytes) -> dict[str, Any]:
        """OCR 识别请求：image 需 base64 后 urlencode（官方要求）。"""
        image_b64 = base64.b64encode(image).decode("ascii")
        form = urllib.parse.urlencode({"image": image_b64})
        return self._post_form(url + "?access_token=" + urllib.parse.quote(token), form)

    def _post_form(self, url: str, form: str) -> dict[str, Any]:
        """application/x-www-form-urlencoded POST，统一错误处理。"""
        req = urllib.request.Request(
            url,
            data=form.encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"百度 OCR HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(f"百度 OCR 网络错误: {exc.__class__.__name__}") from exc
        try:
            body = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("百度 OCR 响应非 JSON") from exc
        if not isinstance(body, dict):
            raise RuntimeError("百度 OCR 响应非法")
        if "error_code" in body:
            raise RuntimeError(_safe_message("百度 OCR 业务错误", body))
        return body
