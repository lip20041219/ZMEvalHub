# 开源组件复用决策（P0.1a）

> 验证日期：2026-11-11 · Phoenix `21.0.0` · `arize-phoenix-otel` `0.17.3`
> 结论基于**实际代码执行**，不是文档阅读。每条 PASS/FAIL 都对应 `scripts/` 下可重跑的脚本。

---

## 1. 结论先行

| 问题 | 结论 |
|---|---|
| 数据集 + 版本快照 | ✅ **Phoenix 原生支持且不可变**，直接复用 |
| 实验与运行记录持久化 | ✅ **原生支持**，直接复用 |
| Agent Trace（OTel/OpenInference） | ✅ **原生支持**，自定义属性无损 |
| 读取 / 查询 / 关联原始记录 | ✅ 通过 `phoenix.client.Client` 可查 |
| 稳定标识 | ⚠️ 部分：Phoenix 用 GlobalID，**不是内容哈希** |
| 幂等导入 | ❌ **无原生支持**，需自研 |
| 版本比较 | ⚠️ 有 `dataset_version_id`，但**同一指标重评测会覆盖** |
| 可靠性规则（ZM-R001~） | ❌ **完全没有**，必须自研 |

**一句话**：Phoenix 负责"存 + 看 + 追踪"，ZMEvalHub 负责"判定 + 幂等 + 版本化指标"。

---

## 2. 许可证核实（重要，与总纲 §2.1 有出入）

总纲未记录 Phoenix 的许可证。实测：

| 组件 | 许可证 | 影响 |
|---|---|---|
| `arize-phoenix`（服务器本体） | **Elastic License 2.0 (ELv2)** | 可自用/修改/分发，但**禁止作为托管服务转售**，禁止移除 license key 功能 |
| `arize-phoenix-otel`（客户端 SDK） | **Apache-2.0** | 无限制 |
| `openinference-semantic-conventions` | Apache-2.0 | 无限制 |
| Opik（对照） | **Apache-2.0（含后端）** | 无限制 |

> ELv2 不是 OSI 认证的开源协议。若 ZMEvalHub 未来要提供公开托管演示，或宣称"完全开源栈"，需要重新评估。**仅本地/自托管使用则无影响。**

---

## 3. 实测验证结果

### 3.1 数据集（`probe_phoenix.py`）

| 能力 | 结果 | 证据 |
|---|---|---|
| 创建数据集 | PASS | `id=RGF0YXNldDo2` |
| 读回 examples | PASS | `count=1` |
| input/metadata 往返一致 | PASS | 字段完全相同 |
| 有 `version_id` | PASS | 数据集自带版本 |
| **修改后产生新版本（不可变）** | **PASS** | `before=1 → after=2` |
| examples 必须含 `output` 键 | 约束 | 缺失时 `ValueError: inputs must be non-empty` |

`version_id` 满足总纲 §6.2 的 `DatasetSnapshot` 不可变要求，**无需自研快照表**。

### 3.2 实验（`probe_phoenix.py`）

| 能力 | 结果 | 证据 |
|---|---|---|
| 创建实验 | PASS | `id=RXhwZXJpbWVudDo1` |
| 读回 | PASS | id 一致 |
| metadata 持久化 | PASS | `{'subject':'ZMAI','git_sha':None,'trace_complete':False}` |
| 绑定 `dataset_version_id` | PASS | 实验可钉住历史版本 |
| `repetitions` 多次试验 | PASS | 原生支持 |

**API 陷阱（实测发现，文档未说明）**：`create()` 返回 `id` / `metadata`，而 `get_experiment()` 返回 `experiment_id` / `experiment_metadata`。字段名不一致，直接照抄会拿到 `None`。

### 3.3 Trace（`probe_otel_trace.py`）

| 能力 | 结果 | 证据 |
|---|---|---|
| OpenInference span 写入 | PASS | 3 个 span |
| 父子层级 | PASS | agent → tool 两层 |
| 自定义属性往返 | PASS | `zmeval.case_id`、`exit_code=0`、`zmeval.trace_complete` 全部存活 |
| 按 trace_id 读回 | PASS | `get_spans(project_identifier=..., trace_ids=[...])` |

