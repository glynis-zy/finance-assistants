# API 规范（api.md）

> 财务智能助手平台 · 单平台 + 三助手
> 依据：`docs/architecture.md` §5（API 设计概览）、`docs/requirements.md` §3（权限）/ §4（功能）/ §6（数据模型）
> 版本：v1.0（实现契约）｜ 状态：已冻结（2026-08-18 收口）
> 说明：认证接口与补充权限码为 api.md 依据架构 §2.3 `auth_service` / §6 权限架构补充定义；冻结后非核心接口不再扩展。

---

## 0. 通用约定

### 0.1 统一响应格式

- **成功（2xx）**：HTTP 状态码表达语义，响应体直接为资源；列表接口统一分页包装；`204 No Content` 返回空体。
- **失败（4xx/5xx）**：统一错误体：

```json
{
  "code": "INVALID_STATE",
  "message": "当前状态不允许该操作",
  "request_id": "req_8f3a2c1e"
}
```

| 业务码 `code` | HTTP | 含义 |
|---|---|---|
| `UNAUTHORIZED` | 401 | 未登录 / 令牌失效 |
| `FORBIDDEN` | 403 | L1 角色权限不足 |
| `FORBIDDEN_SCOPE` | 403 | L2 数据越权（行级过滤拦截） |
| `NOT_FOUND` | 404 | 资源不存在 |
| `VALIDATION_ERROR` | 422 | 参数校验失败（含必填缺失、枚举非法） |
| `INVALID_STATE` | 409 | L3 状态权限不允许（状态机冲突） |
| `DUPLICATE_SUBMIT` | 409 | 重复提交（单据已在审核中） |
| `DUPLICATE_INVOICE` | 409 | 重复发票（查重范围：已生效台账 + 未终结报销单） |
| `RESOURCE_CONFLICT` | 409 | 资源冲突（科目编码、客户编码、合同号、用户名、预算维度等唯一约束重复） |
| `REPORT_NOT_READY` | 409 | 报告尚未生成（无审核结论） |
| `INTERNAL_ERROR` | 500 | 服务内部错误 |

> 校验类错误（422）可附带 `detail` 数组：`[{"field": "items", "message": "明细不能为空"}]`。

### 0.2 分页规范

- Query 参数：`page`（默认 `1`，≥1）、`page_size`（默认 `20`，最大 `100`）。
- 响应统一为：`{ "total": 137, "page": 1, "page_size": 20, "items": [...] }`。
- 默认排序 `created_at DESC`；涉及金额的列表按金额字段倒序时在接口内另行说明。

### 0.3 ID / 金额 / 时间格式

| 类型 | 格式 | 示例 |
|---|---|---|
| ID | int64 自增（所有实体 + `task_id`） | `1024` |
| 金额 | **字符串**（Decimal 序列化，禁浮点），人民币元，保留 2 位小数 | `"1234.56"` |
| 时间 | ISO 8601 / RFC 3339，UTC | `"2026-08-18T01:30:00Z"` |
| 日期 | `YYYY-MM-DD` | `"2026-08-18"` |
| 期间 | `YYYY-MM` | `"2026-08"` |

> 前端展示本地时区由前端自行转换；接口一律 UTC。

### 0.4 认证与权限

- 登录成功返回 JWT `access_token`；所有受保护接口携带请求头 `Authorization: Bearer <token>`；缺失/失效 → `401 UNAUTHORIZED`。
- 三级权限（沿用架构 §6）：
  - **L1 角色权限**：路由依赖注入权限码；
  - **L2 数据权限**：查询层行级过滤（报销按申请人、应收按专员域），越权 → `403 FORBIDDEN_SCOPE`；
  - **L3 状态权限**：状态守卫表显式校验（非前端隐藏），冲突 → `409 INVALID_STATE`。
- 审计：登录、参数变更、阈值变更、预警投递、报销关键操作均写 `audit_log`（见各接口「副作用」）。

#### 权限码总表

| 权限码 | 角色（默认授予） | 来源 |
|---|---|---|
| `reimb:create` | applicant | requirements §3.1 |
| `reimb:view_own` | applicant | requirements §3.1 |
| `reimb:audit` | finance | requirements §3.1 |
| `reimb:manual_review` | finance | requirements §3.1 |
| `ledger:view` | finance | requirements §3.1 |
| `budget:manage` | budget_manager | requirements §3.1 |
| `budget:view` | budget_manager、finance | requirements §3.1（finance 补：对应职责「查看台账与偏差」） |
| `threshold:manage` | budget_manager | requirements §3.1 |
| `ar:manage` / `ar:view` | ar_specialist | requirements §3.1 |
| `user:manage` / `role:manage` / `sys:manage` | admin | requirements §3.1 |
| `cost_category:manage` | admin | **补充**：科目维护 |
| `ledger:import` | finance | **补充**：台账导入 |
| `alert:view` | finance / budget_manager / ar_specialist / admin | **补充**：预警查看（按业务域过滤，见下） |
| `alert:manage` | admin | **补充**：预警已读/管理 |

> **权限收口（v1.0）**
> - `sys_param` 修改：`threshold.*` 键允许 `threshold:manage` 或 `sys:manage` 修改；其余键仅 `sys:manage`。
> - 预警可见性按业务域过滤：`budget` 类预警 → finance / budget_manager；`ar` 类预警 → finance / ar_specialist；admin 全量；applicant 不授予 `alert:view`。

### 0.5 状态与枚举速查

