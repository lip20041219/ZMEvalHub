# 开发状态

> 最后更新：2026-11-12 · 阶段：**P0.4a Web 工作台只读后端 API**

## P0.4a：Web 工作台只读后端 API

- 新增可选 `web` 依赖与 FastAPI 应用 `zmevalhub.api.app:app`。使用仓库内 ZMAI、ZMWiki、synthetic fixture 和 `.zmevalhub/acceptance` 作为默认只读产物目录；只接受服务端配置的目录与固定 Gate 策略，HTTP 仅用不透明运行 ID，不接收文件路径。读取时限制目录归属、符号链接与文件大小，并用 Pydantic 校验 `SourceRunV1` / `EvalBundle`；新采集产物继续由现有 `load_run_capture` 核验，原始 ZMWiki checkpoint 复用现有适配器。
- 接口：`GET /api/v1/runs`（分页列表）、`/api/v1/runs/{id}`（详情）、`/api/v1/runs/{id}/evaluations`（规则/指标）、`/api/v1/runs/{id}/evidence?case_id=...&attempt_index=...`（规范化事件和原始来源引用）、`/api/v1/comparisons?baseline_id=...&candidate_id=...`、`/api/v1/gates?baseline_id=...&candidate_id=...`；对比与 Gate 支持重复传入 `allow_difference`，Gate 可指定已配置的 `policy_id`。另有 `/healthz`、`/readyz`、`/docs`、`/openapi.json`。成功响应统一为 `data/meta/request_id`，错误响应为 `error/request_id`；`meta` 和列表标明真实、脱敏、synthetic、UNKNOWN、BLOCKED。历史产物无 `EvalBundle` 和运行条件时，比较不可比、Gate 为 BLOCKED，不补造可信改善。
- 启动：`uv run --extra web uvicorn zmevalhub.api.app:app --host 127.0.0.1 --port 8000`。Phoenix 仍为独立实验和 Trace 平台，API 不复制其存储。P0.4b 前端通过同源代理请求 `/api/v1`，保存不透明运行 ID；以 `meta.status` / `evaluation_status` 显示 UNKNOWN/BLOCKED，不把空值当 0。当前仅本机只读服务，跨域访问与身份认证需在部署边界另行配置。
- 定向测试：API **4 passed**，现有 Compare/Gate/ZMWiki 兼容路径 **3 passed**；Ruff 与 `git diff --check` 通过。未运行全量测试、Benchmark、E2E、在线 Phoenix 或付费模型调用。

**遗留**：真实成对 Agent 采集仍需用户手动完成；历史 fixture 缺可信执行条件，无法生成可信 Gate PASS。当前 API 不提供写入、数据库或 Phoenix 在线查询。

## P0.3d：ZMWiki 原始数据适配与确定性 RAG 评测

- 新增只读 `zmwiki_benchmark.py`，支持原始平铺 Benchmark checkpoint JSONL，以及需显式 `--arm rag|agent` 的嵌套对比 JSONL。逐行映射为 `SourceRunV1`，保留问题、回答、引用证据 ID、已访问页面、黄金证据 ID、上游 `answer_correct`、步骤摘要和原始文件行号引用。可选 `--dataset` 加入参考答案；仅当 checkpoint 的完整数据集 SHA-256 与提供文件一致时，才把该文件认作运行时快照。历史日志不补造 Trace 完整性证明。
- 新增 `evidence_recall@1`（黄金 ID 与引用 ID 的确定性集合比）、`evidence_missing@1`（缺失黄金 ID 判定）和 `answer_match@1`。答案匹配复用 ZMWiki 的 `answer_correct` 断言，明确标记 `upstream_zmwiki_assertion`，不自研语义或关键词评分；无可绑定的参考答案时为 UNKNOWN。黄金证据缺失、检索字段缺失为 UNKNOWN；标注冲突或上游召回数与 ID 集合矛盾为 ERROR。结果含版本、分子/分母、方向、来源、评测器哈希与原始引用。Ragas 仅用于后续确实需要其语义指标时，本阶段不增加依赖或模型调用。
- CLI：`zmeval evaluate-zmwiki <checkpoint.jsonl> [--dataset dataset.json] [--arm agent|rag] [--output normalized.json]`。可选 `--publish-run-map case_run_ids.json` 将每个 case 对应到既有 Phoenix experiment run ID，复用现有版本化 Evaluation 接口；本轮只用 fake client 验证写入 payload，未连在线 Phoenix。
- 新增从真实 `phase09_smoke.checkpoint.jsonl` 派生的两行**脱敏** fixture。对本机真实原始文件只读核对：3 cases / 9 metrics，证据召回为 `2/2`、`2/2`、`2/3`；原始文件没有参考答案，答案匹配保持 UNKNOWN。当前 `multihop_wiki.json` 与旧 checkpoint 的 `mh03` 黄金证据不一致，且较新嵌套 checkpoint 声明的 dataset SHA-256 与当前文件不符，均不能冒充历史参考答案。
- 本轮定向测试：新适配器 + 既有 ZMAI 适配与 Phoenix 映射 **25 passed（0.17 秒）**；与 Phoenix 导入、Compare/Gate 兼容路径 **22 passed（0.69 秒）**；最后的评分守卫调整后复跑本阶段测试 **4 passed（0.76 秒）**。Ruff 与 `git diff --check` 通过；未运行全量测试、Benchmark、E2E、在线 Phoenix 或真实模型调用。

