# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""预算监控集成测试（22-26/28-30 验收项）：持久化 / 幂等 / 预警 / 接口权限 / 阈值生效。"""

from datetime import UTC, datetime
from decimal import Decimal

from app.models.alert import Alert
from app.models.base_data import ExpenseLedger, SysParam
from app.models.budget_domain import BudgetDeviation, BudgetSnapshot
from app.services import monitor_service
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.helpers import login, make_user, seed_base


def _add_ledger(
    db: Session, dept_id: int, proj_id: int, cat_id: int, period: str, amount: str
) -> None:
    db.add(
        ExpenseLedger(
            source="import",
            cost_category_id=cat_id,
            department_id=dept_id,
            project_id=proj_id,
            period=period,
            amount=Decimal(amount),
            occurred_at=datetime(2026, int(period[5:7]), 15, tzinfo=UTC),
            ref_no=f"MON-{period}",
        )
    )


def _overrun_scenario(db: Session) -> int:
    """seed 预算 10 万 + 1-6 月每月 2 万（累计 12 万 > 计划 5 万 → high）。返回 dept.id。"""
    base = seed_base(db)
    for m in range(1, 7):
        _add_ledger(db, base.dept.id, base.proj.id, base.travel.id, f"2026-{m:02d}", "20000.00")
    db.commit()
    return base.dept.id


def test_monitor_persists_deviation_alert_snapshot(
    db_session: Session,
) -> None:
    """22/23. snapshot 落库 + high deviation 创建 alert。"""
    dept_id = _overrun_scenario(db_session)
    summary = monitor_service.run_monitor(db_session, "2026-06")
    assert summary["deviations"] == 1
    assert summary["alerts_created"] == 1

    dev = db_session.scalar(select(BudgetDeviation))
    assert dev is not None
    assert dev.level == "high"
    assert "over_budget" in (dev.trigger_reason or "")

    alert = db_session.scalar(select(Alert))
    assert alert is not None
    assert alert.alert_type == "budget"
    assert alert.level == "critical"
    assert alert.unique_key == f"budget:2026-06:{dept_id}:1:{dev.cost_category_id}"

    snap = db_session.scalar(select(BudgetSnapshot))
    assert snap is not None
    assert snap.period == "2026-06"
    assert snap.status == "done"
    assert snap.deviation_count == 1


def test_monitor_idempotent(db_session: Session) -> None:
    """24. 重复任务幂等：偏差/预警/快照不无限累积。"""
    _overrun_scenario(db_session)
    monitor_service.run_monitor(db_session, "2026-06")
    monitor_service.run_monitor(db_session, "2026-06")
    assert db_session.scalar(select(func.count()).select_from(BudgetDeviation)) == 1
    assert db_session.scalar(select(func.count()).select_from(Alert)) == 1
    assert db_session.scalar(select(func.count()).select_from(BudgetSnapshot)) == 1


def test_deviation_api_permissions(client: TestClient, db_session: Session) -> None:
    """25/26. applicant 无 budget:view 403；finance 可访问。"""
    _overrun_scenario(db_session)
    monitor_service.run_monitor(db_session, "2026-06")
    make_user(db_session, "app", "applicant")
    make_user(db_session, "fin", "finance")
    app_token = login(client, "app")
    fin_token = login(client, "fin")

    resp = client.get("/api/deviations", headers={"Authorization": f"Bearer {app_token}"})
    assert resp.status_code == 403, resp.text
    resp = client.get("/api/deviations", headers={"Authorization": f"Bearer {fin_token}"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["total"] == 1


def test_summary_aggregation(client: TestClient, db_session: Session) -> None:
    """28. summary group_by 聚合正确。"""
    dept_id = _overrun_scenario(db_session)
    monitor_service.run_monitor(db_session, "2026-06")
    make_user(db_session, "bm", "budget_manager")
    token = login(client, "bm")

    resp = client.get(
        "/api/deviations/summary?group_by=department",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    groups = resp.json()
    assert len(groups) == 1
    g = groups[0]
    assert g["key"] == dept_id
    assert g["budget_total"] == "50000.00"
    assert g["actual_total"] == "120000.00"
    assert g["deviation_amount"] == "70000.00"
    assert g["level"] == "high"


def test_monitor_status_api(client: TestClient, db_session: Session) -> None:
    """29. monitor/status 返回最近快照。"""
    _overrun_scenario(db_session)
    monitor_service.run_monitor(db_session, "2026-06")
    make_user(db_session, "bm", "budget_manager")
    token = login(client, "bm")
    resp = client.get("/api/monitor/status", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "done"
    assert body["snapshot"]["period"] == "2026-06"
    assert body["snapshot"]["deviation_count"] == 1


def test_threshold_change_takes_effect_next_round(db_session: Session) -> None:
    """30. sys_param 修改阈值后下一轮生效。"""
    base = seed_base(db_session)
    for m in range(1, 8):
        period = f"2026-{m:02d}"
        _add_ledger(db_session, base.dept.id, base.proj.id, base.travel.id, period, "6666.67")
    db_session.commit()

    # 默认 gap=0.15：落后约 10% 不触发
    summary = monitor_service.run_monitor(db_session, "2026-06")
    assert summary["deviations"] == 0

    # 调低 progress_gap=0.05 → 下一核算期生效
    gap_key = "threshold.budget.progress_gap"
    param = db_session.scalar(select(SysParam).where(SysParam.key == gap_key))
    if param is None:
        param = SysParam(key=gap_key, value="0.05", value_type="float")
        db_session.add(param)
    else:
        param.value = "0.05"
    db_session.commit()

    summary2 = monitor_service.run_monitor(db_session, "2026-07")
    assert summary2["deviations"] == 1
    dev = db_session.scalar(select(BudgetDeviation).where(BudgetDeviation.period == "2026-07"))
    assert dev is not None and "progress" in (dev.trigger_reason or "")