| 枚举 | 取值 |
|---|---|
| 报销单 `status` | `draft`（待提交）`pending`（审核中）`manual_review`（人工复核）`approved`（已通过）`returned`（已退回） |
| 审核结论 `result` | `approved` / `returned` / `manual_review` |
| 任务 `status` | `queued`（排队）`parsing`（解析中）`done`（完成）`failed`（失败） |
| 附件 `category` | `invoice`（发票）`travel`（行程单）`approval`（审批单） |
| 偏差 `budget_deviation.level` | `low` / `medium` / `high` |
| 预警 `alert.level` | `info` / `warning` / `critical`（独立枚举，不与偏差共用） |
| 预警 `alert_type` | `budget` / `ar` |
| 应收风险 `risk_level` | `low` / `medium` / `high`（`score ≥ 70` 为 `high`） |
| 应收单 `status` | `open`（未回款）/ `partial`（部分回款）/ `settled`（已结清）；由服务端按累计到账维护；逾期为动态判断（`current_date > due_date && status != settled`），不作为状态值 |

---

## 1. 认证接口

### POST /api/auth/login 登录

| 项 | 内容 |
|---|---|
| **路径** | `/api/auth/login` |
| **方法** | `POST` |
| **权限** | 匿名（公开） |
| **允许状态** | — |
| **Request** | `application/json`：`{ "username": "zhang.san", "password": "******" }` |
| **Response** | `200 OK`：`{ "access_token": "eyJ...", "token_type": "bearer", "expires_in": 7200, "user": { "id": 1, "username": "zhang.san", "name": "张三", "roles": ["applicant"], "permissions": ["reimb:create", "reimb:view_own"] } }` |
| **错误码** | `401 UNAUTHORIZED`（用户名或密码错误）`422 VALIDATION_ERROR` |
| **副作用** | 写 `audit_log`（登录成功/失败） |

### POST /api/auth/logout 登出

| 项 | 内容 |
|---|---|
| **路径** | `/api/auth/logout` |
| **方法** | `POST` |
| **权限** | 登录即可 |
| **允许状态** | — |
| **Request** | 空体（Bearer token 在请求头） |
| **Response** | `204 No Content`（幂等，重复调用仍 204） |
| **错误码** | `401 UNAUTHORIZED` |
| **副作用** | 写 `audit_log`（登出）；V1 不做服务端令牌黑名单，前端丢弃 token |

### GET /api/auth/me 当前用户

| 项 | 内容 |
|---|---|
| **路径** | `/api/auth/me` |
| **方法** | `GET` |
| **权限** | 登录即可 |
| **允许状态** | — |
| **Request** | 无 |
| **Response** | `200 OK`：`{ "id": 1, "username": "zhang.san", "name": "张三", "roles": ["applicant"], "permissions": ["reimb:create", "reimb:view_own"] }`（前端渲染菜单/按钮用） |
| **错误码** | `401 UNAUTHORIZED` |
| **副作用** | 无 |

---

## 2. 报销接口

> 状态机：`draft → pending → approved / returned / manual_review`；`manual_review` 经财务裁决落 `approved`/`returned`；`returned` 可编辑后重新提交回 `pending`；`approved` 终态不可修改（冲销不在 V1）。
> 数据权限：申请人仅能访问本人单据（`reimb:view_own`），财务可见全部（`reimb:audit`）。

### POST /api/reimbursements 新建报销单

| 项 | 内容 |
|---|---|
| **路径** | `/api/reimbursements` |
| **方法** | `POST` |
| **权限** | `reimb:create` |
| **允许状态** | —（新建，落 `draft`） |
| **Request** | `application/json`：`{ "department_id": 1, "project_id": 2, "total_amount": "1234.56", "currency": "CNY", "items": [ { "cost_category_id": 3, "amount": "800.00", "invoice_key": "05100190011123456789", "description": "差旅-高铁" } ], "remark": "上海出差" }` |
| **Response** | `201 Created`：`{ "id": 1024, "no": "REIM-20260818-0001", "status": "draft", "total_amount": "1234.56", "created_at": "2026-08-18T01:31:00Z" }` |
| **错误码** | `401` `403 FORBIDDEN` `404 NOT_FOUND`（部门/项目/科目不存在或停用）`422 VALIDATION_ERROR`（明细为空、金额非法） |
| **副作用** | 写 `reimbursement` + `reimbursement_item` + `audit_log`；**不触发审核** |

### GET /api/reimbursements 报销单列表

| 项 | 内容 |
|---|---|
| **路径** | `/api/reimbursements` |
| **方法** | `GET` |
| **权限** | `reimb:view_own`（申请人，行级过滤仅本人）或 `reimb:audit`（财务，可见全部） |
| **允许状态** | — |
| **Request** | Query：`status`（可选）、`applicant_id`（仅财务可用）、`page`、`page_size` |
| **Response** | `200 OK` 分页：`{ "total": 12, "page": 1, "page_size": 20, "items": [ { "id": 1024, "no": "REIM-20260818-0001", "applicant_name": "张三", "department_name": "销售部", "project_name": "华东大区", "total_amount": "1234.56", "status": "pending", "conclusion": null, "created_at": "2026-08-18T01:31:00Z" } ] }` |
| **错误码** | `401` `403 FORBIDDEN` `403 FORBIDDEN_SCOPE`（申请人传他人 `applicant_id`）`422 VALIDATION_ERROR` |
| **副作用** | 无 |