**遗留**：历史平铺 checkpoint 缺可证明同版本的参考答案数据集，故无法给出独立的答案正确率；要计算语义忠实度等指标需后续按锁定版本接入 Ragas 并明确模型成本。本轮未改 ZMWiki 源码。

## P0.3c：真实 Agent 成对运行接入与 Gate 验收准备

- 新增 `RunSpec` / `RunCapture`：在新运行开始、ZMAI 日志出现之前，把用例快照、数据集名、被测版本、模型/Prompt 和执行条件写入独立采集目录；首个 `run_start` 事件绑定元数据与快照哈希。只读 `watch-zmai` 观察新产生的 `execution_log.json`，沿用现有 ZMAI 适配器和 `TraceCapture`，保存规范化事件、原始步骤引用/指纹、最终原始日志及封存证明。既有日志拒绝重放。
- `pair-captures` 验证开始元数据、快照、事件连续性、来源身份/步骤指纹、最终日志及终止证明，再复用 R001～R006 生成标准 `EvalBundle`，调用现有 Compare 与 Gate；可用 `--bundle-dir` 写出两侧 JSON。CI 退出码仍为 PASS=0、FAIL=1、BLOCKED=2。来源或证据缺失、快照/条件不一致时拒绝可信比较。无受控 seed 可诚实记录 `null`，比较和 Gate 必须 BLOCKED。
- 手动真实 ZMAI 成对验收命令见 [`P03C_ZMAI_PAIR_ACCEPTANCE.md`](P03C_ZMAI_PAIR_ACCEPTANCE.md)。本轮未启动真实 Agent 或付费模型；采集者仍须独立于被测 Agent，文件哈希只证明采集产物一致，不能单独证明 ZMAI 内部没有漏记步骤或声明的执行条件真实。
- 合成 ZMAI 持久化日志与原有 Compare/Gate 定向测试 **14 passed（0.72 秒）**，覆盖标准 EvalBundle、逐规则证据、Gate PASS/FAIL/BLOCKED、原始日志篡改、历史重放、来源缺失、工作区 glob 发现及未知 seed；Ruff 与 `git diff --check` 通过。未运行全量测试、Benchmark、E2E 或付费模型调用。

**遗留**：真实成对运行和 Gate 验收待用户按文档手动执行；若当前 ZMAI 后端不提供受控 seed，真实对比会按设计 BLOCKED，不能宣称可信改善。

## P0.3b：质量 Gate 与 CI 退出码

