# 技术选型

> 财务智能助手平台 · 版本 v0.1（设计评审稿）

---

## 1. 选型总表

| 层 | 选型 | 版本 | 与 2.7 关系 | 理由 |
|---|---|---|---|---|
| 语言 | Python | 3.11+（本机 3.12.8 / venv 3.11） | 沿用 | 生态成熟 |
| Web 框架 | FastAPI | 2.x | 沿用 | 异步友好、Pydantic 原生、OpenAPI 自动生成 |
| ORM | SQLAlchemy | 2.x | 沿用 | 成熟声明式 ORM，事务一致性好 |
| 校验/DTO | Pydantic | v2 | 沿用 | LLM 输出与 HTTP 边界强校验（禁止自由文本） |
| 数据库 | MySQL 8（Docker） | 8.x | 沿用 | 演示可切 SQLite（`DATABASE_URL`），验证用 MySQL |
| 消息代理 | Redis | 7.x | 新增 | Celery broker；**仅传输，不存权威状态** |
| 任务队列 | Celery | 5.x | 升级替代 | 报销解析（事件）+ 预算/应收（beat 每日），工程化异步边界 |
| 定时 | Celery beat | 随 Celery | 新增 | 预算监控/应收预警日调度（节奏参数化） |
| 前端 | 原生 HTML/CSS/JS 单页 | — | 沿用方案 | 无构建、可解释；三助手面板 + 预警中心 |
| OCR | 百度云（发票专用 + 通用） | REST | 沿用 | 中文发票识别成熟；适配层可换厂商 |
| LLM | DeepSeek（OpenAI 兼容） | — | 沿用 | 字段提取/科目兜底/报告润色；适配层可换 |
| PDF | pypdf + PyMuPDF | — | 沿用 | 文本型直取；扫描型逐页渲染→OCR |
| 统计 | 自研（numpy/scipy 可选） | — | 新增 | EWMA/CUSUM/MAD 轻量实现，避免引重依赖 |
| 依赖管理 | pyproject.toml | — | 升级 | 统一管理 + 可选 uv；见 dev-standards |
| 质量 | Ruff / pyright / pytest | — | 升级 | 现代默认包，见 dev-standards |

---

## 2. 关键取舍记录（为什么选 / 为什么不选）

### 2.1 为什么不引 Celery 之外的队列
2.7 用进程内 asyncio 队列守住 Demo 边界；本平台有**周期调度 + 并发任务**需求，升级 Celery + Redis。不选 RQ/消息队列：Celery 的 beat + worker + 重试 + 任务状态钩子开箱即用，演示与面试叙事都最顺。

### 2.2 为什么 Redis 仅作 broker
财务结论必须落 DB（审计、重跑一致性、防 Redis 丢失）。Redis 只承担任务传输，不做结果权威存储——这条写进 DESIGN.md 作为原则。

### 2.3 为什么不用 ML 做应收预测
演示数据无真实历史逾期标签可学，且结论不可解释。选**规则加权评分**（确定性、可审计），引擎预留模型接口（见 architecture §9）。

### 2.4 为什么 3.3.2 用「阈值主干 + 统计辅助」
纯阈值抓不住渐变失控；纯统计不可审计、演示数据下不稳定。选阈值定义正式偏差、EWMA/CUSUM/MAD 做提示级信号、多信号/连续 N 期确认才升级。

### 2.5 为什么不引重前端框架
Vue/React + 构建链增加不可解释性，与"最小必要依赖"原则冲突；原生单页三面板规模足够。

### 2.6 为什么不引重型统计/ML 框架
numpy/scipy 足够支撑 EWMA/CUSUM/MAD；statsmodels/sklearn 无必要（当前无 ML 组件）。

### 2.7 LLM 边界
LLM 只做：扫描件字段结构化提取（Pydantic 校验）、科目推荐规则盲区兜底、报告润色。**不做任何结论判定**。

---

## 3. 外部服务与降级约定

| 服务 | 配置 | 未配置时的行为 |
|---|---|---|
| OCR | `OCR_API_KEY` / `OCR_SECRET_KEY` | `preset`/`auto` 模式走预设解析结果 |
| LLM | `LLM_API_KEY` / `LLM_BASE_URL` | 同上降级，科目兜底退化为规则命中或人工复核 |
| Webhook 邮件 | `SMTP_*` | 仅站内投递 |
| Webhook 企微/钉钉 | `WECOM_*` / `DINGTALK_*` | 仅站内投递 |

沿用 2.7 的 `ocr.mode` 三模式约定：`real`（真实调用失败即失败）/ `auto`（真实→失败回退预设）/ `preset`（仅预设，不调外部 API）。演示默认 `auto`。

---

## 4. 运行拓扑（单机演示）

```
docker-compose up → mysql:8 + redis:7 + backend + celery-worker + celery-beat
seed.py → 角色/权限/科目/部门/项目/预算/台账/客户/合同/应收/付款/催收/演示单据
浏览器 → http://127.0.0.1:8000
```

- 数据库：默认 MySQL 8（Docker）；`DATABASE_URL=sqlite:///./dev.db` 可切 SQLite 免 Docker 跑通链路。
- Celery：`celery -A app.worker worker` + `celery -A app.worker beat` 双进程由 compose 编排。