### GET /api/reimbursements/{id} 报销单详情

| 项 | 内容 |
|---|---|
| **路径** | `/api/reimbursements/{id}` |
| **方法** | `GET` |
| **权限** | `reimb:view_own`（仅本人）或 `reimb:audit` |
| **允许状态** | — |
| **Request** | 路径参数 `id` |
| **Response** | `200 OK`：报销单主信息 + `items`（明细数组）+ `attachments`（附件数组：`attachment_id`/`category`/`file_name`/`url`）+ 最新 `audit_conclusion`（如有：`result`/`recommended_category`/`check_items`/`risk_items`） |
| **错误码** | `401` `403 FORBIDDEN` `403 FORBIDDEN_SCOPE`（非本人且非财务）`404 NOT_FOUND` |
| **副作用** | 无 |

### PUT /api/reimbursements/{id} 更新报销单

| 项 | 内容 |
|---|---|
| **路径** | `/api/reimbursements/{id}` |
| **方法** | `PUT` |
| **权限** | `reimb:create`（仅本人） |
| **允许状态** | `draft` / `returned`（其余 → `409 INVALID_STATE`） |
| **Request** | 同 POST（整体替换，`items` 全量提交） |
| **Response** | `200 OK`：更新后资源（同详情摘要） |
| **错误码** | `401` `403 FORBIDDEN` `403 FORBIDDEN_SCOPE` `404 NOT_FOUND` `409 INVALID_STATE`（非 draft/returned）`422 VALIDATION_ERROR` |
| **副作用** | 替换 `reimbursement_item`；写 `audit_log`（前后值）；`returned` 态编辑后状态保持 `returned`，直至重新提交 |

### POST /api/reimbursements/{id}/attachments 上传附件

| 项 | 内容 |
|---|---|
| **路径** | `/api/reimbursements/{id}/attachments` |
| **方法** | `POST` |
| **权限** | `reimb:create`（仅本人） |
| **允许状态** | `draft` / `returned`（其余 → `409 INVALID_STATE`） |
| **Request** | `multipart/form-data`：`files[]`（多文件）、`categories[]`（与 `files[]` 一一对应，取值 `invoice`/`travel`/`approval`）；两数组长度必须一致，否则 `422` |
| **Response** | `201 Created`：`{ "attachments": [ { "attachment_id": 88, "category": "invoice", "file_name": "0510_xxx.jpg", "size": 245760, "url": "/files/2026/08/18/xxx.jpg" } ] }` |
| **错误码** | `401` `403 FORBIDDEN` `403 FORBIDDEN_SCOPE` `404 NOT_FOUND` `409 INVALID_STATE` `422 VALIDATION_ERROR`（categories 取值非法、空文件、files 与 categories 数量不一致） |
| **副作用** | 写 `file_store` + `reimbursement_attachment`；**不触发解析**（解析在 submit 时） |

### DELETE /api/reimbursements/{id}/attachments/{attachment_id} 删除附件

| 项 | 内容 |
|---|---|
| **路径** | `/api/reimbursements/{id}/attachments/{attachment_id}` |
| **方法** | `DELETE` |
| **权限** | `reimb:create`（仅本人） |
| **允许状态** | `draft` / `returned`（其余 → `409 INVALID_STATE`） |
| **Request** | 路径参数 `id`、`attachment_id` |
| **Response** | `204 No Content` |
| **错误码** | `401` `403 FORBIDDEN` `403 FORBIDDEN_SCOPE` `404 NOT_FOUND` `409 INVALID_STATE` |
| **副作用** | 删除附件记录与文件引用；写 `audit_log` |

### POST /api/reimbursements/{id}/submit 提交审核

| 项 | 内容 |
|---|---|
| **路径** | `/api/reimbursements/{id}/submit` |
| **方法** | `POST` |
| **权限** | `reimb:create`（仅本人） |
| **允许状态** | `draft` / `returned`（其余 → `409 INVALID_STATE` / `DUPLICATE_SUBMIT`） |
| **Request** | 空体（Bearer token 在请求头） |
| **Response** | `202 Accepted`：`{ "task_id": 5566, "reimbursement_id": 1024, "status": "queued" }`（前端据此轮询任务） |
| **错误码** | `401` `403 FORBIDDEN` `403 FORBIDDEN_SCOPE` `404 NOT_FOUND` `409 INVALID_STATE`（非 draft/returned）`409 DUPLICATE_SUBMIT`（已排队/审核中）`422 VALIDATION_ERROR`（明细为空 / 无 `invoice` 类附件，先补齐材料） |
| **副作用** | 预检材料（明细非空 + 至少 1 张发票附件）；事务内创建 `audit_task`（`queued`）+ 状态迁 `pending`；入队 Celery（事件触发，不设 beat）；写 `audit_log`；任务按参数幂等 |

### GET /api/audit-tasks/{task_id} 审核任务轮询

| 项 | 内容 |
|---|---|
| **路径** | `/api/audit-tasks/{task_id}` |
| **方法** | `GET` |
| **权限** | `reimb:view_own`（仅本人单据的任务）或 `reimb:audit` |
| **允许状态** | — |
| **Request** | 路径参数 `task_id` |
| **Response** | `200 OK`：`{ "task_id": 5566, "reimbursement_id": 1024, "status": "done", "conclusion": { "result": "manual_review", "recommended_category": { "id": 3, "name": "差旅费", "confidence": 0.91, "candidates": [...] } }, "error": null }`（`status` 为 `failed` 时含 `error`） |
| **错误码** | `401` `403 FORBIDDEN` `403 FORBIDDEN_SCOPE` `404 NOT_FOUND` |
| **副作用** | 无（只读） |

