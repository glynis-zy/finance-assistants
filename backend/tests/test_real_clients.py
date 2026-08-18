# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""RealOCR（百度）/ RealLLM（DeepSeek）mock 测试（Stage 6B）。

自动测试不依赖真实厂商在线：mock urllib urlopen 覆盖 token/成功/timeout/厂商错误/
非法响应/auto fallback/real 不 fallback 全分支。
"""

import io
import json
import urllib.error
import urllib.request
from http.client import HTTPMessage
from typing import Any

import pytest
from app.clients.llm import AutoLLM, CategoryCandidate, RealLLM
from app.clients.ocr import AutoOCR, RealOCR
from app.core.config import get_settings


def _http_error(code: int) -> urllib.error.HTTPError:
    """构造可被适配层捕获的 HTTPError（合法 hdrs/fp 参数）。"""
    return urllib.error.HTTPError("http://x", code, "err", HTTPMessage(), io.BytesIO(b"{}"))


class FakeResp:
    """mock urllib 响应。"""

    def __init__(self, body: bytes, status: int = 200) -> None:
        self.body = body
        self.status = status

    def read(self) -> bytes:
        return self.body

    def __enter__(self) -> "FakeResp":
        return self

    def __exit__(self, *args: object) -> bool:
        return False


_TOKEN_OK = json.dumps({"access_token": "tok-abc", "expires_in": 2592000}).encode()
_INVOICE_OK = json.dumps(
    {
        "words_result": {
            "InvoiceNum": "14641426",
            "AmountInFiguers": "100000.00",
            "PurchaserName": "百度时代网络技术(北京)有限公司",
            "InvoiceDate": "2016年06月02日",
            "InvoiceTypeOrg": "上海增值税专用发票",
            "CommodityName": [{"row": "1", "word": "信息服务费"}],
        }
    }
).encode()
_GENERAL_OK = json.dumps(
    {"words_result": [{"words": "北京"}, {"words": "上海"}, {"words": "高铁票"}]}
).encode()


def _enable_keys(monkeypatch: pytest.MonkeyPatch, ocr: bool = True, llm: bool = True) -> None:
    """配置 real 凭证（mock 测试只验协议，不产生真实调用）。"""
    settings = get_settings()
    if ocr:
        monkeypatch.setattr(settings, "ocr_api_key", "test-api-key")
        monkeypatch.setattr(settings, "ocr_secret_key", "test-secret-key")
        monkeypatch.setattr(settings, "ocr_mode", "real")
    if llm:
        monkeypatch.setattr(settings, "llm_api_key", "test-llm-key")
        monkeypatch.setattr(settings, "llm_mode", "real")


def _mock_urlopen(
    monkeypatch: pytest.MonkeyPatch, responses: list[Any], target: str = ""
) -> tuple[list[str], list[bytes | None]]:
    """依次返回 responses（FakeResp 或抛出的 Exception）；记录请求 URL 与 body。"""

    calls: list[str] = []
    bodies: list[bytes | None] = []
    it = iter(responses)

    def fake(req: Any, timeout: float | None = None) -> Any:
        calls.append(getattr(req, "full_url", ""))
        bodies.append(getattr(req, "data", None))
        item = next(it)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    return calls, bodies


# ---------------------------------------------------------------- RealOCR


def test_real_ocr_invoice_success_and_token_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    """发票成功：token 获取（含 URL 参数）+ vat_invoice 映射；第二次复用缓存 token。"""
    _enable_keys(monkeypatch)
    responses: list[Any] = [FakeResp(_TOKEN_OK), FakeResp(_INVOICE_OK), FakeResp(_INVOICE_OK)]
    calls, bodies = _mock_urlopen(monkeypatch, responses)

    client = RealOCR()
    r1 = client.parse("invoice", "发票.png", b"img-bytes")
    r2 = client.parse("invoice", "发票.png", b"img-bytes")

    assert r1.mode == "real" and r1.fields["invoice_no"] == "14641426"
    assert r1.fields["amount"] == "100000.00"
    assert r1.fields["buyer_name"] == "百度时代网络技术(北京)有限公司"
    assert r1.fields["invoice_date"] == "2016-06-02"  # 日期规范化
    assert r1.fields["description"] == "信息服务费"
    assert r2.fields["invoice_no"] == "14641426"
    # token 仅首次获取（3 次调用 = 1 token + 2 invoice），凭证在 form body（不进日志）
    token_idx = [i for i, c in enumerate(calls) if "oauth/2.0/token" in c]
    assert len(token_idx) == 1
    token_body = (bodies[token_idx[0]] or b"").decode("utf-8")
    assert "grant_type=client_credentials" in token_body
    assert "client_id=test-api-key" in token_body
    assert "client_secret=test-secret-key" in token_body


def test_real_ocr_general_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """travel/approval 用通用 OCR：全文文本入 raw_text，交 LLM 结构化。"""
    _enable_keys(monkeypatch)
    _mock_urlopen(monkeypatch, [FakeResp(_TOKEN_OK), FakeResp(_GENERAL_OK)])
    r = RealOCR().parse("travel", "行程单.png", b"img")
    assert r.mode == "real"
    raw_text = str(r.fields["raw_text"])
    assert "北京" in raw_text and "上海" in raw_text
    assert isinstance(raw_text, str)


def test_real_ocr_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """timeout → RuntimeError（real 失败即失败）。"""
    _enable_keys(monkeypatch)
    _mock_urlopen(monkeypatch, [FakeResp(_TOKEN_OK), TimeoutError("timeout")])
    with pytest.raises(RuntimeError, match="网络错误"):
        RealOCR().parse("invoice", "a.png", b"x")


def test_real_ocr_vendor_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """厂商业务错误（error_code）→ RuntimeError。"""
    _enable_keys(monkeypatch)
    err = json.dumps({"error_code": 17, "error_msg": "每天请求量超限"}).encode()
    _mock_urlopen(monkeypatch, [FakeResp(_TOKEN_OK), FakeResp(err)])
    with pytest.raises(RuntimeError, match="每天请求量超限"):
        RealOCR().parse("invoice", "a.png", b"x")


def test_real_ocr_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP 非 2xx → RuntimeError。"""
    _enable_keys(monkeypatch)
    _mock_urlopen(monkeypatch, [_http_error(500)])
    with pytest.raises(RuntimeError, match="HTTP 500"):
        RealOCR().parse("invoice", "a.png", b"x")