ZMAI 的 `file_edit → test_run → agent_finish` 可以 1:1 映射为 span 树，**事件级证据不丢失**。

### 3.4 真实 fixture 端到端导入（`probe_phoenix_import.py`）

| 样本 | 结果 |
|---|---|
| ZMAI `real_masked_coding_agent_pass.json` | **9/9 PASS** |
| ZMWiki `real_masked_rag_multihop.json` | 2 cases / 2 runs，元数据完好 |

关键字段全部往返一致：`run_status`、`content_sha256`、`source_run_id`、`subject.model_id`、`case_id`、`kind`。

### 3.5 评测语义（`probe_verdict.py`）

| 能力 | 结果 | 说明 |
|---|---|---|
| `log_evaluation` 写 PASS/FAIL/UNKNOWN/ERROR | **PASS** | 四种 label 全部接受 |
| label 存放位置 | `result.label` | **不是**顶层 `label` 键 |
| 不同指标名累积 | PASS | `ZM-R001` + `ZM-R002` → 2 条 |
| **同一指标重复评测** | **覆盖，不累积** | 4 次写 `ZM-R001` 只剩 1 条 |

最后一条是**架构级限制**：总纲 §6.3 要求 `(attempt_id, metric_id, metric_version)` 唯一、且"规则升级后建立新 Run / evaluation revision"。Phoenix 无法保存同一指标的多版本历史，**这部分必须自研**。

---

## 4. 复用边界

### 直接复用（不自研）

| 能力 | 复用方式 |
|---|---|
| 数据集存储 + 版本快照 | `client.datasets.create_dataset` / `get_dataset_versions` |
| 实验与运行记录持久化 | `client.experiments.create` / `log_run` / `get_experiment` |
| Trace 存储与查询 | OTel span + `client.spans.get_spans` |
| 判定结果存储 | `client.experiments.log_evaluation`（label 承载 Verdict） |
| 可视化 UI | Phoenix 自带 Web（免自研前端） |
| 语义约定 | `openinference-semantic-conventions` 标准属性名 |

### 需要适配（薄层）

| 需求 | 适配方式 |
|---|---|
| 契约 → Phoenix 结构 | `src/zmevalhub/importers/phoenix_mapping.py`（纯函数，已测 17 条） |
| Verdict 语义 | `log_evaluation(label=...)`，但需读 `result.label` |
| 缺失值语义 | 序列化进 `run.output` JSON，保证 `null ≠ 0` |
| 事件序列 | 映射成 span 的 `zmeval.sequence` 属性 |

### 必须自研（Phoenix 确实缺失）

| 缺失能力 | 证据 | 影响 |
|---|---|---|
| **幂等导入** | 无 `idempotency_key` 概念；同名数据集重复创建 | 总纲 §6.3 要求 `source_id + source_sha256 + importer_version` 幂等键 |
| **内容哈希快照** | 只有 `version_id`（内部自增），不是 `content_sha256` | 总纲 §9.1 要求同 `content_sha256` 才可比 |
| **指标版本化** | 同一指标重评测覆盖 | 总纲 §6.3 要求历史分数可追溯 |
| **可靠性规则 ZM-R001~R006** | 完全无此概念 | 项目核心竞争力 |
| **成对对比 + 可比性判定** | 无 `comparable / reasons` 语义 | 总纲 §9.2 |
| **质量 Gate + 退出码** | 无 policy 引擎 | 总纲 §9.3 CI 门禁 |
| **UNKNOWN ≠ FAIL 的强制** | label 是自由字符串，无约束 | 语义靠 ZMEvalHub 自己守 |

---

## 5. 为什么选 Phoenix 而不是 Opik

Opik 的许可证更宽松（**含后端全 Apache-2.0**），能力集合也重叠。但本轮已完成 Phoenix 的**真实验证**，切换到 Opik 需要重复全部验证成本（约 4 个探测脚本），而当前需求 Phoenix 已全部覆盖。

**决定：P0.1 采用 Phoenix。** Opik 作为备选记录在案，触发切换的条件是：