### POST /api/reimbursements/{id}/manual-review 人工复核

| 项 | 内容 |
|---|---|
| **路径** | `/api/reimbursements/{id}/manual-review` |
| **方法** | `POST` |
| **权限** | `reimb:manual_review`（财务） |
| **允许状态** | `manual_review`（其余 → `409 INVALID_STATE`） |
| **Request** | `application/json`：`{ "conclusion": "approved" | "returned", "reason": "发票抬头与公司不符，金额不符" }`（`reason` 必填） |
| **Response** | `200 OK`：`{ "id": 1024, "no": "REIM-20260818-0001", "status": "approved", "conclusion": { "result": "approved", "final_reason": "..." } }` |
| **错误码** | `401` `403 FORBIDDEN` `404 NOT_FOUND` `409 INVALID_STATE`（非 manual_review）`422 VALIDATION_ERROR`（conclusion 非法 / reason 缺失） |
| **副作用** | 落 `audit_conclusion`；状态迁移；**`approved` → 同一事务写 `expense_ledger`**（来源 `reimb`）；写 `audit_log`；`returned` → 申请人可编辑重提 |

### POST /api/reimbursements/{id}/return 财务退回

| 项 | 内容 |
|---|---|
| **路径** | `/api/reimbursements/{id}/return` |
| **方法** | `POST` |
| **权限** | `reimb:audit`（财务） |
| **允许状态** | `pending`（仅审核中；`manual_review` 态裁决统一走 manual-review，避免职责重叠） |
| **Request** | `application/json`：`{ "reason": "缺少审批单，请补充后重提" }`（`reason` 必填） |
| **Response** | `200 OK`：`{ "id": 1024, "status": "returned", "return_reason": "缺少审批单，请补充后重提" }` |
| **错误码** | `401` `403 FORBIDDEN` `404 NOT_FOUND` `409 INVALID_STATE`（非 pending）`422 VALIDATION_ERROR`（reason 缺失） |
| **副作用** | 状态迁 `returned`；写 `audit_log`；**不写台账**；申请人可编辑后重新提交 |

### GET /api/reimbursements/{id}/report 审核报告导出

| 项 | 内容 |
|---|---|
| **路径** | `/api/reimbursements/{id}/report` |
| **方法** | `GET` |
| **权限** | `reimb:view_own`（仅本人）或 `reimb:audit` |
| **允许状态** | 存在 `audit_conclusion`（无结论 → `409 REPORT_NOT_READY`） |
| **Request** | 路径参数 `id` |
| **Response** | `200 OK`：`text/html; charset=utf-8`（HTML 报告全文，可直接打开/打印，验收标准要求可导出） |
| **错误码** | `401` `403 FORBIDDEN` `403 FORBIDDEN_SCOPE` `404 NOT_FOUND` `409 REPORT_NOT_READY` |
| **副作用** | 无（只读） |

---

## 3. 预算接口

### GET /api/deviations 偏差明细

| 项 | 内容 |
|---|---|
| **路径** | `/api/deviations` |
| **方法** | `GET` |
| **权限** | `budget:view` |
| **允许状态** | — |
| **Request** | Query：`dimension`（`department`/`project`/`cost_category`）、`level`（`low`/`medium`/`high`）、`period_from`、`period_to`、`page`、`page_size` |
| **Response** | `200 OK` 分页：`items` 元素含 `{ "id", "dimension_type", "dimension_id", "dimension_name", "period", "budget_amount", "actual_amount", "deviation_amount", "deviation_ratio", "level", "owner", "status" }` |
| **错误码** | `401` `403 FORBIDDEN` `422 VALIDATION_ERROR`（枚举非法） |
| **副作用** | 无（只读） |

### GET /api/deviations/summary 偏差汇总

| 项 | 内容 |
|---|---|
| **路径** | `/api/deviations/summary` |
| **方法** | `GET` |
| **权限** | `budget:view` |
| **允许状态** | — |
| **Request** | Query：`group_by`（`department`/`project`/`cost_category`）、`period`、`level`（可选） |
| **Response** | `200 OK`：`{ "groups": [ { "key": 1, "name": "销售部", "budget_total": "1200000.00", "actual_total": "1350000.00", "deviation_amount": "150000.00", "deviation_ratio": "0.125", "level": "high" } ] }` |
| **错误码** | `401` `403 FORBIDDEN` `422 VALIDATION_ERROR` |
| **副作用** | 无（只读） |

### GET /api/monitor/status 监控任务状态

| 项 | 内容 |
|---|---|
| **路径** | `/api/monitor/status` |
| **方法** | `GET` |
| **权限** | `budget:view` |
| **允许状态** | — |
| **Request** | 无 |
| **Response** | `200 OK`：`{ "last_run_at": "2026-08-18T00:00:10Z", "status": "done" | "queued" | "running" | "failed", "snapshot": { "id": 77, "period": "2026-08", "deviation_count": 9 } }` |
| **错误码** | `401` `403 FORBIDDEN` |
| **副作用** | 无（只读） |

### GET /api/budgets 预算列表

