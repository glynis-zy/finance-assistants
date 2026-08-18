# 财务智能助手平台（Finance Assistants）

基于设计文档 `zy-项目实战.md` 第 3.3 节「财务管理」实现。**单平台 + 三助手**，共享基础数据层，三个服务型 Agent 挂载其上：

- **3.3.1 发票报销审核助手**：识别发票/行程单/审批单，校验材料完整性与财务合规性，推荐费用科目，输出通过/退回/人工复核。
- **3.3.2 预算执行偏差监控助手**：按部门×项目×科目×期间对比预算与实际，识别超预算、进度异常、异常增长，输出偏差金额/比例/责任范围。
- **3.3.3 应收账款逾期预警助手**：结合账龄/账期/付款历史/催收记录预测逾期风险，输出高风险客户/应收金额/预计逾期时间/催收优先级。

**核心设计哲学**（承 2.7 并扩展）：

> **OCR 负责"看懂文档"，LLM 负责"理解非结构化文本"与规则盲区兜底，规则引擎负责"确定性判定"，LLM 只做最后的"自然语言解释"。结论永远由规则引擎决定，存疑一律人工复核（fail-closed）。**

**异步边界**：2.7 用进程内 asyncio 队列（仅单进程 Demo 边界）；本平台升级为 **Celery + Redis**（工程化异步边界）。Redis 仅作 broker，任务状态与结论全落 DB，支持多 worker、可重试、失败可查（仅凭 Celery + Redis 不构成完整生产级，部署/监控/容灾不在 V1 范围）。

## 文档地图

| 文档 | 内容 |
|---|---|
| [docs/requirements.md](docs/requirements.md) | 需求规格：三助手输入/处理/输出/规则清单、角色权限、数据模型、验收标准 |
| [docs/architecture.md](docs/architecture.md) | 架构：分层总览、数据归属、Celery 异步与调度、API、权限、部署、对 2.7 复用评估 |
| [docs/api.md](docs/api.md) | API 契约：统一响应/分页/ID·金额·时间格式、认证、报销/预算/应收/预警/基础数据接口（路径·方法·权限·允许状态·请求响应·错误码·副作用） |
| [docs/tech-stack.md](docs/tech-stack.md) | 技术选型：选型总表、取舍记录、外部服务降级约定 |
| [docs/dev-standards.md](docs/dev-standards.md) | 开发规范：Ruff/pyright/pytest/pre-commit、Git 规范、目录结构 |
| [docs/DESIGN.md](docs/DESIGN.md) | 设计原则与模式：原则 11 条、模式落点、面试问答预演 |

## 技术栈速览

Python 3.12 · FastAPI · SQLAlchemy 2 · Pydantic v2 · MySQL 8（可切 SQLite）· Redis · Celery · 原生 HTML/CSS/JS 单页 · 百度 OCR / DeepSeek LLM（适配层可换）。

## 当前状态

**需求已冻结**——`docs/requirements.md` v1.0 评审通过。后续进入实现（backend + frontend + docker-compose + seed 演示数据）；实现中发现非阻塞边界问题按最简单可运行方案处理，不再扩大评审范围。

## 相关项目

- `Desktop/finance-risk-review`：2.7 节「财务单据智能风险审核系统」，本平台的模式与适配层来源（详见 [architecture.md](docs/architecture.md) §8 复用评估）。
