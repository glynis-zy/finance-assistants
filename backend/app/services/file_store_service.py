"""附件物理存储服务：真实写盘 / 读取 / 删除，防路径穿越。

约定（Stage 6A）：
- storage_path 只存「相对 upload_dir 的安全文件名」（如 ab12cd34.png），不做任何拼接用户输入；
- 原始文件名仅作为 FileStore.file_name 元数据展示；
- 读取/删除前 resolve 校验，确保目标在 upload_dir 内（防穿越）。
"""

from pathlib import Path
from uuid import uuid4

from app.core.config import get_settings


def _upload_dir() -> Path:
    """upload_dir 绝对化（容器内 WORKDIR=/app → /app/uploads）。"""
    settings = get_settings()
    return Path(settings.upload_dir).resolve()


def safe_storage_name(original_name: str | None) -> str:
    """随机安全存储名（保留原扩展名的小写形式；忽略路径部分防穿越）。"""
    ext = Path(original_name or "").suffix.lower()
    if len(ext) > 12 or not ext.replace(".", "").isalnum():
        ext = ""
    return f"{uuid4().hex}{ext}"


def save_upload(content: bytes, original_name: str | None) -> str:
    """真实写入 upload_dir，返回相对 storage_path（可恢复路径）。"""
    root = _upload_dir()
    root.mkdir(parents=True, exist_ok=True)
    name = safe_storage_name(original_name)
    (root / name).write_bytes(content)
    return name


def _resolve_safe(storage_path: str) -> Path:
    """校验并返回 upload_dir 内的目标路径（防路径穿越）。"""
    root = _upload_dir()
    target = (root / storage_path).resolve()
    if not str(target).startswith(str(root)):
        raise ValueError("非法存储路径")
    return target


def read_upload(storage_path: str) -> bytes:
    """从共享存储读取 bytes（worker 与 backend 同 volume）。"""
    return _resolve_safe(storage_path).read_bytes()


def delete_upload(storage_path: str) -> None:
    """删除真实文件（不存在静默）。"""
    _resolve_safe(storage_path).unlink(missing_ok=True)