| 项 | 内容 |
|---|---|
| **路径** | `/api/budgets` |
| **方法** | `GET` |
| **权限** | `budget:view` |
| **允许状态** | — |
| **Request** | Query：`department_id`、`project_id`、`cost_category_id`、`period_from`、`period_to`、`page`、`page_size` |
| **Response** | `200 OK` 分页：`items` 元素含 `{ "id", "department_id", "project_id", "cost_category_id", "period", "amount", "allocation_curve", "created_at", "updated_at" }` |
| **错误码** | `401` `403 FORBIDDEN` `422 VALIDATION_ERROR` |
| **副作用** | 无（只读） |

### POST /api/budgets 新建预算

| 项 | 内容 |
|---|---|
| **路径** | `/api/budgets` |
| **方法** | `POST` |
| **权限** | `budget:manage` |
| **允许状态** | — |
| **Request** | `application/json`：`{ "department_id": 1, "project_id": 2, "cost_category_id": 3, "period": "2026-08", "amount": "100000.00", "allocation_curve": [0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.05, 0.05] }` |
| **Response** | `201 Created`：`{ "budget_id": 501, "period": "2026-08", "amount": "100000.00" }` |
| **错误码** | `401` `403 FORBIDDEN` `404 NOT_FOUND`（部门/项目/科目）`409 RESOURCE_CONFLICT`（同维度期间已存在，应走 PUT 调整）`422 VALIDATION_ERROR` |
| **副作用** | 写 `budget`；写 `audit_log`；影响下一次监控任务（参数化，不改代码） |

### PUT /api/budgets/{id} 调整预算

| 项 | 内容 |
|---|---|
| **路径** | `/api/budgets/{id}` |
| **方法** | `PUT` |
| **权限** | `budget:manage` |
| **允许状态** | — |
| **Request** | `application/json`：`{ "amount": "120000.00", "allocation_curve": [...] }`（调整金额，可附新分摊曲线） |
| **Response** | `200 OK`：`{ "id": 501, "period": "2026-08", "amount": "120000.00", "adjustment_id": 10 }` |
| **错误码** | `401` `403 FORBIDDEN` `404 NOT_FOUND` `422 VALIDATION_ERROR` |
| **副作用** | 写 `budget`（更新）+ 调整记录（留痕）；写 `audit_log`；影响下一次监控任务 |

---

## 4. 应收接口

### GET /api/ar/risk-ranking 高风险客户排名

| 项 | 内容 |
|---|---|
| **路径** | `/api/ar/risk-ranking` |
| **方法** | `GET` |
| **权限** | `ar:view` |
| **允许状态** | — |
| **Request** | Query：`limit`（默认 20）、`min_score`（默认 70，仅返回高风险） |
| **Response** | `200 OK`：`{ "items": [ { "customer_id": 1, "customer_name": "某某科技", "risk_score": 82, "risk_level": "high", "overdue_amount": "450000.00", "expected_payment_date": "2026-09-15", "expected_overdue_days": 28, "collection_priority": 1 } ] }`（风险分降序） |
| **错误码** | `401` `403 FORBIDDEN` `422 VALIDATION_ERROR` |
| **副作用** | 无（只读） |

### GET /api/ar/{customer_id}/detail 客户应收明细

| 项 | 内容 |
|---|---|
| **路径** | `/api/ar/{customer_id}/detail` |
| **方法** | `GET` |
| **权限** | `ar:view` |
| **允许状态** | — |
| **Request** | 路径参数 `customer_id` |
| **Response** | `200 OK`：`{ "customer": {...}, "receivables": [ { "receivable_id", "contract_no", "amount", "due_date", "overdue_days", "status" } ], "factors": { "aging_score": 25, "term_score": 20, "payment_score": 18, "collection_score": 19 }, "total_score": 82, "risk_level": "high", "expected_payment_date": "2026-09-15", "expected_overdue_days": 28 }` |
| **错误码** | `401` `403 FORBIDDEN` `404 NOT_FOUND` |
| **副作用** | 无（只读） |

### GET /api/ar/receivables 应收列表

| 项 | 内容 |
|---|---|
| **路径** | `/api/ar/receivables` |
| **方法** | `GET` |
| **权限** | `ar:view` |
| **允许状态** | — |
| **Request** | Query：`customer_id`、`status`（`open`/`partial`/`settled`，可选）、`due_before`（可选）、`page`、`page_size` |
| **Response** | `200 OK` 分页：`items` 元素含 `{ "receivable_id", "customer_id", "customer_name", "contract_no", "amount", "due_date", "overdue_days", "status" }`（`status` 由服务端维护，逾期由 `overdue_days > 0` 表达） |
| **错误码** | `401` `403 FORBIDDEN` `422 VALIDATION_ERROR` |
| **副作用** | 无（只读） |

### POST /api/ar/receivables 登记应收

| 项 | 内容 |
|---|---|
| **路径** | `/api/ar/receivables` |
| **方法** | `POST` |
| **权限** | `ar:manage` |
| **允许状态** | — |
| **Request** | `application/json`：`{ "customer_id": 1, "contract_id": 1, "invoice_no": "FP-2026-001", "amount": "500000.00", "due_date": "2026-09-15" }`（**不传 `status`**，由服务端初始化） |
| **Response** | `201 Created`：`{ "receivable_id": 88, "customer_id": 1, "status": "open" }` |
| **错误码** | `401` `403 FORBIDDEN` `404 NOT_FOUND`（客户/合同）`422 VALIDATION_ERROR` |
| **副作用** | 写 `ar_receivable`（`status` 初始 `open`）+ `audit_log`；影响下一次评分任务 |