- 新增 `GatePolicy` / `GateDecision`，通过 `zmeval gate baseline.json candidate.json --policy config/gates/agent_regression_v1.json` 离线运行。策略使用严格的 JSON 契约，含 schema、名称、版本和固定的成对比较语义；未知字段或非法版本拒绝。可重复传入 `--allow-difference model_id`、`--allow-difference prompt_version` 等沿用 P0.3a 的显式差异声明。
- Gate 先复用 P0.3a 可比性与证据守卫。不可比返回 BLOCKED；可比时任一明确 PASS→FAIL 返回 FAIL，即使另有改善或不确定项也不会抵消；没有明确退化但有影响判定的 UNKNOWN、ERROR 或适用性变化时返回 BLOCKED。两侧均 SKIPPED 的规则为不适用，不影响其余规则；全部不适用也 BLOCKED。结果包含策略版本、原因、关键 `findings`，以及所有已检查的 `checked_changes`（case、规则版本、两侧原始证据），PASS 也可追溯。
- CI 退出码固定为 `0=PASS`、`1=FAIL`、`2=BLOCKED`。策略或输入 JSON 无效时输出 BLOCKED JSON 并退出 2。此阶段只支持固定的无退化策略，不包含阈值、WARN、数据库策略表、前端或报告系统。
- Gate + P0.3a 对比定向测试 **9 passed（0.36 秒）**，覆盖通过、改善与退化并存、UNKNOWN/ERROR、快照缺失、全部不适用、非法策略、CLI 退出码及差异声明；Ruff 与 `git diff --check` 通过。未执行全量测试、Benchmark、E2E 或付费模型调用。

**遗留**：目前缺可证明快照与运行条件的真实成对样本，未对真实 A/B 运行 Gate；上游提供的快照哈希与条件仍需可信采集。

## P0.3a：成对 A/B 对比与可比性判定

- 新增纯离线 `EvalBundle` 对比：两侧分别包含 `SourceRunV1`、六规则的版本化 `RuleResult` 和显式 `ExecutionConditions`。`zmeval compare baseline.json candidate.json` 按 case ID、attempt index、规则 ID 与版本配对，输出逐项 verdict 变化、原因及两侧原始证据引用；输出顺序固定。
- 可比性守卫要求同名且均带相同数据集快照哈希、相同用例集合与内容、完整的逐尝试六规则结果、相同规则版本、相同种子/重复次数/工具环境/并发/超时/评测器配置。模型、Prompt、代码或配置版本差异须逐项用 `--allow-difference` 声明；未声明即拒绝。结果引用必须指向对应尝试的输入事件或尝试引用。不可比时列出原因、退出码 1，不给变化或改善结论。
- PASS↔FAIL 才计为改善或退步；涉及 UNKNOWN、ERROR、SKIPPED 的配对标记为 `indeterminate`，不计零分，也不产生整体改善结论。`observed_balance` 只是已匹配规则判定的方向，不代表统计显著性或真实性能增益。输入中的快照哈希与执行条件仍依赖上游可信记录；历史 fixture 缺原始快照证明，不能据此宣称可信 A/B。
- 合成样本定向测试 **5 passed（0.14 秒）**，另复跑原有 Trace CLI 定向测试 **1 passed（0.11 秒）**；覆盖可比变化、UNKNOWN 保留、快照/用例/条件/规则版本不一致、未声明的模型与 Prompt 差异、证据丢失及 CLI。Ruff 与 `git diff --check` 通过。未运行全量测试、Benchmark、E2E、在线 Phoenix 或付费模型调用。

**遗留**：尚无真实且条件齐全的成对运行样本；本阶段不提供实验管理、统计检验、Gate、前端或报告。

## P0.2d：可信 Trace 采集与评测发布

- `TraceCapture` 在新运行的事件到达时顺序写入规范化 `EventV1` JSONL；终止事件到达后封存 SHA-256、来源标识、事件数和终止状态。`load_capture` 复核字节、序号、来源引用与终止记录；缺终止事件、序号跳跃或测试状态/退出码矛盾不允许封存或评测。
- `zmeval evaluate-trace <events.jsonl> <proof.json> --case-id <id>` 从封存产物离线执行 R001～R006。可选 `--publish-run-id <Phoenix run id>` 复用现有 Phoenix SDK 发布六条版本化 Evaluation。2026-11-12 在本机 Phoenix 21.0.0 上，将 synthetic Trace 的六条 `ZM-R001@1`～`ZM-R006@1` 发布至 experiment run `RXhwZXJpbWVudFJ1bjox`，SDK 读回确认标签为 PASS/PASS/PASS/SKIPPED/PASS/PASS，原因与 `evidence_refs` 均保存。
- PowerShell 手动发布时，空的 `--publish-run-id` 会明确报配置错误，不再静默退回离线运行；实际 Phoenix URL 使用 `http://`，不能写作 `http\://`。
- 新采集的 synthetic PASS/FAIL/UNKNOWN 与篡改拒绝路径已做定向验证；仓库中的真实历史 ZMAI 脱敏 fixture 仍无独立证明，不据此判 PASS。采集者必须在被测 Agent 控制范围之外，且证明只保证所记录字节的一致性，不能证明源头没有漏采或伪造事件。
- 定向测试 **28 passed（0.20 秒）**，最后的采集守卫微调后复跑采集测试 **4 passed（0.11 秒）**；Ruff 检查通过。Phoenix 在线发布与读回已验证（仅 synthetic 样本）；未运行全量测试、Benchmark、E2E 或付费模型调用。手动发布前先取得真实的 Phoenix **experiment run ID**；在 PowerShell 中以 `Read-Host` 读入变量，并将实际 JSONL、proof 路径作为引号包住的参数传入 `zmeval evaluate-trace`。文档中的占位说明不能作为 PowerShell 参数直接执行。

