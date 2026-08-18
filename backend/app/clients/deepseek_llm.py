"""DeepSeek LLM 协议封装（OpenAI-compatible，官方文档核对 2026-08）。

- base_url 默认 https://api.deepseek.com，路径 /chat/completions
- 认证：Authorization: Bearer <api_key>
- 严格 JSON 输出：response_format={"type":"json_object"} + 系统提示要求 JSON
- timeout / HTTP 错误 / 非 JSON / 字段非法 → RuntimeError（auto 模式回退 preset）
- 异常消息不含 api_key（详见 _safe_message）
"""

# 厂商 JSON 响应边界（json.loads 返回 Any 属适配层正常放宽）
# pyright: reportUnknownVariableType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false

import contextlib
import json
import logging
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)


def _safe_message(exc: BaseException, body: str) -> str:
    """构造不含 api_key 的错误消息（HTTP 状态码 / DeepSeek 错误体 code 截断）。"""
    if isinstance(exc, urllib.error.HTTPError):
        return f"DeepSeek API HTTP {exc.code}"
    try:
        parsed = json.loads(body)
        err = parsed.get("error") if isinstance(parsed, dict) else None
        if isinstance(err, dict):
            return f"DeepSeek API {err.get('type', 'error')}: {str(err.get('message', ''))[:200]}"
    except (json.JSONDecodeError, UnicodeDecodeError):
        pass
    return f"DeepSeek API {exc.__class__.__name__}"


class DeepSeekClient:
    """DeepSeek 对话补全客户端（标准库 urllib，不引第三方依赖）。"""

    def __init__(self, api_key: str, base_url: str, model: str, timeout: int = 30) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout

    def chat_json(self, system: str, user: str) -> dict[str, Any]:
        """一次对话，要求模型只返回严格 JSON 对象。"""
        url = self._base_url + "/chat/completions"
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
            "stream": False,
            "response_format": {"type": "json_object"},  # 严格 JSON 输出
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            body = ""
            with contextlib.suppress(OSError):
                body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(_safe_message(exc, body)) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(f"DeepSeek 网络错误: {exc.__class__.__name__}") from exc
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("DeepSeek 响应非 JSON") from exc
        if not isinstance(data, dict):
            raise RuntimeError("DeepSeek 响应非法")
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("DeepSeek 响应缺少 choices/message/content") from exc
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("DeepSeek 返回空内容")
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise RuntimeError("DeepSeek 返回非 JSON 内容") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError("DeepSeek JSON 内容非法")
        return parsed
