# 架构文档

> 财务智能助手平台 · 单平台 + 三助手
> 版本：v0.1（设计评审稿）｜ 状态：设计阶段

---

## 1. 架构总览

```
┌──────────────────────────── 统一 Web 控制台（原生 HTML/CSS/JS，无构建）───────────────────────────┐
│  报销审核面板   预算监控面板   应收预警面板   预警中心   系统管理（用户/参数）                       │
└───────────────────────────────────────────────┬──────────────────────────────────────────────┘
                                                │ REST API（FastAPI routers，薄控制器）
┌───────────────────────────────────────────────┴──────────────────────────────────────────────┐
│                                   服务层（一个 service 一个领域）                                │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐   共享基础服务：                           │
│  │ 报销审核助手 │  │ 预算监控助手 │  │ 应收预警助手 │   cost_category / budget / expense_ledger│
│  │ reimbursement│ │   budget_mon│  │   ar_warning │   customer / contract / sys_param         │
│  │ _audit       │  │   itoring   │  │             │   alert / notification / audit            │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘                                             │
└─────────┼────────────────┼────────────────┼──────────────────────────────────────────────────┘
          │                │                │
┌─────────┴────────────────┴────────────────┴─────────────────────────────────────────────────┐
│  领域层（确定性引擎，结论拍板处，可单测）                                                        │
│  risk_engine(规则注册表)   deviation_engine(阈值+统计)   scoring_engine(加权评分)  document      │
│                                                                  schemas(单据类型元数据)          │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
          │                          │                              │
┌─────────┴──────────────────────────┴──────────────────────────────┴─────────────────────────┐
│  适配层（依赖倒置，厂商可换）                                                                    │
│  clients/ocr(百度·可换)  clients/llm(DeepSeek·可换)  clients/webhook(邮件/企微/钉钉·可换)        │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
          │
┌─────────┴──────────────────────────────────────────────────────────────────────────────────┐
│  任务层（Celery + Redis broker）    beat(每日预算/应收) + worker(报销解析/监控/评分/投递)        │
│  任务状态与结果落 DB（Redis 仅传输，不存权威状态）                                                │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
          │
┌─────────┴──────────────────────────────────────────────────────────────────────────────────┐
│  数据层（MySQL 8，可切 SQLite 演示）  共享基础层表 + 报销/预算/应收域表 + 预警表 + 审计表          │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
```

**一句话**：展示层 → API 层（薄）→ 服务层（三助手 + 共享基础服务）→ 领域层（确定性引擎拍板）→ 适配层（OCR/LLM/Webhook 可换）→ 任务层（Celery 异步）→ 数据层（单一权威来源）。

---

## 2. 分层设计

### 2.1 展示层
原生 HTML/CSS/JS 单页（无构建，FastAPI 托管静态资源），四个面板 + 系统管理。与 2.7 前端同方案，前端轮询任务状态（`/tasks/{id}`）。

### 2.2 API 层（`routers/`）
薄控制器：收 HTTP 参数、做权限依赖注入（`Depends`）、调服务、回 DTO。不写业务。

### 2.3 服务层（`services/`）
一个 service 一个领域，互不掺和：
- 报销域：`reimbursement_service`（单据）、`audit_service`（审核调度）、`report_service`（报告）、`attachment_service`（文件）、`parse_pipeline`（解析流水线）；
- 预算域：`budget_service`（预算维护）、`deviation_service`（偏差计算）、`monitor_service`（监控调度）；
- 应收域：`ar_service`（应收/付款/催收）、`scoring_service`（评分）；
- 共享：`ledger_service`（台账）、`cost_category_service`（科目）、`customer_service`、`contract_service`、`sysparam_service`（参数）、`alert_service`（预警）、`notification_service`（投递）、`audit_service`（审计）、`auth_service`。