## P0.2c：规则完善与真实案例核查

- 修正 ZMAI 命令范围提取：仅从 pytest 调用片段识别目标测试，忽略后续 `& type tests/...`。同时将 `edit` 等工具结果正确映射为文件修改事件，并保留工具签名与输出摘要供重复调用规则使用。
- 复用 `RuleResult`、`TraceSource` 与 Phoenix Evaluation 发布接口，新增 `evaluate_all_agent_rules` 离线执行 R001～R006。R003 检查验证后影响范围明确的修改；R004 检查三次相同工具与输出且无确认进展；R005 检查显式预算或循环守卫终止；R006 检查有退出码的外部测试，按范围取最近结果。缺完整性、范围或退出码时保守判 UNKNOWN，证据冲突判 ERROR。
- 真实日志 `A1_echo_on_20261011_114528/agent_16668`：step 35 是全量 pytest 后接文件读取，step 36 为 66 passed/3 failed；step 41 再次全量 pytest，step 42 为 69 passed 但工具结果没有明确退出码，step 43 的 `tests_passed` 摘要记录 `exit=0`。修正后 step 36/42/43 均归为 regression；R002 从错误的 FAIL 改为 UNKNOWN，因历史 Trace 无独立完整性证明且 step 42 的退出码缺失。六规则在该历史日志均为 UNKNOWN，不对外宣称已证明完全成功。
- 定向测试 **24 passed（0.16 秒）**，覆盖 PASS/FAIL/UNKNOWN/ERROR/SKIPPED、真实命令范围、规则确定性与来源引用；Ruff 与 `git diff --check` 通过。未执行全量测试、Benchmark、E2E、在线 Phoenix 或付费模型调用。

**遗留**：真实历史日志缺独立 Trace 完整性证明；step 42 的测试摘要不能代替明确的进程退出码。R003 的编辑影响范围若未提供，只能判 UNKNOWN。

## P0.2b：真实 ZMAI 日志适配与证据验证

- 新增只读适配器 `src/zmevalhub/importers/zmai_execution_log.py`，将外部 `.state/execution_log.json` 的每个 source step 映射为 `EventV1`，保留原始 `step_id`、来源 URI、顺序、编辑事件、测试范围/退出码与 `agent_finalize` 状态，并生成合法 `SourceRunV1`。
- CLI：`zmeval evaluate-zmai <execution_log.json> [--output normalized.json]`；离线调用既有 ZM-R001/R002，结果含 source step evidence refs。`--output` 仅写入 ZMEvalHub 指定路径，不修改 ZMAI 日志。
- 历史 ZMAI 日志没有独立 Trace 完整性证明。适配器将 `trace_complete=false`；文件 SHA-256 仅作导入字节指纹，不冒充上游完整性证明。因此完整窗口依赖项返回 UNKNOWN，明确连续的失败测试仍可由 R002 判 FAIL。
- 若上游提供规范化 EventV1 JSONL 及产出时记录的 SHA-256，可用 `--trace-proof-jsonl` 与 `--trace-proof-sha256` 交给现有完整性守卫；哈希或事件冲突返回 ERROR。不生成或回填上游证明。
- 定向离线验证：规则引擎 + 适配器 **19 passed（0.08 秒）**，Ruff 检查通过；真实日志 44 steps 经 CLI 转换并通过 `SourceRunV1` 校验，结果 R001=UNKNOWN、R002=FAIL（step 36 的 target 测试失败未被其他范围通过覆盖）。未改动 ZMAI 文件。未执行全量测试、Benchmark、E2E、Phoenix 在线评测或付费模型调用。

