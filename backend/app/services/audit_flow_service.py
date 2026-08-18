"""报销审核编排（docs/requirements.md §4.2.2 四层流水线）。

（注：与审计日志服务 audit_service.log_action 分离，本模块负责审核流水线。）
解析 → 规则引擎 → 科目推荐 → 结论。结论由规则引擎拍板，fail-closed 汇总：
任一 failed → returned；否则任一 uncertain → manual_review；否则 approved。
approved 与 expense_ledger 写入同一事务并幂等。
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.clients import llm as llm_module
from app.core.config import get_settings
from app.domain.risk_engine.rules import run_rules
from app.domain.risk_engine.types import BudgetCheck, RuleContext, RuleResult
from app.models.base_data import (
    Attachment,
    Budget,
    CostCategory,
    ExpenseLedger,
    Project,
    SysParam,
)
from app.models.enums import (
    AuditResult,
    ReimbursementStatus,
    TaskStatus,
)
from app.models.rbac import SysUser
from app.models.reimbursement import (
    AuditConclusion,
    AuditTask,
    Reimbursement,
    ReimbursementAttachment,
    ReimbursementItem,
)
from app.services.category_service import recommend_category
from app.services.parse_service import parse_attachments

_UNFINISHED = [
    ReimbursementStatus.DRAFT.value,
    ReimbursementStatus.PENDING.value,
    ReimbursementStatus.MANUAL_REVIEW.value,
]


def _load_attachments(db: Session, reimbursement_id: int) -> list[Attachment]:
    return list(
        db.scalars(
            select(Attachment)
            .join(
                ReimbursementAttachment,
                ReimbursementAttachment.attachment_id == Attachment.id,
            )
            .where(ReimbursementAttachment.reimbursement_id == reimbursement_id)
        )
    )


def _load_thresholds(db: Session) -> dict[str, str]:
    rows = db.scalars(select(SysParam).where(SysParam.key.like("threshold.%"))).all()
    return {p.key: p.value for p in rows}


def _load_existing_invoice_keys(db: Session, current_id: int) -> set[str]:
    """查重范围：已通过 + 未终结报销单的发票号（退回可合法重提，故排除 returned）。"""
    rows = db.scalars(
        select(ReimbursementItem.invoice_key)
        .join(Reimbursement, Reimbursement.id == ReimbursementItem.reimbursement_id)
        .where(
            Reimbursement.id != current_id,
            Reimbursement.status.in_([ReimbursementStatus.APPROVED.value, *_UNFINISHED]),
            ReimbursementItem.invoice_key.is_not(None),
        )
    ).all()
    return {str(r) for r in rows if r}


def _cumulative_ratio(curve: Any, month: int) -> Decimal:
    """截止 month 的累计分摊比例：有曲线按曲线前 month 项之和，无曲线按均匀分摊。"""
    if curve:
        return sum((Decimal(str(x)) for x in curve[:month]), Decimal(0))
    return Decimal(month) / Decimal(12)


def _build_budget_checks(
    db: Session, reimb: Reimbursement, items: list[ReimbursementItem]
) -> list[BudgetCheck]:
    if reimb.project_id is None:
        return []
    now = datetime.now(UTC)
    year = now.strftime("%Y")
    month = now.month
    checks: list[BudgetCheck] = []
    for item in items:
        budget = db.scalar(
            select(Budget).where(
                Budget.department_id == reimb.department_id,
                Budget.project_id == reimb.project_id,
                Budget.cost_category_id == item.cost_category_id,
                Budget.budget_year == year,
            )
        )
        ledger = db.scalar(
            select(func.sum(ExpenseLedger.amount)).where(
                ExpenseLedger.department_id == reimb.department_id,
                ExpenseLedger.project_id == reimb.project_id,
                ExpenseLedger.cost_category_id == item.cost_category_id,
                ExpenseLedger.period.like(f"{year}-%"),
            )
        )
        # 截止当前月的累计预算额度 = 年度预算 × 曲线累计比例（Stage 3 年度口径）
        budget_amount = Decimal(0)
        if budget is not None:
            budget_amount = (
                budget.amount * _cumulative_ratio(budget.allocation_curve, month)
            ).quantize(Decimal("0.01"))
        checks.append(
            BudgetCheck(
                cost_category_id=item.cost_category_id,
                budget_amount=budget_amount,
                ledger_amount=ledger or Decimal(0),
                item_amount=item.amount,
            )
        )
    return checks


def _summarize(results: list[RuleResult]) -> str:
    """fail-closed 汇总：failed → returned；uncertain → manual_review；否则 approved。"""
    if any(r.status == "failed" for r in results):
        return AuditResult.RETURNED.value
    if any(r.status == "uncertain" for r in results):
        return AuditResult.MANUAL_REVIEW.value
    return AuditResult.APPROVED.value


def write_ledger(db: Session, reimb: Reimbursement, items: list[ReimbursementItem]) -> None:
    """approved 写台账（幂等：ref_no 已存在则跳过）。"""
    exists = db.scalar(
        select(ExpenseLedger.id).where(
            ExpenseLedger.source == "reimb", ExpenseLedger.ref_no == reimb.no
        )
    )
    if exists is not None:
        return
    period = datetime.now(UTC).strftime("%Y-%m")
    for item in items:
        db.add(
            ExpenseLedger(
                source="reimb",
                cost_category_id=item.cost_category_id,
                department_id=reimb.department_id,
                project_id=reimb.project_id,
                period=period,
                amount=item.amount,
                occurred_at=datetime.now(UTC),
                ref_no=reimb.no,
            )
        )


def run_audit(db: Session, reimbursement_id: int, task_id: int) -> None:
    """执行完整审核流水线，更新任务/单据状态、写结论与台账。"""
    settings = get_settings()
    reimb = db.get(Reimbursement, reimbursement_id)
    if reimb is None:
        return
    task = db.get(AuditTask, task_id)
    # 幂等：任务已终态则跳过（重复投递不重复执行）
    if task is not None and task.status in (TaskStatus.DONE.value, TaskStatus.FAILED.value):
        return
    if task is not None:
        task.status = TaskStatus.PARSING.value
        db.flush()

    try:
        attachments = _load_attachments(db, reimbursement_id)
        parsed_docs = parse_attachments(db, reimb, attachments)

        categories = list(
            db.scalars(select(CostCategory).where(CostCategory.enabled.is_(True))).all()
        )
        recommendation = recommend_category(
            db, parsed_docs, categories, llm_module.get_llm_client()
        )

        items = list(
            db.scalars(
                select(ReimbursementItem).where(
                    ReimbursementItem.reimbursement_id == reimbursement_id
                )
            )
        )

        project_name = ""
        if reimb.project_id is not None:
            project = db.get(Project, reimb.project_id)
            project_name = project.name if project else ""
        applicant = db.get(SysUser, reimb.applicant_id)
        applicant_name = applicant.name if applicant else ""

        ctx = RuleContext(
            reimbursement=reimb,
            items=items,
            parsed_docs=parsed_docs,
            categories=categories,
            budget_checks=_build_budget_checks(db, reimb, items),
            company_name=settings.company_name,
            thresholds=_load_thresholds(db),
            existing_invoice_keys=_load_existing_invoice_keys(db, reimbursement_id),
            project_name=project_name,
            applicant_name=applicant_name,
            recommended_category=recommendation.category,
        )

        results = run_rules(ctx)
        conclusion = _summarize(results)
        risk_items = [r.to_dict() for r in results if r.status != "passed"]
        check_items = [r.to_dict() for r in results]

        reason = "；".join(r.message for r in results if r.status != "passed") or None

        db.add(
            AuditConclusion(
                reimbursement_id=reimbursement_id,
                task_id=task_id,
                result=conclusion,
                recommended_category_id=(
                    recommendation.category.id if recommendation.category else None
                ),
                check_items=check_items,
                risk_items=risk_items,
                reason=reason,
            )
        )

        reimb.status = conclusion
        if conclusion == AuditResult.APPROVED.value:
            write_ledger(db, reimb, items)

        if task is not None:
            task.status = TaskStatus.DONE.value
            task.error = None
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        if task is not None:
            task.status = TaskStatus.FAILED.value
            task.error = str(exc)
            db.commit()
        raise


def get_conclusion(db: Session, reimbursement_id: int) -> AuditConclusion | None:
    """取报销单最新审核结论。"""
    return db.scalar(
        select(AuditConclusion)
        .where(AuditConclusion.reimbursement_id == reimbursement_id)
        .order_by(AuditConclusion.id.desc())
        .limit(1)
    )