### 2.4 领域层（`domain/`）
确定性引擎，**结论拍板处，禁止 LLM 参与**：
- `risk_engine`：报销合规规则注册表（完整性 + 合规性，config 驱动）；
- `deviation_engine`：偏差/进度/增长阈值判定 + 统计信号（EWMA/CUSUM/MAD）；
- `scoring_engine`：应收风险加权评分 + 分档 + 预计逾期时间公式；
- `document_schemas`：单据类型元数据（字段定义 + 校验），加类型不加代码。

### 2.5 适配层（`clients/`）
- `ocr/`：百度云（发票专用 + 通用），实现统一 `OCRClient` 接口；
- `llm/`：DeepSeek（OpenAI 兼容），实现 `LLMClient` 接口：字段提取（Pydantic 校验）、科目兜底候选、报告润色；
- `webhook/`：邮件/企微/钉钉，实现 `Notifier` 接口，配置驱动启用。

业务代码只依赖接口，不依赖厂商 SDK（DIP）。

### 2.6 任务层（Celery + Redis）
- **broker**：Redis，仅传输任务；
- **beat 调度**：每日预算监控、每日应收预警（节奏参数化）；
- **worker**：报销解析（事件触发）、监控、评分、预警投递；
- **任务状态**：任务入队/执行中/成功/失败落 DB（`audit_task` 等），结论与结果全落 DB；Redis 重启不丢已产生结论；
- **幂等**：预警按唯一键（维度+期间 / 客户+应收单）去重；投递按 `notification` 表状态去重。

---

## 3. 数据模型与归属

### 3.1 归属总图
```
共享基础层（单一权威来源）
├─ 主数据：cost_category / org_department / project / customer / contract
├─ 财务数据：budget / expense_ledger
└─ 平台数据：sys_user/sys_role/sys_permission / sys_param / audit_log

报销域（3.3.1 私有）         预算域（3.3.2 私有）      应收域（3.3.3 私有）
reimbursement*               budget_deviation          ar_receivable
doc_parse_result             budget_snapshot           ar_payment
audit_conclusion             stat_signal               collection_record
audit_task                                             ar_risk_score

预警域：alert / notification（三助手共用）
```

### 3.2 关键写读关系
- **台账写入**：报销审核结论为「通过」→ 事务内写 `expense_ledger`；另支持导入模拟其他支出源；
- **台账读取**：预算监控只读台账与预算；报销预算检查读预算；
- **应收域**：引用共享层 `customer` / `contract` 主数据，业务表自持；
- **一致性**：所有写操作在同一 DB 事务内完成，无分布式事务负担（单平台优势）。

---

## 4. 异步与调度架构

### 4.1 链路
| 场景 | 触发 | 执行 | 结果 |
|---|---|---|---|
| 报销审核 | 提交报销单 → 入队 | worker：解析→提取→校验→科目→结论 | 落 `audit_conclusion` + 台账（通过时），前端轮询 |
| 预算监控 | Celery beat 每日 | worker：对比→偏差→统计信号→预警 | 落 `budget_deviation` + `budget_snapshot` + `alert` |
| 应收预警 | Celery beat 每日 | worker：评分→分档→预警 | 落 `ar_risk_score` + `alert` |
| 预警投递 | 预警产生 | worker：站内必达 + webhook（配置启用） | 落 `notification` |

### 4.2 边界声明（写进 README，面试要主动说清）
Redis 仅作 broker；任务状态与结论**全落 DB**。相比 2.7 的进程内 asyncio 队列（仅单进程 Demo 边界），本平台升级为 Celery + Redis 的**工程化异步边界**：支持多 worker、可重试、失败可查；`docker-compose` 起 worker + beat 双进程。注意：仅凭 Celery + Redis 不构成完整生产级，部署/监控/容灾不在 V1 范围。Celery 任务本身仍建议幂等（如按任务参数生成唯一键）。

### 4.3 调度节奏（参数化，sys_param 可调）
- `schedule.budget_monitor` = `0 0 8 * * *`（每日 08:00，可配）；
- `schedule.ar_warning` = `0 30 8 * * *`（每日 08:30，可配）；
- 报销解析 = 事件触发（不设 beat）。

