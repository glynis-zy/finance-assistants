# 开发规范

> 财务智能助手平台 · 版本 v0.1（设计评审稿）

---

## 1. 语言与版本

- Python **3.12+**；单 repo 单虚拟环境（`.venv`）。
- 依赖统一在根 `pyproject.toml` 声明（`[project]` + `[tool.*]`），生产/开发/任务依赖分组；可选 `uv` 加速。

## 2. 代码风格

| 工具 | 职责 | 关键配置 |
|---|---|---|
| Ruff | lint + format | `line-length=100`；选择 `E/F/W/I/UP/B/SIM` 规则集；`format` 为默认 |
| pyright | 严格类型检查 | `typeCheckingMode=strict`；Pydantic/SQLAlchemy 模型显式类型标注 |

- 全库类型标注：函数签名、DTO、ORM 模型必须标注类型；禁止 `Any` 泄漏（适配层边界除外）。
- 命名：模块/函数/变量 `snake_case`；类 `PascalCase`；常量 `UPPER_SNAKE`；表名 `snake_case` 复数；权限码 `domain:action`。

## 3. 文档与注释

- **Google 风格 docstring**（中文）：模块、公开类、公开函数必须有。
- 注释写"为什么"不写"是什么"；复杂规则/公式旁必须标注口径来源（`requirements.md` 对应条款）。
- 代码内中文术语与需求规格一致（科目/台账/账龄/账期等），不发明新词。

## 4. 测试

| 层 | 工具 | 覆盖对象 | 门槛 |
|---|---|---|---|
| 单元 | pytest | 确定性引擎（`risk_engine` / `deviation_engine` / `scoring_engine`）、规则注册表、评分因子 | 引擎函数 100% 关键分支 |
| 服务 | pytest | service 层编排、事务（通过→写台账） | 核心链路断言 |
| API | FastAPI `TestClient` | 路由、权限三级、DTO 校验 | 越权一律 4xx 断言 |
| 冒烟 | pytest 脚本 | seed → 三助手各档位结论 → 预警投递 全链路 | 端到端可跑 |
| 集成 | 脚本 | Celery 任务入队/执行/落库；webhook 通道 | 任务状态断言 |

- 命名：`test_<模块>_<行为>`；断言看行为不看实现。
- 覆盖率工具 `coverage.py`；演示规模不设硬性全局门槛，但**引擎与权限为必测**。

## 5. pre-commit 钩子

| 钩子 | 作用 |
|---|---|
| `ruff check` + `ruff format --check` | lint + 格式 |
| `pyright` | 类型 |
| 私有 key 扫描 | 防 `.env`/密钥入库 |
| 尾部空白/文件末尾 | 基础卫生 |

## 6. Git 规范

- **分支模型**：`main`（可发布） + `feat/*`（功能） + `fix/*`（缺陷）。禁止直接推 `main`，PR 合并。
- **提交信息**：类型前缀 + 中文短语描述。
  ```
  feat: 报销审核规则注册表接入预算检查
  fix: 台账事务在结论通过时未写入
  refactor: deviation_engine 拆分统计信号模块
  test: 应收评分分档边界用例
  docs: requirements 3.3.2 统计升级口径
  ```
- 一次提交一个逻辑变更；不夹带无关改动。
- 提交前跑 `pre-commit` + 相关单测。

## 7. 目录结构（目标形态）

```
finance-assistants/
├── docs/                    # 本目录五件套
├── backend/
│   └── app/
│       ├── routers/         # HTTP 控制器（薄）
│       ├── services/        # UseCase 编排（报销/预算/应收/共享）
│       ├── repositories/    # 数据访问聚合
│       ├── domain/          # risk_engine / deviation_engine / scoring_engine / document_schemas
│       ├── clients/         # ocr / llm / webhook 适配层
│       ├── core/            # config / security / perms / scopes / deps
│       ├── db/              # session / init / 迁移（Alembic）
│       ├── models/          # SQLAlchemy ORM
│       ├── schemas/         # Pydantic DTO
│       └── tasks/           # Celery app / beat 调度 / 任务定义
│   ├── scripts/             # seed / smoke_test / e2e
│   ├── tests/               # pytest（单元/服务/API/冒烟）
│   └── pyproject.toml
├── frontend/                # 原生单页（index.html + css/ + js/）
├── docker-compose.yml
└── README.md
```

## 8. 提交验收清单（PR 合并前）

- [ ] Ruff / pyright / pre-commit 通过
- [ ] 相关单测 + 冒烟测试通过
- [ ] 权限三级覆盖新接口
- [ ] 审计日志覆盖新变更点
- [ ] 涉及规则/阈值改动时，requirements.md 对应口径已同步
