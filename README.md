# ZMEvalHub

ZMEvalHub 是面向 Coding Agent 和 RAG 运行记录的**本地评测工具**。它读取已有结果，按可追溯证据执行确定性规则，并对满足可比条件的两次运行做成对比较和质量 Gate。项目当前完成至 **P0.4a**；[开发状态](docs/DEVELOPMENT_STATUS.md)记录了各阶段的验证边界。

## 已实现

- Pydantic `SourceRunV1` 数据契约与校验 CLI。
- ZMAI `execution_log.json`、ZMWiki Benchmark JSONL 的只读适配；Coding Agent 的 ZM-R001～R006 和无需模型调用的 RAG 指标。
- 新运行的 Trace 采集与验证接口、版本化 Phoenix Evaluation 发布接口，以及本地 SQLite 导入账本。Phoenix 是可选的独立服务，不包含在本仓库。
- 离线 `EvalBundle` 成对比较与版本化 Gate；Gate 退出码为 `0=PASS`、`1=FAIL`、`2=BLOCKED`。
- FastAPI 本地产物只读查询：运行列表、详情、规则结果、证据引用、比较与 Gate。它不提供写入或 Phoenix 在线查询。

历史 ZMAI 日志缺独立 Trace 完整性证明，相关规则可能返回 `UNKNOWN`。只有在运行开始时采集了快照、执行条件和来源证明，且通过现有守卫，两次运行才可能形成可信比较。**真实 ZMAI 成对运行及 Gate 验收尚未执行**；仓库中的 synthetic 样本和测试结果不能当作真实 A/B 性能提升。脱敏真实来源 fixture 仅用于适配与回归检查，其来源说明见[开发状态](docs/DEVELOPMENT_STATUS.md)。

## 安装与离线用法

需要 Python 3.11+ 和 [uv](https://docs.astral.sh/uv/)：

```bash
uv sync --extra dev
uv run zmeval validate fixtures/zmai/real_masked_coding_agent_pass.json
uv run zmeval evaluate-zmai <execution_log.json>
uv run zmeval evaluate-zmwiki <checkpoint.jsonl>
uv run zmeval compare <baseline.json> <candidate.json>
uv run zmeval gate <baseline.json> <candidate.json> --policy config/gates/agent_regression_v1.json
```

尖括号是占位说明，请替换为实际路径；在 PowerShell 中不要直接输入尖括号。`compare` 与 `gate` 的 JSON 输入必须是包含运行条件与版本化评测结果的 `EvalBundle`。新 ZMAI 成对运行的手动采集步骤见[验收说明](docs/P03C_ZMAI_PAIR_ACCEPTANCE.md)。

可选 Phoenix 集成需要本地运行的 Phoenix 服务：

```bash
uv sync --extra dev --extra phoenix
```

只读 API 可单独安装并启动：

```bash
uv sync --extra web
uv run --extra web uvicorn zmevalhub.api.app:app --host 127.0.0.1 --port 8000
```

启动后访问 `http://127.0.0.1:8000/docs`。默认只读取仓库 fixture 和被 `.gitignore` 排除的本地 `.zmevalhub/acceptance` 产物。HTTP 端点接收不透明运行 ID，不接收任意文件路径。

## 数据与验证边界

- `fixtures/synthetic/` 是**合成数据**；`real_masked_*` 是**真实来源的脱敏节选**，并非未经修改的上游原始日志。
- `UNKNOWN` 表示证据不足；`ERROR` 表示证据矛盾或评测错误；Gate 的 `BLOCKED` 表示无法可信地放行。它们都不能算作 PASS 或零分。
- 当前没有前端、异步任务、在线批量评测器或已验证的真实 A/B 性能提升。Ragas 与 Promptfoo 尚未集成；现阶段的 RAG 指标是确定性检查，不是语义评分。
- Phoenix 的数据集、实验、Trace 与 Evaluation 能力由 Phoenix 提供；本项目只提供适配、规则、比较、Gate 和只读查询，不把第三方能力声明为原创。

## 许可证与第三方组件

本仓库**自身代码**按 [MIT License](LICENSE) 发布。依赖按各自许可证分发；尤其 `arize-phoenix` 主包为 Elastic License 2.0，不能由本仓库的 MIT 许可覆盖。具体版本与边界见[第三方组件说明](docs/THIRD_PARTY.md)。本仓库不包含 Phoenix、Ragas 或其他依赖的源代码。
