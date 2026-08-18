"""报销业务服务（docs/api.md §2）：CRUD + 附件 + 提交 + 复核 + 退回。

落实三级权限：L1 在路由层（require_perm），L2 行级过滤与 L3 状态守卫在本层。
"""

# Celery task 的 .delay 为动态属性，第三方边界豁免
# pyright: reportFunctionMemberAccess=false

import contextlib
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import (
    ForbiddenError,
    ForbiddenScopeError,
    NotFoundError,
    ValidationError,
)
from app.core.perms import user_permissions
from app.core.state_guard import REIMBURSEMENT_ACTION_STATES, ensure_state
from app.models.base_data import Attachment, FileStore
from app.models.enums import ReimbursementStatus
from app.models.rbac import SysUser
from app.models.reimbursement import (
    AuditConclusion,
    AuditTask,
    Reimbursement,
    ReimbursementAttachment,
    ReimbursementItem,
)
from app.schemas.reimbursement import ReimbursementCreate
from app.services import file_store_service
from app.services.audit_flow_service import get_conclusion, write_ledger
from app.tasks.audit import run_audit_task

_VALID_CATEGORIES = {"invoice", "travel", "approval"}


def _gen_no() -> str:
    return f"REIM-{datetime.now(UTC).strftime('%Y%m%d')}-{uuid4().hex[:6].upper()}"


def _ensure_view(user: SysUser, reimb: Reimbursement) -> None:
    """L2 数据权限：财务看全部，申请人仅本人。"""
    perms = user_permissions(user)
    if "reimb:audit" in perms:
        return
    if "reimb:view_own" in perms and reimb.applicant_id == user.id:
        return
    raise ForbiddenScopeError()


def _ensure_owner(user: SysUser, reimb: Reimbursement) -> None:
    """写操作仅本人。"""
    if reimb.applicant_id != user.id:
        raise ForbiddenScopeError()


def _check_amount(items: list[ReimbursementItem], total: Decimal) -> None:
    if sum(i.amount for i in items) != total:
        raise ValidationError("明细金额合计与报销总额不一致")


def _load_items(db: Session, reimbursement_id: int) -> list[ReimbursementItem]:
    return list(
        db.scalars(
            select(ReimbursementItem).where(ReimbursementItem.reimbursement_id == reimbursement_id)
        )
    )


def create_reimbursement(db: Session, user: SysUser, payload: ReimbursementCreate) -> Reimbursement:
    """新建报销单（draft）。"""
    items = [ReimbursementItem(**i.model_dump()) for i in payload.items]
    _check_amount(items, payload.total_amount)
    reimb = Reimbursement(
        no=_gen_no(),
        applicant_id=user.id,
        department_id=payload.department_id,
        project_id=payload.project_id,
        total_amount=payload.total_amount,
        currency=payload.currency,
        remark=payload.remark,
        items=items,
    )
    db.add(reimb)
    db.commit()
    db.refresh(reimb)
    return reimb


