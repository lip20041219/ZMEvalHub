# 开发状态

> 最后更新：2026-11-11 · 阶段：**P0.0 完成 → P0.1a 完成（开源复用验证）**

## P0.1a 新增（开源组件复用验证与最小集成）

**结论**：采用 **Phoenix 21.0.0** 作为存储/Trace 后端，ZMEvalHub 只自研规则、幂等、指标版本化、对比与 Gate。
详见 [`OPEN_SOURCE_REUSE_DECISION.md`](OPEN_SOURCE_REUSE_DECISION.md)。

| 项 | 证据 |
|---|---|
| Phoenix 数据集 + 不可变版本 | `probe_phoenix.py`：修改后版本 1→2 |
| 实验元数据持久化 | 真实 fixture 往返一致 |
| OpenInference Trace 往返 | `probe_otel_trace.py`：3 span，自定义属性无损 |
| Verdict 四态写入 | `probe_verdict.py`：PASS/FAIL/UNKNOWN/ERROR 均可 |
| 真实 ZMAI fixture 端到端 | `probe_phoenix_import.py`：**9/9 PASS** |
| 真实 ZMWiki fixture 端到端 | 2 cases / 2 runs |
| 适配器 | `src/zmevalhub/importers/phoenix_mapping.py` + 17 条离线测试 |

**许可证提示**：`arize-phoenix`（服务端）是 **Elastic-2.0**，`arize-phoenix-otel`（SDK）是 Apache-2.0。ELv2 禁止作为托管服务转售。

**Phoenix 无法覆盖、必须自研**：幂等导入、内容哈希快照、指标版本化（重复评测会覆盖）、可靠性规则、成对对比、Gate 与退出码。

## 已实现

| 项 | 证据 |
|---|---|
| 数据契约 `schemas/v1.py` | `SourceRunV1` / `CaseV1` / `AttemptV1` / `EventV1` |
| 三种状态分离 | `RunStatus` / `SubjectOutcome` / `Verdict` 为独立枚举类型 |
| 两种 case 类型 | `coding_agent`、`rag_agent` |
| JSON Schema | `docs/schema/v1.json`（由模型生成，测试保证不漂移） |
| 校验 CLI | `zmeval validate`，错误定位到字段路径，非法退出码 1 |
| Fixture | 真实脱敏 2 条 + synthetic 2 条 + 反例 11 条 |
| 测试 | 78 个定向测试通过（61 契约 + 17 Phoenix 映射） |

## 未实现（明确不声称支持）

- 数据库：无 PostgreSQL / SQLAlchemy / Alembic
- 队列：无 Redis / RQ
- **评测引擎：零规则实现**（`ZM-R001`~`ZM-R006` 均未写）
- API：无 FastAPI
- 前端：无 Vue
- 对比 / Gate / 报告：未实现
- 导入器：无自动适配器（fixture 为手工整理）
- Ragas / Promptfoo：未接入
- OTel **Trace 写入能力已验证但未接入导入流程**（仅探测脚本）
- LLM Judge：未实现
- 幂等导入：未实现（Phoenix 无原生支持）
- 指标版本化：未实现（Phoenix 会覆盖）

## Fixture 来源声明

| 文件 | 来源 | 说明 |
|---|---|---|
| `fixtures/zmai/real_masked_coding_agent_pass.json` | **真实**，脱敏 | 派生自 ZMAI `A1_echo_on_20261011_114528` 的 `execution_log.json`（44 步，最终 69 passed）。路径与绝对位置已移除。 |
| `fixtures/zmwiki/real_masked_rag_multihop.json` | **真实**，脱敏 | 派生自 ZMWiki `benchmark/results/phase09_smoke.checkpoint.jsonl`（`mh01` recall 2/2、`mh03` recall 2/3）。 |
| `fixtures/synthetic/*.json` | **合成** | 为覆盖 `UNKNOWN` 与 false-completion 形状而构造，**不是实测成果**，不得对外引用为真实数据。 |
| `fixtures/invalid/*` | 合成反例 | 由合法样本 perturb 生成，用于验证拒绝路径。 |

## P0.0 遗留与阻塞

1. **真实样本的 `snapshot_sha256` / `config_sha256` 为 `null`**：ZMAI/ZMWiki 的历史结果中没有数据集内容哈希。契约允许 null，但在做 A/B 对比前必须补齐，否则不满足 §9.1 的可比性前提。这是 P0.1 必须先解决的问题。
2. **ZMAI 的 `execution_log.json` 没有 Token/成本字段**：`budget.request_log` 中有 `input_tokens`/`output_tokens`，但多数为 null。已按契约置 `null` + `measurement_status=unavailable`，没有伪造成 0。
3. **`trace_complete` 目前靠人工判断**：ZMAI 日志没有完整性标志字段。P0.2 实现 `ZM-R001` 前，需要定义"如何判定日志完整"，否则只能一律返回 `UNKNOWN`。

## 下一步（P0.1b 建议）

架构已由 P0.1a 验证结果收敛。原计划的 11 张表缩减为 **3 张**（其余由 Phoenix 承担）：

1. **SQLite + SQLAlchemy 2 + Alembic**，仅建 3 表：
   - `zm_import_ledger`：幂等键 `(source, source_run_id, source_sha256, importer_version)`
   - `zm_metric_versions`：指标版本历史（Phoenix 会覆盖，必须自存）
   - `zm_gate_decisions`：Gate 结果与策略版本
2. **内容哈希**：实现 `content_sha256` 计算并回填 fixture（解决 P0.0 阻塞 1）。
3. **`zmai-jsonl` / `zmwiki-jsonl` 只读适配器**：把 P0.0 的手工映射固化成代码。
4. **真实导入流程**：`zmeval import --to phoenix`，带幂等保证。

存储选型从 PostgreSQL 调整为 SQLite（P0 单用户本地），PostgreSQL 推迟到并发/部署需求出现。