def test_real_ocr_invalid_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """非法响应（非 JSON）→ RuntimeError。"""
    _enable_keys(monkeypatch)
    _mock_urlopen(monkeypatch, [FakeResp(b"<html>not json")])
    with pytest.raises(RuntimeError, match="非 JSON"):
        RealOCR().parse("invoice", "a.png", b"x")


def test_real_ocr_missing_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """未配置 Key：real 直接失败（不发 HTTP）。"""
    settings = get_settings()
    monkeypatch.setattr(settings, "ocr_api_key", "")
    monkeypatch.setattr(settings, "ocr_secret_key", "")
    with pytest.raises(RuntimeError, match="未配置"):
        RealOCR().parse("invoice", "a.png", b"x")


def test_real_ocr_requires_content(monkeypatch: pytest.MonkeyPatch) -> None:
    """real 模式解析需要附件内容。"""
    _enable_keys(monkeypatch)
    with pytest.raises(RuntimeError, match="需要附件"):
        RealOCR().parse("invoice", "a.png", None)


def test_auto_ocr_fallback_to_preset(monkeypatch: pytest.MonkeyPatch) -> None:
    """auto 模式：real 失败回退 preset（不破坏 preset 行为）。"""
    settings = get_settings()
    monkeypatch.setattr(settings, "ocr_api_key", "k")
    monkeypatch.setattr(settings, "ocr_secret_key", "s")
    monkeypatch.setattr(settings, "ocr_mode", "auto")
    _mock_urlopen(monkeypatch, [TimeoutError("net")])
    r = AutoOCR().parse("invoice", "a.png", b"x")
    assert r.mode == "preset"
    assert r.fields["invoice_no"] == "INV-000001"  # 预设值


def test_real_ocr_no_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """real 模式失败不 fallback：直接抛错。"""
    _enable_keys(monkeypatch)
    _mock_urlopen(monkeypatch, [TimeoutError("net")])
    with pytest.raises(RuntimeError):
        RealOCR().parse("invoice", "a.png", b"x")


# ---------------------------------------------------------------- RealLLM


def _llm_resp(content: str) -> FakeResp:
    return FakeResp(json.dumps({"choices": [{"message": {"content": content}}]}).encode())


def test_real_llm_extract_json_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """extract：DeepSeek 返回严格 JSON → dict。"""
    _enable_keys(monkeypatch)
    content = json.dumps({"invoice_no": "X-1", "amount": "100.00"}, ensure_ascii=False)
    _mock_urlopen(monkeypatch, [_llm_resp(content)])
    out = RealLLM().extract("invoice", {"raw_text": "发票"})
    assert out["invoice_no"] == "X-1" and out["amount"] == "100.00"


