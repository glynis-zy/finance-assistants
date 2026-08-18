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

**V1 部署闭环已完成**（Stage 1~6A）：三助手全部落地（报销审核 / 预算偏差监控 / 应收预警），共享平台接口与前端 MVP 就绪，附件真实持久化（backend 与 worker 共享存储），Docker 一键启动（init-db 自动迁移+seed）。真实 OCR/LLM/Webhook 厂商接入留待 Stage 6B。

## 快速启动（preset 模式，无需任何外部 Key）

### 方式一：Docker 一键启动（推荐，MySQL + Redis + Celery 全栈）

```bash
docker compose down -v        # 首次或想重置数据时执行
docker compose up --build     # 自动：mysql 就绪 → alembic 迁移 → seed → backend/worker/beat
# 浏览器打开 http://localhost:8000
```

数据（MySQL 卷）与上传附件（uploads 卷）持久化在 Docker volume；`docker compose restart` 后数据与状态保持不变。

### 方式二：本地直接跑（SQLite，无 Docker）

```bash
cd backend
python -m alembic upgrade head
PYTHONPATH=. python scripts/seed.py
PYTHONPATH=. python -m uvicorn app.main:app --port 8000
# 浏览器打开 http://127.0.0.1:8000
```

### OCR / LLM 三模式（Stage 6B）

| 模式 | 行为 | 适用 |
|---|---|---|
| `preset`（默认） | 不调用外部 API，使用内置预设解析结果，无需任何 Key | 演示 / 离线 |
| `auto` | 先调真实厂商，失败自动回退 preset | 接真实验证但允许降级 |
| `real` | 只调真实厂商，失败即失败（不 fallback） | 生产接入 |

结论判定永远由规则引擎负责，OCR/LLM 只做识别与提取，**LLM 不能决定 approved/returned**。

### 百度 OCR 配置（real 模式）

1. 百度智能云控制台创建「文字识别」应用，获取 **API Key** 与 **Secret Key**
2. 配置环境变量后启动：

```bash
cd backend
cp .env.example .env
# 编辑 .env：
#   OCR_MODE=real
#   OCR_API_KEY=你的API Key
#   OCR_SECRET_KEY=你的Secret Key
PYTHONPATH=. python -m uvicorn app.main:app --port 8000
```

- invoice 附件走**增值税发票识别**接口（结构化字段）；travel/approval 走**通用文字识别**（全文交 LLM 提取）
- access_token 自动获取并进程内缓存（官方默认 30 天，过期前 5 分钟刷新），日志不输出任何凭证

### DeepSeek 配置（real 模式）

1. DeepSeek 开放平台申请 API Key（OpenAI 兼容接口）
2. 配置环境变量：

```bash
#   LLM_MODE=real
#   LLM_API_KEY=你的API Key
#   LLM_BASE_URL=https://api.deepseek.com   （官方默认，可省略）
#   LLM_MODEL=deepseek-v4-flash              （以官方文档为准）
```

- 字段提取与科目推荐使用严格 JSON 输出（`response_format=json_object`），结果仍过 Pydantic 校验
- LLM 推荐科目超出白名单（TRAVEL/OFFICE/ENTERTAIN/MEETING）或低置信度 → 不采纳（manual_review），不会产生不存在的科目
```

不配置百度 OCR / DeepSeek / Webhook 任何 Key，靠 preset/auto 模式即可完整演示三助手（real 厂商接入见 Stage 6B）。

## 演示账号（seed 内置）

| 用户名 | 密码 | 角色 | 可演示内容 |
|---|---|---|---|
| `admin` | `admin123` | 系统管理员 | 预警中心（全量）、系统管理（用户/角色/参数/科目） |
| `zhang.san` | `123456` | 报销申请人 | 报销列表/新建/编辑/附件/提交/轮询结果/审核报告 |
| `finance.li` | `123456` | 财务审核 | 报销审核（退回/人工裁决）、台账查询、预算监控、预警中心 |
| `budget.wang` | `123456` | 预算管理员 | 预算管理（新建/调整留痕）、偏差明细/汇总、预警中心（budget） |
| `ar.zhao` | `123456` | 应收专员 | 应收列表/新增/回款/催收、风险排名/客户详情、预警中心（ar） |

## seed 演示场景

- **报销**：`BX-2026-0001` approved（已写台账）· `0002` returned（发票抬头不符）· `0003` manual_review（财务裁决）
- **预算**：销售差旅 120 万正常（60 万=计划 60 万不误报）· 销售招待 20 万超支 high（→ budget 预警）· 销售办公 30 万增长异常 · 研发差旅进度落后 · 研发办公 low
- **应收**：A 客户 86 分 high（催收后未回款）· B 客户 medium（催收后已回款，collection=0，含 partial 应收）· C 客户 0 分 low（无未结）
- **预警**：budget alert（超支 high）+ ar alert（score ≥ 70），预警中心两类可见

## 相关项目

- `Desktop/finance-risk-review`：2.7 节「财务单据智能风险审核系统」，本平台的模式与适配层来源（详见 [architecture.md](docs/architecture.md) §8 复用评估）。