---

## 5. API 设计概览

### 5.1 报销域
| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/reimbursements` | 新建报销单（草稿态） |
| GET | `/api/reimbursements` | 列表（申请人行级过滤；`status` 筛选 + 分页） |
| GET | `/api/reimbursements/{id}` | 详情（含明细、附件、最新审核结论） |
| PUT | `/api/reimbursements/{id}` | 更新（仅 `draft`/`returned` 态；整体替换含明细） |
| POST | `/api/reimbursements/{id}/attachments` | 上传附件（multipart 多文件 + `category`：invoice/travel/approval） |
| DELETE | `/api/reimbursements/{id}/attachments/{attachment_id}` | 删除附件（仅 `draft`/`returned` 态） |
| POST | `/api/reimbursements/{id}/submit` | 提交 → 触发审核任务，返回 `task_id`（重复提交 409） |
| POST | `/api/reimbursements/{id}/manual-review` | 财务对 `manual_review` 态单据落结论（approved/returned，`reason` 必填） |
| POST | `/api/reimbursements/{id}/return` | 财务主动退回（仅 `pending` 态，`reason` 必填） |
| GET | `/api/audit-tasks/{task_id}` | 任务状态轮询（queued/parsing/done/failed） |
| GET | `/api/reimbursements/{id}/report` | 报告（HTML 导出） |

> 状态机：`draft → pending → approved / returned / manual_review`；`manual_review` 经财务裁决（manual-review）落 `approved`/`returned`；`returned` 可编辑后重新提交回 `pending`。结论由规则引擎判定，无法判定一律 `manual_review`（fail-closed）；`pending` 态仅财务可操作，`approved` 终态不可修改。

### 5.2 预算域
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/deviations` | 偏差明细（部门/项目/科目/期间/等级过滤） |
| GET | `/api/deviations/summary` | 汇总（按部门/项目/科目聚合） |
| GET | `/api/monitor/status` | 最近一次监控任务状态/快照 |
| GET | `/api/budgets` | 预算列表（budget_year 年度过滤） |
| POST | `/api/budgets` | 新建年度预算（budget_year + 12 个月分摊曲线） |
| PUT | `/api/budgets/{id}` | 调整预算（写 BudgetAdjustment 留痕） |
| GET | `/api/sys-params`（管理） | 阈值/调度节奏读写 |

> 口径（Stage 3 修正）：预算粒度 = 部门×项目×科目×年度（`budget_year=YYYY`），
> 偏差事实记录按 部门×项目×科目×期间（`YYYY-MM`）存储；汇总在查询层按维度聚合。