**遗留边界**：目前发现的真实 ZMAI 日志均未携带独立来源证明，故不会据它们断言 Trace 完整；原始工具输出/错误正文不复制进规范化事件，需通过 `source_ref` 回查原文件。

## P0.2a：Trace 完整性与 ZM-R001 / ZM-R002

- `rules/agent_reliability.py` 离线评测现有 `CaseV1` / `AttemptV1`。每项结果包含规则 ID、版本 `1`、PASS / FAIL / UNKNOWN / ERROR / SKIPPED、原因和事件引用；相同输入及版本返回相同结果。规则本身无网络调用。
- 完整性不能只信 `trace_complete=true`：还要求独立来源引用、上游捕获的规范化事件 JSONL 与已记录 SHA-256 相符、事件与契约一致、序号从 1 连续、最后是成功终止事件。缺少来源证明或事件窗口不完整为 UNKNOWN；哈希、内容或状态矛盾为 ERROR。来源哈希必须由上游在日志产出时独立记录，不能在评测时由 `attempt.events` 自行生成并冒充来源证明；该校验只证明所提供日志的内部完整性，仍依赖上游采集可信。
- R001 仅适用于 coding agent 完成声明且有成功修改：完整窗口内无修改后合格验证为 FAIL；有明确范围和退出码的修改后验证为 PASS；测试范围或退出码缺失、完整性不足为 UNKNOWN。无修改且完整时 SKIPPED。
- R002 按验证范围追踪最近结果：失败的目标测试不会被另一范围的通过覆盖；失败测试至完成事件间序号连续时，即便较早 Trace 不完整也保留 FAIL。较新的同范围成功验证可解除该失败；未知测试或缺失完整证据不判 PASS。
- 复用 Phoenix 版本化 Evaluation 写入接口，写入 verdict、reason 和 evidence_refs；未引入新表。离线定向测试 **16 passed（0.64 秒）**，覆盖正常/错误完成、缺验证、日志不完整、范围冲突、来源哈希、历史 fixture 与 Phoenix payload。未执行全量测试、在线规则评测或 Benchmark。

**边界**：历史 fixture 没有独立原始 Trace 证明；即使其中 `trace_complete=true`，R001 也不能据此断言“没有验证”。P0.2a 不包含原始 ZMAI JSONL 自动适配器、R003～R006、Gate 或前端。

## P0.1b：幂等导入与指标版本

- Git 首次本地提交已在 P0.1a 后完成：`719bddcf8852d524c72d47f2c888602d41ce2eac`；本轮未重复初始化，未 Push。
- SQLite + SQLAlchemy 只建 `zm_import_ledger` 一表。唯一键为 `(source, source_run_id, importer_version)`；同键内容变化报冲突。导入前保存外部写入阶段，断点重试须显式 `--resume` 并先读 Phoenix；远端写入结果不明确且无法读回时停止，**不声称 SQLite 与 Phoenix 存在跨系统原子事务**。
- 计算规范化 case 内容的 `dataset_content_sha256` 并关联 Phoenix `dataset_version_id`；原始 fixture 的 `snapshot_sha256=null` 保持原样，不把计算值冒充历史来源的哈希。
- Phoenix SDK 对同一 `(experiment_run_id, name)` 执行 upsert；不同 name 可以并存。采用 `metric_id@metric_version` 独立命名及读取，不建指标表。`scripts/probe_verdict.py` 的版本名读写断言由用户在真实 Phoenix 上执行，退出码为 0。
- 新增 `zmeval import <SourceRunV1.json> --to phoenix [--ledger PATH] [--resume]`。本阶段只接受已经符合 v1 契约的 JSON；原始 `zmai-jsonl` / `zmwiki-jsonl` 适配器未实现。
- `COMPLETE` 账本重复导入前会只读核对 Phoenix 数据集、版本、实验、内容哈希和 run；远端缺失或不一致时拒绝报告成功，不创建替代资源。`scripts/probe_phoenix_idempotent.py` 使用独立合成数据和新 SQLite 账本，检查首次、重复、同源冲突、远端写入后丢失响应的恢复，以及远端状态不明时拒绝成功；逐项打印 PASS/FAIL。
- 定向离线验证：`tests/test_phoenix_import.py` **9 passed（1.21 秒）**，探针及导入器语法检查通过。未重跑原有 78 项。用户手动执行 Phoenix 在线幂等导入探针：首次、重复、同源冲突、中断恢复、未知远端状态 **5 项全部 PASS**，退出码 0；独立账本位于 `.zmevalhub/acceptance/ee5cb85b346247f8849b935bc7399b55/imports.sqlite`。