def list_reimbursements(
    db: Session, user: SysUser, status: str | None, page: int, page_size: int
) -> tuple[int, list[Reimbursement]]:
    """列表（L2 行级过滤）。"""
    perms = user_permissions(user)
    stmt = select(Reimbursement)
    if "reimb:audit" not in perms:
        if "reimb:view_own" not in perms:
            raise ForbiddenError()
        stmt = stmt.where(Reimbursement.applicant_id == user.id)
    if status:
        stmt = stmt.where(Reimbursement.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        db.scalars(
            stmt.order_by(Reimbursement.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return total, items


def get_reimbursement(db: Session, user: SysUser, reimbursement_id: int) -> Reimbursement:
    reimb = db.get(Reimbursement, reimbursement_id)
    if reimb is None:
        raise NotFoundError("报销单不存在")
    _ensure_view(user, reimb)
    return reimb


def update_reimbursement(
    db: Session, user: SysUser, reimbursement_id: int, payload: ReimbursementCreate
) -> Reimbursement:
    """整体更新（仅 draft / returned）。"""
    reimb = get_reimbursement(db, user, reimbursement_id)
    _ensure_owner(user, reimb)
    ensure_state(reimb.status, REIMBURSEMENT_ACTION_STATES["edit"], "edit")
    items = [ReimbursementItem(**i.model_dump()) for i in payload.items]
    _check_amount(items, payload.total_amount)
    reimb.department_id = payload.department_id
    reimb.project_id = payload.project_id
    reimb.total_amount = payload.total_amount
    reimb.currency = payload.currency
    reimb.remark = payload.remark
    reimb.items.clear()
    reimb.items.extend(items)
    db.commit()
    db.refresh(reimb)
    return reimb


def upload_attachments(
    db: Session,
    user: SysUser,
    reimbursement_id: int,
    files: list[UploadFile],
    categories: list[str],
) -> list[dict[str, object]]:
    """上传附件（multipart 多文件 + 分类一一对应）。"""
    reimb = get_reimbursement(db, user, reimbursement_id)
    _ensure_owner(user, reimb)
    ensure_state(
        reimb.status, REIMBURSEMENT_ACTION_STATES["upload_attachment"], "upload_attachment"
    )
    if len(files) != len(categories):
        raise ValidationError("files 与 categories 数量不一致")
    result: list[dict[str, object]] = []
    for f, cat in zip(files, categories, strict=True):
        if cat not in _VALID_CATEGORIES:
            raise ValidationError(f"非法附件分类: {cat}")
        content = f.file.read()
        size = len(content)
        # 真实写盘（随机安全文件名，防路径穿越）；原始文件名仅作元数据
        storage_path = file_store_service.save_upload(content, f.filename)
        fs = FileStore(
            file_name=f.filename or "",
            storage_path=storage_path,
            mime_type=f.content_type,
            size=size,
        )
        db.add(fs)
        db.flush()
        att = Attachment(file_store_id=fs.id, category=cat, uploaded_by=user.id)
        db.add(att)
        db.flush()
        db.add(ReimbursementAttachment(reimbursement_id=reimbursement_id, attachment_id=att.id))
        result.append(
            {
                "attachment_id": att.id,
                "category": cat,
                "file_name": f.filename,
                "size": size,
                "url": f"/files/{storage_path}",
            }
        )
    db.commit()
    return result


def delete_attachment(
    db: Session, user: SysUser, reimbursement_id: int, attachment_id: int
) -> None:
    """删除附件（仅 draft / returned）。"""
    reimb = get_reimbursement(db, user, reimbursement_id)
    _ensure_owner(user, reimb)
    ensure_state(
        reimb.status, REIMBURSEMENT_ACTION_STATES["delete_attachment"], "delete_attachment"
    )
    ra = db.scalar(
        select(ReimbursementAttachment).where(
            ReimbursementAttachment.reimbursement_id == reimbursement_id,
            ReimbursementAttachment.attachment_id == attachment_id,
        )
    )
    if ra is None:
        raise NotFoundError("附件不存在")
    db.delete(ra)
    db.flush()  # session autoflush=False，先落删除再查引用
    # 无其他引用时清理 Attachment / FileStore / 真实文件
    att = db.get(Attachment, attachment_id)
    still_ref = db.scalar(
        select(ReimbursementAttachment.id).where(
            ReimbursementAttachment.attachment_id == attachment_id
        )
    )
    if att is not None and still_ref is None:
        fs = db.get(FileStore, att.file_store_id)
        db.delete(att)
        if fs is not None:
            with contextlib.suppress(OSError):
                file_store_service.delete_upload(fs.storage_path)
            db.delete(fs)
    db.commit()


def submit(db: Session, user: SysUser, reimbursement_id: int) -> int:
    """提交审核：事务内建任务 + 迁 pending，投递 Celery。返回 task_id。"""
    reimb = get_reimbursement(db, user, reimbursement_id)
    _ensure_owner(user, reimb)
    ensure_state(reimb.status, REIMBURSEMENT_ACTION_STATES["submit"], "submit")
    invoice_count = db.scalar(
        select(func.count())
        .select_from(Attachment)
        .join(
            ReimbursementAttachment,
            ReimbursementAttachment.attachment_id == Attachment.id,
        )
        .where(
            ReimbursementAttachment.reimbursement_id == reimbursement_id,
            Attachment.category == "invoice",
        )
    )
    if not invoice_count:
        raise ValidationError("缺少发票附件，请先上传")
    task = AuditTask(reimbursement_id=reimbursement_id, status="queued")
    db.add(task)
    reimb.status = ReimbursementStatus.PENDING.value
    reimb.submitted_at = datetime.now(UTC)
    db.commit()
    db.refresh(task)
    run_audit_task.delay(reimbursement_id, task.id)
    return task.id


def manual_review(
    db: Session, user: SysUser, reimbursement_id: int, conclusion: str, reason: str
) -> Reimbursement:
    """人工复核（仅 manual_review 态）：裁决 approved / returned。"""
    reimb = get_reimbursement(db, user, reimbursement_id)
    ensure_state(reimb.status, REIMBURSEMENT_ACTION_STATES["manual_review"], "manual_review")
    existing = get_conclusion(db, reimbursement_id)
    if existing is not None:
        existing.result = conclusion
        existing.reason = reason
    else:
        db.add(AuditConclusion(reimbursement_id=reimbursement_id, result=conclusion, reason=reason))
    reimb.status = conclusion
    if conclusion == "approved":
        write_ledger(db, reimb, _load_items(db, reimbursement_id))
    db.commit()
    db.refresh(reimb)
    return reimb


def return_reimbursement(
    db: Session, user: SysUser, reimbursement_id: int, reason: str
) -> Reimbursement:
    """财务主动退回（仅 pending 态）。"""
    reimb = get_reimbursement(db, user, reimbursement_id)
    ensure_state(reimb.status, REIMBURSEMENT_ACTION_STATES["return"], "return")
    reimb.status = ReimbursementStatus.RETURNED.value
    reimb.return_reason = reason
    db.commit()
    db.refresh(reimb)
    return reimb


def get_audit_task(db: Session, user: SysUser, task_id: int) -> AuditTask:
    """审核任务轮询（L2：申请人仅本人单据任务）。"""
    task = db.get(AuditTask, task_id)
    if task is None:
        raise NotFoundError("任务不存在")
    reimb = db.get(Reimbursement, task.reimbursement_id)
    if reimb is not None:
        _ensure_view(user, reimb)
    return task
