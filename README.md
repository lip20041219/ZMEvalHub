# ZMEvalHub

**AI Agent 可靠性评测中台** — 把"任务成功"和"Agent 自称成功"分开。

> 当前状态：**P0.0 + P0.1a（数据契约 + 开源组件复用验证）**。这是一个可运行、可测试的起点，**不是**可用的评测平台。
> 完整的规划与验收标准见 [`docs/00_ENGINEERING_BLUEPRINT.md`](docs/00_ENGINEERING_BLUEPRINT.md)。

---

## 项目要解决什么

Agent 开发者经常只能拿到一个"任务成功/失败"的结果，却回答不了：

1. Agent 说它完成了，**凭什么**？有没有外部测试或工具结果支撑？
2. 执行过程中是否出现未验证修改、重复读取、无效重试、超预算？
3. 改了一处代码或 Prompt 后，**哪些用例改善、哪些退化**？

ZMEvalHub 不重跑被测 Agent，也不自研评测算法。它**消费**已有执行结果（ZMAI / ZMWiki / Promptfoo / OTel），
用确定性规则产出可追溯的证据、成对版本差异和 CI 质量闸门。

### 三种"成功"必须分开

这是整个项目的立身之本，也是代码里被强制约束的部分：

| 概念 | 回答的问题 | 陷阱 |
|---|---|---|
| `run_status` | 平台评测流程跑完了吗？ | `SUCCEEDED` **不等于** Agent 成功 |
| `subject_outcome` | 被测系统**自己声称**了什么？ | `COMPLETED` 可能从未验证过任何东西 |
| `verdict` | 规则根据证据判了什么？ | 这才是真值 |

两个不能被混淆的判定：

- **`UNKNOWN` ≠ `FAIL`** — 证据不足，不是失败。
- **`ERROR` ≠ `FAIL`** — 评测器自己崩了，不是被测系统失败。

---

## 技术架构

P0 是 **Python 模块化单体 + 独立异步 Worker**（本轮只实现数据契约层）：

```text
Vue3 Console │ zmeval CLI │ REST / OpenAPI
                     ↓
        FastAPI (zmevalhub)         ← P0.1+
   Project/Dataset/Snapshot/Run
   Import Adapters/Rules/Gate
              ↓            ↓
        PostgreSQL    Redis + RQ      ← P0.1 / P0.2
              ↓
        RQ Worker (rules)           ← P0.2
```

| 层 | 选型 | 本轮状态 |
|---|---|---|
| 数据契约 | **Pydantic v2** | ✅ 已实现 |
| CLI | argparse | ✅ `zmeval validate` / `zmeval schema` |
| 测试 | pytest | ✅ 已实现 |
| **存储 / Trace** | **Phoenix 21 + OpenInference** | ✅ 已验证（P0.1a） |
| API | FastAPI | ⬜ P0.1b |
| 存储 | PostgreSQL + SQLAlchemy 2 + Alembic | ⬜ P0.1 |
| 队列 | Redis + RQ | ⬜ P0.2 |
| 前端 | Vue 3 + TS + Vite + Element Plus | ⬜ P0.3 |
| 指标 | Ragas（optional extra） | ⬜ P1 |

---

## 安装