**P0.1b 验收状态**：指标版本化和幂等导入的 Phoenix 在线探针均已通过，达到本阶段验收标准。SQLite 与 Phoenix 没有跨系统原子事务；异常状态由 `--resume` 读回或明确拒绝处理。

**P0.2 启动前待定**：明确 ZMAI `trace_complete` 的可验证来源，或让依赖完整日志的规则返回 UNKNOWN。原始 `snapshot_sha256` 缺失的历史数据不可直接用于公平 A/B 对比。

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

**Phoenix 无法覆盖、必须自研**：幂等导入、内容哈希、可靠性规则、成对对比、Gate 与退出码。指标版本通过不同 Evaluation 名称复用 Phoenix。

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

- 数据库：已用 SQLite + SQLAlchemy 建最小导入账本；无 PostgreSQL / Alembic
- 队列：无 Redis / RQ
- 评测规则：`ZM-R001`～`ZM-R006` 已实现离线执行与可选 Phoenix Evaluation 发布；没有在线批量运行器
- API：P0.4a 已提供 FastAPI 本地只读查询
- 前端：无 Vue
- 对比 / Gate：已实现 P0.3a 纯离线成对比较和 P0.3b 固定策略 Gate；报告未实现
- 导入器：已支持 ZMAI `execution_log.json` 与 ZMWiki Benchmark checkpoint JSONL 只读适配
- Ragas / Promptfoo：未接入
- OTel **Trace 写入能力已验证但未接入导入流程**（仅探测脚本）
- LLM Judge：未实现
- Phoenix 在线幂等与版本名往返：用户已在真实服务上验证通过
- ZMWiki 其他未核对的原始结果格式：未实现；当前支持平铺/嵌套 Benchmark checkpoint JSONL

## Fixture 来源声明

| 文件 | 来源 | 说明 |
|---|---|---|
| `fixtures/zmai/real_masked_coding_agent_pass.json` | **真实**，脱敏 | 派生自 ZMAI `A1_echo_on_20261011_114528` 的 `execution_log.json`（44 步，最终 69 passed）。路径与绝对位置已移除。 |
| `fixtures/zmwiki/real_masked_rag_multihop.json` | **真实**，脱敏 | 派生自 ZMWiki `benchmark/results/phase09_smoke.checkpoint.jsonl`（`mh01` recall 2/2、`mh03` recall 2/3）。 |
| `fixtures/zmwiki/real_masked_phase09_checkpoint.jsonl` | **真实来源，脱敏节选** | 同一 phase09 原始 JSONL 的 `mh01`、`mh03` 两行；人名、项目名、步骤摘要已替换，保留引用 ID 和召回分子/分母用于适配回归测试。 |
| `fixtures/synthetic/*.json` | **合成** | 为覆盖 `UNKNOWN` 与 false-completion 形状而构造，**不是实测成果**，不得对外引用为真实数据。 |
| `fixtures/invalid/*` | 合成反例 | 由合法样本 perturb 生成，用于验证拒绝路径。 |

## P0.0 遗留与阻塞

1. **真实样本的原始 `snapshot_sha256` / `config_sha256` 为 `null`**：P0.1b 可从规范化 case 内容计算新哈希，但无法追溯证明历史运行当时使用的原始数据集快照。历史 A/B 仍不可直接判为可比。
2. **ZMAI 的 `execution_log.json` 没有 Token/成本字段**：`budget.request_log` 中有 `input_tokens`/`output_tokens`，但多数为 null。已按契约置 `null` + `measurement_status=unavailable`，没有伪造成 0。
3. **历史 `trace_complete` 不能独立证明完整性**：ZMAI 历史 fixture 未附带原始 Trace 字节、独立哈希和终止证据。新规则按 UNKNOWN 处理；后续原始日志适配器须保存可复核来源，不能据人工标记补造完整性。

## 下一步

需要由新运行的可信采集流程提供可核验的数据集快照、评测结果和执行条件，才能对真实 A/B 运行 P0.3a 对比及 P0.3b Gate。ZMWiki 历史数据的答案评测需要与 checkpoint 哈希一致的参考数据集。当前 Gate 为纯离线入口，不建持久化表。