### POST /api/ar/payments 登记回款

| 项 | 内容 |
|---|---|
| **路径** | `/api/ar/payments` |
| **方法** | `POST` |
| **权限** | `ar:manage` |
| **允许状态** | — |
| **Request** | `application/json`：`{ "receivable_id": 88, "customer_id": 1, "amount": "200000.00", "received_at": "2026-08-18T02:00:00Z", "remark": "" }` |
| **Response** | `201 Created`：`{ "payment_id": 45, "receivable_id": 88 }` |
| **错误码** | `401` `403 FORBIDDEN` `404 NOT_FOUND`（应收/客户）`422 VALIDATION_ERROR` |
| **副作用** | 写 `ar_payment`；按累计到账重算 `ar_receivable.status`（open/partial/settled）；**触发该客户风险分重算**（异步任务，幂等） |

### POST /api/ar/collection-records 登记催收记录

| 项 | 内容 |
|---|---|
| **路径** | `/api/ar/collection-records` |
| **方法** | `POST` |
| **权限** | `ar:manage` |
| **允许状态** | — |
| **Request** | `application/json`：`{ "customer_id": 1, "channel": "电话", "action": "催收", "result": "承诺 3 日内回款", "remark": "", "occurred_at": "2026-08-18T02:00:00Z" }` |
| **Response** | `201 Created`：`{ "record_id": 66, "customer_id": 1 }` |
| **错误码** | `401` `403 FORBIDDEN` `404 NOT_FOUND`（客户）`422 VALIDATION_ERROR` |
| **副作用** | 写 `collection_record`；**触发该客户风险分重算**（异步任务，幂等；验证催收记录登记后风险分相应变化，权重可配） |

---

## 5. 预警接口

### GET /api/alerts 预警中心

| 项 | 内容 |
|---|---|
| **路径** | `/api/alerts` |
| **方法** | `GET` |
| **权限** | `alert:view`（finance / budget_manager / ar_specialist / admin，**不授予 applicant**）；按业务域过滤：`budget` 预警 → finance / budget_manager，`ar` 预警 → finance / ar_specialist，admin 全量 |
| **允许状态** | — |
| **Request** | Query：`alert_type`（`budget`/`ar`，可选）、`level`（可选）、`read`（可选布尔）、`page`、`page_size` |
| **Response** | `200 OK` 分页：`items` 元素含 `{ "id", "alert_type", "level", "summary", "detail", "created_at", "read" }` |
| **错误码** | `401` `403 FORBIDDEN` `422 VALIDATION_ERROR` |
| **副作用** | 无（只读） |

### POST /api/alerts/{id}/read 标记已读

| 项 | 内容 |
|---|---|
| **路径** | `/api/alerts/{id}/read` |
| **方法** | `POST` |
| **权限** | `alert:manage` |
| **允许状态** | — |
| **Request** | 路径参数 `id` |
| **Response** | `200 OK`：`{ "id": 77, "read": true }`（幂等） |
| **错误码** | `401` `403 FORBIDDEN` `404 NOT_FOUND` |
| **副作用** | 更新 `read` 标记（轻操作，不记审计） |

---

## 6. 基础数据接口

> 共享基础层单一权威来源（架构 §3.1）：主数据（科目/部门/项目/客户/合同）、财务数据（预算/台账）、平台数据（系统参数/用户/角色）。

### GET /api/sys-params 系统参数列表

| 项 | 内容 |
|---|---|
| **路径** | `/api/sys-params` |
| **方法** | `GET` |
| **权限** | `sys:manage`（管理功能，见架构 §5.2） |
| **允许状态** | — |
| **Request** | Query：`key`（可选，精确匹配） |
| **Response** | `200 OK`：`{ "items": [ { "key": "threshold.reimb.date_window_days", "value": "180", "value_type": "int", "description": "发票允许报销区间（天）", "updated_by": "admin", "updated_at": "2026-08-18T00:00:00Z" } ] }` |
| **错误码** | `401` `403 FORBIDDEN` |
| **副作用** | 无（只读） |

### PUT /api/sys-params/{key} 更新系统参数

| 项 | 内容 |
|---|---|
| **路径** | `/api/sys-params/{key}` |
| **方法** | `PUT` |
| **权限** | `threshold.*` 键：`threshold:manage` 或 `sys:manage`；其余键：仅 `sys:manage` |
| **允许状态** | — |
| **Request** | `application/json`：`{ "value": "120" }` |
| **Response** | `200 OK`：`{ "key": "threshold.reimb.date_window_days", "value": "120", "updated_at": "..." }` |
| **错误码** | `401` `403 FORBIDDEN` `404 NOT_FOUND` `422 VALIDATION_ERROR`（类型不符） |
| **副作用** | 更新 `sys_param` + **写 `audit_log`（参数/阈值变更必审）**；下一次监控/审核任务即生效（参数化，不改代码） |

### GET /api/cost-categories 费用科目列表

| 项 | 内容 |
|---|---|
| **路径** | `/api/cost-categories` |
| **方法** | `GET` |
| **权限** | 登录即可（报销单/预算填写需科目下拉） |
| **允许状态** | — |
| **Request** | Query：`enabled_only`（默认 `true`）、`keyword`（可选） |
| **Response** | `200 OK`：`{ "items": [ { "id": 3, "code": "TRAVEL", "name": "差旅费", "parent_id": null, "enabled": true, "invoice_type_map": {...}, "keyword_map": {...} } ] }` |
| **错误码** | `401` |
| **副作用** | 无（只读） |

