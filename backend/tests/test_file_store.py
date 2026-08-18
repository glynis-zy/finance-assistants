# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportOptionalMemberAccess=false
"""附件真实持久化测试（Stage 6A）：

- 上传真实写盘（随机安全文件名，原始名仅元数据）
- 解析时 worker 从共享存储读取 bytes（OCRClient.parse 收到 content）
- 删除附件：无引用时清理真实文件
- 防路径穿越
"""

from pathlib import Path

import pytest
from app.core.config import get_settings
from app.models.base_data import Attachment, FileStore
from app.models.reimbursement import ReimbursementAttachment
from app.services import file_store_service
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.helpers import login, make_user, seed_base


def _upload(client: TestClient, token: str, rid: int, name: str = "invoice.png") -> int:
    resp = client.post(
        f"/api/reimbursements/{rid}/attachments",
        headers={"Authorization": f"Bearer {token}"},
        files={"files": (name, b"fake-image-bytes-123", "image/png")},
        data={"categories": "invoice"},
    )
    assert resp.status_code == 201, resp.text
    return int(resp.json()["attachments"][0]["attachment_id"])


def test_upload_writes_real_file(client: TestClient, db_session: Session) -> None:
    """上传 → 真实文件落盘，storage_path 为安全随机名，原始名仅元数据。"""
    base = seed_base(db_session)
    make_user(db_session, "app", "applicant", name="张三")
    token = login(client, "app")
    rid = client.post(
        "/api/reimbursements",
        json={
            "department_id": base.dept.id,
            "project_id": base.proj.id,
            "total_amount": "100.00",
            "items": [{"cost_category_id": base.travel.id, "amount": "100.00"}],
        },
        headers={"Authorization": f"Bearer {token}"},
    ).json()["id"]

    att_id = _upload(client, token, rid, name="../../evil.png")
    att = db_session.get(Attachment, att_id)
    fs = db_session.get(FileStore, att.file_store_id)
    # 防穿越：storage_path 不含路径分隔符（随机名 + 安全扩展名）
    assert "/" not in fs.storage_path and ".." not in fs.storage_path
    assert fs.storage_path.endswith(".png")
    assert fs.file_name == "../../evil.png"  # 原始名仅元数据
    assert fs.size == len(b"fake-image-bytes-123")
    # 真实文件可读回且内容一致
    content = file_store_service.read_upload(fs.storage_path)
    assert content == b"fake-image-bytes-123"
    root = Path(get_settings().upload_dir)
    assert (root / fs.storage_path).exists()


def test_path_traversal_rejected(client: TestClient, db_session: Session) -> None:
    """读取/删除越过 upload_dir 的路径 → 拒绝。"""
    with pytest.raises(ValueError):
        file_store_service.read_upload("../../etc/passwd")
    with pytest.raises(ValueError):
        file_store_service.delete_upload("..\\..\\windows\\win.ini")


def test_worker_reads_uploaded_file(client: TestClient, db_session: Session) -> None:
    """worker（同共享存储）可读取 backend 上传的文件 bytes，且传入 OCRClient.parse。"""
    base = seed_base(db_session)
    make_user(db_session, "app", "applicant", name="张三")
    token = login(client, "app")
    rid = client.post(
        "/api/reimbursements",
        json={
            "department_id": base.dept.id,
            "project_id": base.proj.id,
            "total_amount": "1000.00",
            "items": [{"cost_category_id": base.travel.id, "amount": "1000.00"}],
        },
        headers={"Authorization": f"Bearer {token}"},
    ).json()["id"]
    _upload(client, token, rid, name="发票.png")

    # 模拟 worker：独立打开 session + 从 FileStore 读取 bytes → 传给 OCRClient
    att = db_session.scalar(select(Attachment).order_by(Attachment.id.desc()))
    assert att is not None
    received: dict[str, object] = {}

    class SpyOCR:
        def parse(self, doc_type: str, file_name: str, content: bytes | None) -> object:
            received["file_name"] = file_name
            received["content"] = content
            from app.clients.ocr import OCRResult

            return OCRResult(
                doc_type=doc_type, fields={"amount": "1000.00"}, confidence=0.99, mode="spy"
            )

    from app.models.reimbursement import Reimbursement
    from app.services import parse_service

    original = parse_service.ocr_module.get_ocr_client
    parse_service.ocr_module.get_ocr_client = lambda: SpyOCR()  # type: ignore[assignment]
    try:
        reimb = db_session.get(Reimbursement, rid)
        assert reimb is not None
        parse_service.parse_attachments(db_session, reimb, [att])
    finally:
        parse_service.ocr_module.get_ocr_client = original  # type: ignore[assignment]

    assert received["file_name"] == "发票.png"
    assert received["content"] == b"fake-image-bytes-123"


def test_delete_removes_file_when_unreferenced(client: TestClient, db_session: Session) -> None:
    """删除附件：关联删除 + 无引用时真实文件被清理。"""
    base = seed_base(db_session)
    make_user(db_session, "app", "applicant", name="张三")
    token = login(client, "app")
    rid = client.post(
        "/api/reimbursements",
        json={
            "department_id": base.dept.id,
            "project_id": base.proj.id,
            "total_amount": "100.00",
            "items": [{"cost_category_id": base.travel.id, "amount": "100.00"}],
        },
        headers={"Authorization": f"Bearer {token}"},
    ).json()["id"]
    att_id = _upload(client, token, rid)
    att = db_session.get(Attachment, att_id)
    fs = db_session.get(FileStore, att.file_store_id)
    file_path = Path(get_settings().upload_dir) / fs.storage_path
    assert file_path.exists()

    resp = client.delete(
        f"/api/reimbursements/{rid}/attachments/{att_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 204, resp.text
    assert not file_path.exists()  # 真实文件已清理
    assert db_session.get(Attachment, att_id) is None
    assert db_session.get(FileStore, fs.id) is None
    ref = db_session.scalar(
        select(ReimbursementAttachment).where(ReimbursementAttachment.attachment_id == att_id)
    )
    assert ref is None