需要 Python 3.11+ 和 [uv](https://docs.astral.sh/uv/)。

```bash
git clone <repo-url> ZMEvalHub
cd ZMEvalHub

uv sync --extra dev              # 核心：契约 + CLI + 测试
uv sync --extra dev --extra phoenix   # 加上 Phoenix 集成
```

---

## 用法

### 校验一条评测数据

```bash
uv run zmeval validate fixtures/zmai/synthetic_coding_agent_pass.json
```

合法数据：

```text
VALID  source=zmai  cases=1  attempts=1  run_status=SUCCEEDED
  content_sha256=3f2a...
```

非法数据会指出**具体字段路径**，并以退出码 **1** 结束：

```text
INVALID  2 error(s):
  cases[0].attempts[0].events: duplicate event sequence numbers: [2]
  cases[0].attempts[0].input_tokens: Input should be a valid integer
```

### 导出 JSON Schema

```bash
uv run zmeval schema --out docs/schema/v1.json
```

---

## 数据契约概览

`schema_version = 1`，四个核心模型（`src/zmevalhub/schemas/v1.py`）：

```text
SourceRunV1
├── schema_version / source / source_run_id / importer_version
├── subject   { name, git_sha?, model_id?, config_sha256? }
├── dataset   { name, snapshot_sha256? }
├── run_status            ← 平台执行状态
└── cases: CaseV1[]
        ├── case_id / kind (coding_agent | rag_agent)
        ├── input / expected / tags
        └── attempts: AttemptV1[]
                ├── attempt_index / subject_outcome  ← 被测方声称
                ├── trace_complete                   ← 决定能否判 FAIL
                ├── measurement_status               ← 缺失值不许当 0
                └── events: EventV1[]
                        └── sequence（单调、去重）/ event_type / status / exit_code
```

契约里几条**用代码强制**的规则：

- `extra="forbid"` — 拼错的字段名直接报错，不被静默吞掉。
- 事件 `sequence` 必须唯一且升序 — 顺序是定位证据的基础。
- `measurement_status="measured"` 必须同时有 token 数 — 防止"没测到"被当成"测到 0"。
- 未测到的数值一律 `null`，**绝不允许写 0**。
- `trace_complete=False` 时，需要完整事件窗口的规则只能返回 `UNKNOWN`。

---

## 运行测试

```bash
uv run pytest -q                    # 全部定向测试（78 个，全部离线）
uv run pytest tests/test_schema.py -q
uv run pytest tests/test_phoenix_mapping.py -q
uv run ruff check src tests scripts
```

### 验证 Phoenix 集成（需要本地服务）

```bash
uv sync --extra dev --extra phoenix
PHOENIX_WORKING_DIR=/tmp/phx_data PHOENIX_PORT=6006 \
  uv run python -m phoenix.server.main serve

# 另开终端
export PHOENIX_COLLECTOR_ENDPOINT=http://127.0.0.1:6006
uv run python scripts/probe_phoenix.py
uv run python scripts/probe_otel_trace.py
uv run python scripts/probe_verdict.py
uv run python scripts/probe_phoenix_import.py
```

详细结论见 [`docs/OPEN_SOURCE_REUSE_DECISION.md`](docs/OPEN_SOURCE_REUSE_DECISION.md)。

---

## 当前进度与**未实现**功能

### ✅ 已实现（P0.0）

- 工程骨架：`pyproject.toml`（uv 管理）、README、`.gitignore`、`.env.example`
- Pydantic v2 数据契约：`SourceRunV1` / `CaseV1` / `AttemptV1` / `EventV1`
- 三种状态枚举严格分离：`RunStatus` / `SubjectOutcome` / `Verdict`
- Coding Agent 与 RAG Agent 两种 case 类型
- JSON Schema 生成（与 Pydantic 模型有测试保证一致）
- `zmeval validate` CLI，错误定位到字段路径，非法数据退出码非零
- fixture：真实脱敏样本 + 明确标注的 synthetic 样本 + 反例

### ✅ 已实现（P0.1a — 开源复用验证）

- Phoenix 21.0.0 集成验证：数据集 / 不可变版本 / 实验 / 运行记录
- OpenInference Trace 往返：自定义属性无损
- Verdict 四态（PASS/FAIL/UNKNOWN/ERROR）写入验证
- 真实 ZMAI + ZMWiki fixture 端到端导入（9/9 PASS）
- 映射适配器 `importers/phoenix_mapping.py`（17 条离线测试）
- 结论：**复用 Phoenix 存储与追踪，自研规则/幂等/版本化/对比/Gate**

### ⬜ 未实现（明确不声称支持）

- **本地元数据库**：无 SQLite / SQLAlchemy / Alembic（P0.1b 只建 3 张表）
- **异步任务**：无 Redis、无 RQ Worker
- **评测引擎**：**没有任何规则评分**（`ZM-R001`~`ZM-R006` 均未实现）
- **API**：无 FastAPI、无 REST 接口
- **前端**：无 Vue、无任何页面
- **对比与 Gate**：无成对比较、无质量门禁、无退出码语义实现
- **上游自动导入**：无 `zmai-jsonl` / `zmwiki-jsonl` 适配器，fixture 仍为**手工**整理
- **幂等导入**：未实现（Phoenix 无原生支持，必须自研）
- **指标版本化**：未实现（Phoenix 重复评测会覆盖）
- **Ragas / Promptfoo**：完全未接入
- **Trace 自动采集**：能力已验证，但未接入导入流程
- **LLM Judge**：未实现，且 P0 要求模型调用次数为 0

> 项目名称、命令和字段描述的是**设计目标**，不代表已经具备该能力。

---

## 目录结构

```text
中台/
├── docs/
│   ├── 00_ENGINEERING_BLUEPRINT.md   # 工程总纲（验收依据）
│   └── DEVELOPMENT_STATUS.md         # 进度与阻塞
├── fixtures/                          # 脱敏样本，全部标注来源
├── src/zmevalhub/
│   ├── schemas/v1.py                  # ★ 数据契约
│   ├── validation.py                  # 校验入口
│   └── cli/main.py                    # zmeval CLI
└── tests/
```

---

## 许可

MIT。使用任何第三方代码/dependency 前需复核许可证，见 `docs/THIRD_PARTY.md`（待建）。