### POST /api/cost-categories 新建科目

| 项 | 内容 |
|---|---|
| **路径** | `/api/cost-categories` |
| **方法** | `POST` |
| **权限** | `cost_category:manage`（补充） |
| **允许状态** | — |
| **Request** | `application/json`：`{ "code": "ENTERTAIN", "name": "业务招待费", "parent_id": null, "enabled": true, "invoice_type_map": {...}, "keyword_map": {...} }` |
| **Response** | `201 Created`：`{ "id": 9, "code": "ENTERTAIN", "name": "业务招待费" }` |
| **错误码** | `401` `403 FORBIDDEN` `409 RESOURCE_CONFLICT`（code 重复）`422 VALIDATION_ERROR` |
| **副作用** | 写 `cost_category` + `audit_log` |

### PUT /api/cost-categories/{id} 更新科目

| 项 | 内容 |
|---|---|
| **路径** | `/api/cost-categories/{id}` |
| **方法** | `PUT` |
| **权限** | `cost_category:manage`（补充） |
| **允许状态** | — |
| **Request** | `application/json`：`{ "name": "业务招待费-修订", "enabled": false, "keyword_map": {...} }`（`code` 不可改） |
| **Response** | `200 OK`：更新后科目 |
| **错误码** | `401` `403 FORBIDDEN` `404 NOT_FOUND` `422 VALIDATION_ERROR` |
| **副作用** | 写 `audit_log`；停用后新报销/新预算不可引用（历史单据不追溯） |

### GET /api/departments 部门列表

| 项 | 内容 |
|---|---|
| **路径** | `/api/departments` |
| **方法** | `GET` |
| **权限** | 登录即可 |
| **允许状态** | — |
| **Request** | 无 |
| **Response** | `200 OK`：`{ "items": [ { "id": 1, "code": "SALES", "name": "销售部", "manager": "王五" } ] }` |
| **错误码** | `401` |
| **副作用** | 无（只读） |

### GET /api/projects 项目列表

| 项 | 内容 |
|---|---|
| **路径** | `/api/projects` |
| **方法** | `GET` |
| **权限** | 登录即可 |
| **允许状态** | — |
| **Request** | Query：`department_id`（可选） |
| **Response** | `200 OK`：`{ "items": [ { "id": 2, "code": "PJ-HD", "name": "华东大区", "department_id": 1, "owner": "赵六" } ] }` |
| **错误码** | `401` |
| **副作用** | 无（只读） |

### GET /api/customers 客户列表

| 项 | 内容 |
|---|---|
| **路径** | `/api/customers` |
| **方法** | `GET` |
| **权限** | `ar:view` |
| **允许状态** | — |
| **Request** | Query：`keyword`（可选） |
| **Response** | `200 OK`：`{ "items": [ { "id": 1, "code": "C-001", "name": "某某科技", "rating": "A", "credit": "500000.00" } ] }` |
| **错误码** | `401` `403 FORBIDDEN` |
| **副作用** | 无（只读） |

### POST /api/customers 新建客户

| 项 | 内容 |
|---|---|
| **路径** | `/api/customers` |
| **方法** | `POST` |
| **权限** | `ar:manage` |
| **允许状态** | — |
| **Request** | `application/json`：`{ "code": "C-002", "name": "某某制造", "rating": "B", "credit": "200000.00" }` |
| **Response** | `201 Created`：`{ "id": 2, "code": "C-002", "name": "某某制造" }` |
| **错误码** | `401` `403 FORBIDDEN` `409 RESOURCE_CONFLICT`（code 重复）`422 VALIDATION_ERROR` |
| **副作用** | 写 `customer` + `audit_log` |

### GET /api/contracts 合同列表

| 项 | 内容 |
|---|---|
| **路径** | `/api/contracts` |
| **方法** | `GET` |
| **权限** | `ar:view` |
| **允许状态** | — |
| **Request** | Query：`customer_id`（可选） |
| **Response** | `200 OK`：`{ "items": [ { "id": 1, "contract_no": "HT-2026-001", "customer_id": 1, "amount": "800000.00", "payment_term": 30, "status": "executing" } ] }` |
| **错误码** | `401` `403 FORBIDDEN` |
| **副作用** | 无（只读） |

### POST /api/contracts 新建合同

| 项 | 内容 |
|---|---|
| **路径** | `/api/contracts` |
| **方法** | `POST` |
| **权限** | `ar:manage` |
| **允许状态** | — |
| **Request** | `application/json`：`{ "contract_no": "HT-2026-002", "customer_id": 1, "amount": "300000.00", "payment_term": 45, "status": "executing" }` |
| **Response** | `201 Created`：`{ "id": 2, "contract_no": "HT-2026-002" }` |
| **错误码** | `401` `403 FORBIDDEN` `404 NOT_FOUND`（客户）`409 RESOURCE_CONFLICT`（合同号重复）`422 VALIDATION_ERROR` |
| **副作用** | 写 `contract` + `audit_log` |

### GET /api/ledger 支出台账查询

