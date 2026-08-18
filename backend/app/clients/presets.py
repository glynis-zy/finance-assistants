"""preset 模式预设解析结果。

preset 模式不调用外部 OCR/LLM，返回这些固定预设值，保证无 Key 完整跑通验收链路。
金额统一为字符串（docs/api.md §0.3）；抬头/项目/申请人与 seed 演示数据一致。
"""

INVOICE_PRESET: dict[str, object] = {
    "invoice_no": "INV-000001",
    "amount": "1000.00",
    "buyer_name": "某某科技有限公司",
    "invoice_date": "2026-08-01",
    "invoice_type": "增值税普通发票",
    "description": "差旅费-高铁票",
}

TRAVEL_PRESET: dict[str, object] = {
    "trip_no": "TRIP-000001",
    "from_city": "北京",
    "to_city": "上海",
    "trip_date": "2026-08-02",
    "amount": "1000.00",
    "description": "高铁行程单",
}

APPROVAL_PRESET: dict[str, object] = {
    "approval_no": "APR-000001",
    "approval_amount": "1000.00",
    "project_name": "华东大区",
    "applicant_name": "张三",
    "approval_date": "2026-08-01",
}

PRESETS: dict[str, dict[str, object]] = {
    "invoice": INVOICE_PRESET,
    "travel": TRAVEL_PRESET,
    "approval": APPROVAL_PRESET,
}