def test_real_llm_extract_non_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM 返回非 JSON 内容 → RuntimeError。"""
    _enable_keys(monkeypatch)
    _mock_urlopen(monkeypatch, [_llm_resp("很抱歉，我无法…")])
    with pytest.raises(RuntimeError, match="非 JSON"):
        RealLLM().extract("invoice", {})


def test_real_llm_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """API HTTP 错误 → RuntimeError。"""
    _enable_keys(monkeypatch)
    _mock_urlopen(
        monkeypatch, [_http_error(401)]
    )
    with pytest.raises(RuntimeError, match="401"):
        RealLLM().extract("invoice", {})


def test_real_llm_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """timeout → RuntimeError。"""
    _enable_keys(monkeypatch)
    _mock_urlopen(monkeypatch, [TimeoutError("slow")])
    with pytest.raises(RuntimeError, match="网络错误"):
        RealLLM().extract("invoice", {})


def test_real_llm_invalid_schema_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """响应缺少 choices/message → RuntimeError。"""
    _enable_keys(monkeypatch)
    _mock_urlopen(monkeypatch, [FakeResp(json.dumps({"foo": 1}).encode())])
    with pytest.raises(RuntimeError, match="choices"):
        RealLLM().extract("invoice", {})


def test_real_llm_category_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """科目推荐成功：白名单 code + confidence。"""
    _enable_keys(monkeypatch)
    _mock_urlopen(monkeypatch, [_llm_resp('{"category_code": "OFFICE", "confidence": 0.85}')])
    cand = RealLLM().recommend_category("采购办公用品")
    assert cand == CategoryCandidate(category_code="OFFICE", confidence=0.85)


def test_real_llm_category_unknown_code_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM 产生不存在科目 → None（不产生不存在的科目后直接通过）。"""
    _enable_keys(monkeypatch)
    _mock_urlopen(monkeypatch, [_llm_resp('{"category_code": "FOO", "confidence": 0.99}')])
    assert RealLLM().recommend_category("随便") is None


def test_real_llm_category_bad_confidence(monkeypatch: pytest.MonkeyPatch) -> None:
    """confidence 非法 → 0.0（业务层低于阈值 → manual_review）。"""
    _enable_keys(monkeypatch)
    _mock_urlopen(monkeypatch, [_llm_resp('{"category_code": "TRAVEL", "confidence": "abc"}')])
    cand = RealLLM().recommend_category("高铁")
    assert cand is not None and cand.confidence == 0.0


def test_real_llm_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """未配置 Key：real 直接失败。"""
    settings = get_settings()
    monkeypatch.setattr(settings, "llm_api_key", "")
    with pytest.raises(RuntimeError, match="未配置"):
        RealLLM().extract("invoice", {})


def test_auto_llm_fallback_to_preset(monkeypatch: pytest.MonkeyPatch) -> None:
    """auto 模式：real 失败回退 preset。"""
    settings = get_settings()
    monkeypatch.setattr(settings, "llm_api_key", "k")
    monkeypatch.setattr(settings, "llm_mode", "auto")
    _mock_urlopen(monkeypatch, [TimeoutError("net"), TimeoutError("net")])  # extract + recommend
    auto = AutoLLM()
    assert auto.extract("invoice", {"raw_text": "x"}) == {"raw_text": "x"}  # preset 原样
    cand = auto.recommend_category("高铁")
    assert cand == CategoryCandidate(category_code="TRAVEL", confidence=0.9)


def test_real_llm_no_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """real 模式失败不 fallback。"""
    _enable_keys(monkeypatch)
    _mock_urlopen(monkeypatch, [TimeoutError("net")])
    with pytest.raises(RuntimeError):
        RealLLM().extract("invoice", {})


def test_llm_never_decides_result(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM 永远不能决定 approved/returned：推荐只返回 code+confidence 候选。"""
    _enable_keys(monkeypatch)
    _mock_urlopen(monkeypatch, [_llm_resp('{"category_code": "TRAVEL", "confidence": 0.8}')])
    cand = RealLLM().recommend_category("差旅")
    assert cand is not None
    # 推荐结果只有 code/confidence，无 result/status 字段（dataclass 结构保证）
    assert set(vars(cand)) == {"category_code", "confidence"}
