"""报销域接口（docs/api.md §2）。"""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_perm
from app.core.exceptions import NotFoundError
from app.core.perms import Permission
from app.db.session import get_db
from app.models.base_data import Attachment, CostCategory, FileStore, OrgDepartment, Project
from app.models.rbac import SysUser
from app.models.reimbursement import AuditConclusion, ReimbursementAttachment
from app.schemas.common import PageResult
from app.schemas.reimbursement import (
    AttachmentOut,
    AuditConclusionOut,
    AuditTaskOut,
    ManualReviewRequest,
    ReimbursementCreate,
    ReimbursementDetailOut,
    ReimbursementListOut,
    ReimbursementOut,
    ReturnRequest,
    SubmitResponse,
    UploadResponse,
)
from app.services import reimbursement_service, report_service
from app.services.audit_flow_service import get_conclusion

router = APIRouter(prefix="/reimbursements", tags=["报销"])
audit_router = APIRouter(prefix="/audit-tasks", tags=["报销"])

_REIMB_CREATE = Permission.REIMB_CREATE.value
_REIMB_AUDIT = Permission.REIMB_AUDIT.value
_REIMB_MANUAL_REVIEW = Permission.REIMB_MANUAL_REVIEW.value


def _attachments(db: Session, reimbursement_id: int) -> list[AttachmentOut]:
    rows = db.execute(
        select(Attachment, FileStore)
        .join(FileStore, FileStore.id == Attachment.file_store_id)
        .join(ReimbursementAttachment, ReimbursementAttachment.attachment_id == Attachment.id)
        .where(ReimbursementAttachment.reimbursement_id == reimbursement_id)
    ).all()
    return [
        AttachmentOut(
            attachment_id=a.id,
            category=a.category,
            file_name=fs.file_name,
            size=fs.size,
            url=f"/files/{fs.storage_path}",
        )
        for a, fs in rows
    ]


def _conclusion_out(db: Session, conclusion: AuditConclusion | None) -> AuditConclusionOut | None:
    if conclusion is None:
        return None
    recommended = None
    if conclusion.recommended_category_id is not None:
        cat = db.get(CostCategory, conclusion.recommended_category_id)
        recommended = {"id": cat.id, "name": cat.name, "confidence": 1.0} if cat else None
    return AuditConclusionOut(
        result=conclusion.result,
        recommended_category=recommended,
        check_items=conclusion.check_items,
        risk_items=conclusion.risk_items,
        reason=conclusion.reason,
    )


@router.post("", response_model=ReimbursementOut, status_code=201)
def create_reimbursement(
    payload: ReimbursementCreate,
    current_user: Annotated[SysUser, Depends(require_perm(_REIMB_CREATE))],
    db: Annotated[Session, Depends(get_db)],
) -> ReimbursementOut:
    """新建报销单（草稿态）。"""
    reimb = reimbursement_service.create_reimbursement(db, current_user, payload)
    return ReimbursementOut.model_validate(reimb)


