"""审核报告 HTML 输出（docs/api.md §2 / requirements 验收：可导出 HTML）。

优先简单、可维护、可打印，不引入模板系统。
"""

from typing import Any

from sqlalchemy.orm import Session

from app.models.base_data import CostCategory
from app.models.reimbursement import AuditConclusion, Reimbursement

_RESULT_LABEL = {
    "approved": "通过",
    "returned": "退回",
    "manual_review": "人工复核",
}


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _check_rows(check_items: list[dict[str, Any]] | None) -> str:
    if not check_items:
        return "<p>无校验明细</p>"
    rows: list[str] = []
    for c in check_items:
        status = str(c.get("status", ""))
        color = {"passed": "#1d9e75", "failed": "#e24b4a", "uncertain": "#ba7517"}.get(
            status, "#5f5e5a"
        )
        rows.append(
            f"<tr><td>{_escape(str(c.get('rule', '')))}</td>"
            f"<td>{_escape(str(c.get('name', '')))}</td>"
            f"<td style='color:{color}'>{_escape(status)}</td>"
            f"<td>{_escape(str(c.get('actual_value', '')))}</td>"
            f"<td>{_escape(str(c.get('expected_value', '')))}</td>"
            f"<td>{_escape(str(c.get('message', '')))}</td></tr>"
        )
    return "".join(rows)


def render_report(db: Session, reimb: Reimbursement, conclusion: AuditConclusion) -> str:
    """渲染审核报告 HTML。"""
    category_name = ""
    if conclusion.recommended_category_id is not None:
        cat = db.get(CostCategory, conclusion.recommended_category_id)
        category_name = cat.name if cat else ""

    result = conclusion.result
    label = _RESULT_LABEL.get(result, result)
    risk_count = len(conclusion.risk_items or [])

    return f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>报销审核报告 {_escape(reimb.no)}</title>
<style>
body {{
  font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif;
  margin: 24px;
  color: #2c2c2a;
}}
h1 {{ font-size: 18px; font-weight: 600; }}
table {{ border-collapse: collapse; width: 100%; margin-top: 8px; }}
th, td {{ border: 1px solid #ddd; padding: 8px 10px; font-size: 13px; text-align: left; }}
th {{ background: #f5f5f3; }}
.badge {{ display: inline-block; padding: 2px 10px; border-radius: 12px; font-weight: 600; }}
.summary {{ margin: 16px 0; line-height: 1.8; font-size: 14px; }}
</style>
</head>
<body>
<h1>报销审核报告</h1>
<div class="summary">
<p><strong>单据号：</strong>{_escape(reimb.no)}</p>
<p><strong>报销金额：</strong>{reimb.total_amount} {reimb.currency}</p>
<p><strong>审核结论：</strong><span class="badge">{label}</span></p>
<p><strong>推荐科目：</strong>{_escape(category_name) or "—"}</p>
<p><strong>风险项：</strong>{risk_count}</p>
<p><strong>结论说明：</strong>{_escape(conclusion.reason or "—")}</p>
</div>
<h2>校验明细</h2>
<table>
<thead><tr><th>规则</th><th>名称</th><th>结果</th><th>实际值</th><th>参考值</th><th>说明</th></tr></thead>
<tbody>{_check_rows(conclusion.check_items)}</tbody>
</table>
</body>
</html>"""