| 项 | 内容 |
|---|---|
| **路径** | `/api/ledger` |
| **方法** | `GET` |
| **权限** | `ledger:view`（财务；台账为单一权威来源，见需求 §4.1） |
| **允许状态** | — |
| **Request** | Query：`source`（`reimb`/`import`）、`department_id`、`project_id`、`cost_category_id`、`period_from`、`period_to`、`page`、`page_size` |
| **Response** | `200 OK` 分页：`items` 元素含 `{ "id", "source", "cost_category_id", "department_id", "project_id", "period", "amount", "occurred_at", "ref_no" }` |
| **错误码** | `401` `403 FORBIDDEN` `422 VALIDATION_ERROR` |
| **副作用** | 无（只读） |

### POST /api/ledger/import 台账导入（模拟其他支出源）

| 项 | 内容 |
|---|---|
| **路径** | `/api/ledger/import` |
| **方法** | `POST` |
| **权限** | `ledger:import`（补充） |
| **允许状态** | — |
| **Request** | `multipart/form-data`：`file`（CSV，列：`cost_category_code, department_code, project_code, period, amount, occurred_at, ref_no`） |
| **Response** | `201 Created`：`{ "imported_count": 96, "failed_rows": [ { "row": 3, "reason": "科目编码不存在" } ] }` |
| **错误码** | `401` `403 FORBIDDEN` `422 VALIDATION_ERROR`（文件空/列缺失/金额非法） |
| **副作用** | 批量写 `expense_ledger`（来源 `import`）；写 `audit_log`；影响次日预算监控 |

### GET /api/users 用户列表（系统管理）

| 项 | 内容 |
|---|---|
| **路径** | `/api/users` |
| **方法** | `GET` |
| **权限** | `user:manage` |
| **允许状态** | — |
| **Request** | Query：`role`（可选） |
| **Response** | `200 OK`：`{ "items": [ { "id": 1, "username": "zhang.san", "name": "张三", "roles": ["applicant"], "enabled": true } ] }` |
| **错误码** | `401` `403 FORBIDDEN` |
| **副作用** | 无（只读） |

### POST /api/users 新建用户（系统管理）

| 项 | 内容 |
|---|---|
| **路径** | `/api/users` |
| **方法** | `POST` |
| **权限** | `user:manage` |
| **允许状态** | — |
| **Request** | `application/json`：`{ "username": "li.si", "name": "李四", "password": "******", "roles": ["finance"] }` |
| **Response** | `201 Created`：`{ "id": 2, "username": "li.si", "roles": ["finance"] }` |
| **错误码** | `401` `403 FORBIDDEN` `409 RESOURCE_CONFLICT`（用户名重复）`422 VALIDATION_ERROR` |
| **副作用** | 写 `sys_user` + 角色关联 + `audit_log` |

### GET /api/roles 角色列表（系统管理）

| 项 | 内容 |
|---|---|
| **路径** | `/api/roles` |
| **方法** | `GET` |
| **权限** | `role:manage` |
| **允许状态** | — |
| **Request** | 无 |
| **Response** | `200 OK`：`{ "items": [ { "code": "finance", "name": "财务审核", "permissions": ["reimb:audit", "reimb:manual_review", "ledger:view", "ledger:import", "alert:view"] } ] }` |
| **错误码** | `401` `403 FORBIDDEN` |
| **副作用** | 无（只读） |

---

## 附：接口清单速览

| 域 | 方法 | 路径 |
|---|---|---|
| 认证 | POST | `/api/auth/login` |
| 认证 | POST | `/api/auth/logout` |
| 认证 | GET | `/api/auth/me` |
| 报销 | POST | `/api/reimbursements` |
| 报销 | GET | `/api/reimbursements` |
| 报销 | GET | `/api/reimbursements/{id}` |
| 报销 | PUT | `/api/reimbursements/{id}` |
| 报销 | POST | `/api/reimbursements/{id}/attachments` |
| 报销 | DELETE | `/api/reimbursements/{id}/attachments/{attachment_id}` |
| 报销 | POST | `/api/reimbursements/{id}/submit` |
| 报销 | GET | `/api/audit-tasks/{task_id}` |
| 报销 | POST | `/api/reimbursements/{id}/manual-review` |
| 报销 | POST | `/api/reimbursements/{id}/return` |
| 报销 | GET | `/api/reimbursements/{id}/report` |
| 预算 | GET | `/api/deviations` |
| 预算 | GET | `/api/deviations/summary` |
| 预算 | GET | `/api/monitor/status` |
| 预算 | GET | `/api/budgets` |
| 预算 | POST | `/api/budgets` |
| 预算 | PUT | `/api/budgets/{id}` |
| 应收 | GET | `/api/ar/risk-ranking` |
| 应收 | GET | `/api/ar/{customer_id}/detail` |
| 应收 | GET | `/api/ar/receivables` |
| 应收 | POST | `/api/ar/receivables` |
| 应收 | POST | `/api/ar/payments` |
| 应收 | POST | `/api/ar/collection-records` |
| 预警 | GET | `/api/alerts` |
| 预警 | POST | `/api/alerts/{id}/read` |
| 基础数据 | GET/PUT | `/api/sys-params` / `/api/sys-params/{key}` |
| 基础数据 | GET/POST/PUT | `/api/cost-categories` |
| 基础数据 | GET | `/api/departments` |
| 基础数据 | GET | `/api/projects` |
| 基础数据 | GET/POST | `/api/customers` |
| 基础数据 | GET/POST | `/api/contracts` |
| 基础数据 | GET/POST | `/api/ledger` / `/api/ledger/import` |
| 基础数据 | GET/POST | `/api/users` |
| 基础数据 | GET | `/api/roles` |