@router.get("", response_model=PageResult[ReimbursementListOut])
def list_reimbursements(
    current_user: Annotated[SysUser, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> PageResult[ReimbursementListOut]:
    """报销单列表（L2 行级过滤）。"""
    total, reimbs = reimbursement_service.list_reimbursements(
        db, current_user, status, page, page_size
    )
    items: list[ReimbursementListOut] = []
    for r in reimbs:
        applicant = db.get(SysUser, r.applicant_id)
        dept = db.get(OrgDepartment, r.department_id)
        proj = db.get(Project, r.project_id) if r.project_id else None
        concl = get_conclusion(db, r.id)
        items.append(
            ReimbursementListOut(
                id=r.id,
                no=r.no,
                applicant_name=applicant.name if applicant else "",
                department_name=dept.name if dept else "",
                project_name=proj.name if proj else None,
                total_amount=r.total_amount,
                status=r.status,
                conclusion=concl.result if concl else None,
                created_at=r.created_at,
            )
        )
    return PageResult(total=total, page=page, page_size=page_size, items=items)


@router.get("/{reimbursement_id}", response_model=ReimbursementDetailOut)
def get_reimbursement(
    reimbursement_id: int,
    current_user: Annotated[SysUser, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ReimbursementDetailOut:
    """报销单详情。"""
    reimb = reimbursement_service.get_reimbursement(db, current_user, reimbursement_id)
    detail = ReimbursementDetailOut.model_validate(reimb)
    detail.attachments = _attachments(db, reimbursement_id)
    detail.conclusion = _conclusion_out(db, get_conclusion(db, reimbursement_id))
    return detail


@router.put("/{reimbursement_id}", response_model=ReimbursementOut)
def update_reimbursement(
    reimbursement_id: int,
    payload: ReimbursementCreate,
    current_user: Annotated[SysUser, Depends(require_perm(_REIMB_CREATE))],
    db: Annotated[Session, Depends(get_db)],
) -> ReimbursementOut:
    """整体更新（仅 draft / returned）。"""
    reimb = reimbursement_service.update_reimbursement(db, current_user, reimbursement_id, payload)
    return ReimbursementOut.model_validate(reimb)


@router.post("/{reimbursement_id}/attachments", response_model=UploadResponse, status_code=201)
def upload_attachments(
    reimbursement_id: int,
    current_user: Annotated[SysUser, Depends(require_perm(_REIMB_CREATE))],
    db: Annotated[Session, Depends(get_db)],
    files: Annotated[list[UploadFile] | None, File()] = None,
    categories: Annotated[list[str] | None, Form()] = None,
) -> UploadResponse:
    """上传附件（multipart 多文件 + 分类一一对应）。"""
    result = reimbursement_service.upload_attachments(
        db, current_user, reimbursement_id, list(files or []), list(categories or [])
    )
    return UploadResponse(
        attachments=[AttachmentOut(**a) for a in result]  # type: ignore[arg-type]
    )


@router.delete("/{reimbursement_id}/attachments/{attachment_id}", status_code=204)
def delete_attachment(
    reimbursement_id: int,
    attachment_id: int,
    current_user: Annotated[SysUser, Depends(require_perm(_REIMB_CREATE))],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """删除附件（仅 draft / returned）。"""
    reimbursement_service.delete_attachment(db, current_user, reimbursement_id, attachment_id)


@router.post("/{reimbursement_id}/submit", response_model=SubmitResponse, status_code=202)
def submit(
    reimbursement_id: int,
    current_user: Annotated[SysUser, Depends(require_perm(_REIMB_CREATE))],
    db: Annotated[Session, Depends(get_db)],
) -> SubmitResponse:
    """提交审核（触发异步审核任务）。"""
    task_id = reimbursement_service.submit(db, current_user, reimbursement_id)
    return SubmitResponse(task_id=task_id, reimbursement_id=reimbursement_id, status="queued")


@router.post("/{reimbursement_id}/manual-review", response_model=ReimbursementOut)
def manual_review(
    reimbursement_id: int,
    payload: ManualReviewRequest,
    current_user: Annotated[SysUser, Depends(require_perm(_REIMB_MANUAL_REVIEW))],
    db: Annotated[Session, Depends(get_db)],
) -> ReimbursementOut:
    """人工复核落结论（approved / returned）。"""
    reimb = reimbursement_service.manual_review(
        db, current_user, reimbursement_id, payload.conclusion, payload.reason
    )
    return ReimbursementOut.model_validate(reimb)


@router.post("/{reimbursement_id}/return", response_model=ReimbursementOut)
def return_reimbursement(
    reimbursement_id: int,
    payload: ReturnRequest,
    current_user: Annotated[SysUser, Depends(require_perm(_REIMB_AUDIT))],
    db: Annotated[Session, Depends(get_db)],
) -> ReimbursementOut:
    """财务主动退回（仅 pending）。"""
    reimb = reimbursement_service.return_reimbursement(
        db, current_user, reimbursement_id, payload.reason
    )
    return ReimbursementOut.model_validate(reimb)


@router.get("/{reimbursement_id}/report")
def get_report(
    reimbursement_id: int,
    current_user: Annotated[SysUser, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> HTMLResponse:
    """审核报告（HTML 导出）。"""
    reimb = reimbursement_service.get_reimbursement(db, current_user, reimbursement_id)
    conclusion = get_conclusion(db, reimbursement_id)
    if conclusion is None:
        raise NotFoundError("审核报告尚未生成")
    html = report_service.render_report(db, reimb, conclusion)
    return HTMLResponse(content=html)


@audit_router.get("/{task_id}", response_model=AuditTaskOut)
def get_audit_task(
    task_id: int,
    current_user: Annotated[SysUser, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> AuditTaskOut:
    """审核任务轮询。"""
    task = reimbursement_service.get_audit_task(db, current_user, task_id)
    conclusion = get_conclusion(db, task.reimbursement_id)
    return AuditTaskOut(
        task_id=task.id,
        reimbursement_id=task.reimbursement_id,
        status=task.status,
        conclusion=_conclusion_out(db, conclusion),
        error=task.error,
    )