1. 需要以托管服务形式对外提供（ELv2 不允许），或
2. 需要对项目整体宣称 OSI 认证开源栈。

在此之前不并行开发两套集成。

---

## 6. P0.1 最终架构

```text
┌─────────────────────────────────────────────────────┐
│ ZMEvalHub（自研，薄）                                │
│  ├── 可靠性规则 ZM-R001~R006                        │
│  ├── 幂等键 (source_id + source_sha256 + importer)  │
│  ├── 内容哈希 content_sha256                        │
│  ├── 指标版本化 metric_version                      │
│  ├── 成对对比 + 可比性判定                          │
│  └── 质量 Gate + CLI 退出码                         │
└──────────────┬──────────────────────────────────────┘
               │ phoenix_mapping.py（已实现）
┌──────────────▼──────────────────────────────────────┐
│ Phoenix（复用，不自研）                              │
│  ├── 数据集 + 版本快照（不可变）                     │
│  ├── 实验 / 运行 / 评测结果持久化                    │
│  ├── Trace 存储 + 查询                              │
│  └── Web UI                                         │
└─────────────────────────────────────────────────────┘
       SQLite/PostgreSQL（仅存 Phoenix 缺失的元数据）
```

### P0.1 是否还需要 SQLAlchemy + Alembic + PostgreSQL？

**答案：需要，但范围大幅缩小。**

原计划 11 张表 → 实际只需 **3 张**，因为以下已被 Phoenix 覆盖：

| 原计划表 | 结论 |
|---|---|
| `zm_datasets` / `zm_dataset_snapshots` / `zm_snapshot_cases` | ❌ 删除，用 Phoenix 数据集 + `version_id` |
| `zm_eval_runs` / `zm_eval_attempts` | ❌ 删除，用 Phoenix 实验 + run |
| `zm_trace_events` | ❌ 删除，用 OTel span |
| `zm_score_records` | ⚠️ 部分保留（需版本化，Phoenix 会覆盖） |
| **`zm_import_ledger`**（新增） | ✅ 幂等键 + `content_sha256` |
| **`zm_metric_versions`**（新增） | ✅ 指标版本历史 |
| **`zm_gate_decisions`**（保留） | ✅ Gate 结果与策略版本 |

**存储选型调整**：P0.1 先用 **SQLite**（零部署、单用户），PostgreSQL 推迟到需要并发或部署时。理由：剩余 3 张表都是低频元数据，SQLite 足够；总纲允许"测试可用 SQLite"，而 P0 场景正是单用户本地。

---

## 7. 复现方式

```bash
# 1. 安装（核心不需要 Phoenix）
uv sync --extra dev

# 2. 启动本地 Phoenix（后台）
uv sync --extra dev --extra phoenix
PHOENIX_WORKING_DIR=/tmp/phx_data PHOENIX_PORT=6006 \
  uv run python -m phoenix.server.main serve
# 等待日志出现 "Phoenix is up and running"，再 curl /healthz 得到 200

# 3. 运行验证（需要服务）
export PHOENIX_COLLECTOR_ENDPOINT=http://127.0.0.1:6006
uv run python scripts/probe_phoenix.py        # 数据集 / 实验 / 版本
uv run python scripts/probe_otel_trace.py     # Trace 往返
uv run python scripts/probe_verdict.py        # Verdict 语义（含覆盖问题）
uv run python scripts/probe_phoenix_import.py # 真实 fixture 端到端

# 4. 离线测试（不需要服务）
uv run pytest -q
```

---

## 8. 未验证 / 已知限制

1. **未测并发写入**：单 Worker 场景，未做压力测试。
2. **未测大文件**：只用 1~2 case 的 fixture，未验证 50 case 数据集的行为。
3. **未测损坏数据**：本轮只导入合法 fixture，非法数据在 P0.0 的 schema 层被拦。
4. **`version_id` 语义未深究**：只确认"修改会产生新版本"，未确认版本是否可删除、是否永久保留。
5. **Opik 未做代码级验证**：仅核实许可证与 README 声明，未运行。