### 5.3 应收域
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/ar/risk-ranking` | 高风险客户排名（最新评分，风险分降序，默认 min_score=70） |
| GET | `/api/ar/{customer_id}/detail` | 客户应收明细 + 因子明细（raw/weight/weighted）+ 总分 |
| GET | `/api/ar/receivables` | 应收列表（客户/状态/到期前过滤） |
| POST | `/api/ar/receivables` | 登记应收（status 默认 open，合同须属客户） |
| POST | `/api/ar/payments` | 登记回款（超额拒绝，按累计到账重算 status，触发该客户重算） |
| POST | `/api/ar/collection-records` | 登记催收记录（触发该客户重算） |
| GET | `/api/ar/risk-status` | 最近一次全量评分任务状态（ar_risk_run） |
| GET | `/api/alerts` | 预警中心（类型/级别过滤，已读标记） |

> 口径（Stage 4）：评分确定性规则（scoring_engine，无 LLM）；每客户每评分日一条
> `ar_risk_score`（unique(customer_id, score_date)，同日 upsert）；beat 每日 08:30 全量评分。

> 权限码、数据权限、状态权限全部在路由依赖层强制，见 §6。

---

## 6. 权限架构

沿用 2.7 三级纵深防御：
1. **L1 角色权限**：`require_perm("reimb:create")` 等权限码依赖注入路由；
2. **L2 数据权限**：`scopes.visible_*_ids()` 在查询层强制过滤（报销按申请人、应收按专员域）；
3. **L3 状态权限**：状态守卫表（动作 × 允许状态）显式校验，非前端隐藏。

任何一层不过即 4xx。审计日志记录登录与关键变更。

权限收口（v1.0 冻结，详见 api.md §0.4）：
- finance 默认补 `budget:view`（对应其「查看台账与偏差」职责，requirements §3.1）。
- `sys_param` 修改：`threshold.*` 键允许 `threshold:manage` 或 `sys:manage` 修改；其余键仅 `sys:manage`。
- 预警可见性：`alert:view` 授予 finance / budget_manager / ar_specialist / admin（不授予 applicant）；预算类预警仅 finance / budget_manager 可见，应收类预警仅 finance / ar_specialist 可见，admin 全量可见。

---

## 7. 部署架构

```
docker-compose.yml
├─ mysql:8        （3306，卷持久化；演示可切 DATABASE_URL=sqlite）
├─ redis:7        （6379，Celery broker）
├─ backend        （uvicorn 应用 + 托管前端静态资源）
├─ celery-worker  （消费报销/监控/评分/投递任务）
└─ celery-beat    （每日调度）
```

- 演示单机可起，`--workers` 无单进程限制（相比 2.7 的强约束已解除）；
- 未配置 OCR/LLM key 时走 `preset`/`auto` 降级（沿用 2.7 约定），链路始终可跑；
- seed 脚本灌入角色/权限/科目/部门/项目/预算/台账/客户/合同/应收/付款/催收/演示单据，并触发一次监控与评分。

---

## 8. 对 2.7 项目（finance-risk-review）的复用评估

| 资产 | 复用决策 | 理由 |
|---|---|---|
| 技术栈（FastAPI/SQLAlchemy/Pydantic/原生前端） | **沿用** | 已验证、单平台下成本最低 |
| 四层流水线理念（OCR→LLM→规则→润色） | **沿用** | 3.3.1 报销审核与之同构 |
| 规则引擎注册表（策略模式） | **沿用并扩展** | 报销规则注册表直接复用模式；新增偏差/评分两个引擎 |
| OCR/LLM 适配层 | **沿用抽象，实现可复制后调整** | `OCRClient`/`LLMClient` 接口一致；百度/DeepSeek 厂商不变 |
| 权限模型（RBAC+数据+状态） | **沿用** | 三级纵深防御直接迁移 |
| `sys_param` 系统参数 | **沿用** | 阈值/权重/调度节奏参数化 |
| 异步方案（进程内 asyncio 队列） | **不沿用，升级 Celery+Redis** | 3.3 需周期调度与多任务并发，2.7 方案是 Demo 边界 |
| 单据类型元数据（document_schemas） | **沿用** | 报销单/发票/行程单/审批单类型化描述 |
| 前端页面 | **不直接复用** | 三助手面板为全新布局，但沿用无构建技术方案 |

> 结论：**架构与模式全面复用，代码按 3.3 数据模型重建**。2.7 未提交的 E2E/集成测试收尾不并入本平台。

---

## 9. 演进边界（生产可替换点）

| 点 | 现状 | 演进 |
|---|---|---|
| 异步 | Celery + Redis | 可平滑换 RQ / 消息队列，任务状态已落 DB |
| OCR/LLM | 百度 / DeepSeek | 换厂商只动 `clients/` 适配层与 `.env` |
| 数据库 | MySQL 8 / SQLite | 数据全在共享层，无分库负担 |
| 统计信号 | EWMA/CUSUM/MAD | 可叠加时间序列分解、贝叶斯变点检测，仅升级 `deviation_engine` |
| 应收评分 | 规则加权 | 有历史逾期标签时可叠加 ML 概率修正，`scoring_engine` 预留模型接口 |
| 投递通道 | 站内 + Webhook | 增渠道只加一个 `Notifier` 实现 |
