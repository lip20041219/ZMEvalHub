# ZMEvalHub — AI Agent 可靠性评测中台

> **工程启动与实施总纲（Engineering Blueprint）v2.0**  
> 项目名称：**ZMEvalHub**（ZM Evaluation Hub）  
> Python 包名：`zmevalhub` · CLI：`zmeval` · GitHub 仓库建议名：`ZMEvalHub`  
> 文档制定日期：2026-11-11 · 状态：**规划基线 / 尚非已实现能力**  
> 适用对象：个人开发者、AI 应用工程师、Coding Agent / RAG 开发者。  
> 启动原则：**成熟轮子负责执行与算法，ZMEvalHub 负责统一协议、可靠性诊断、可复现对比与质量门禁。**

---

## 阅读指南与约束

- 本文以用户提供的《ZMEvalHub — AI 应用评测中台 工程启动文档》v1.0 为基础重构：**保留项目/数据集/任务/结果/模型/Trace/报告/CI 的核心范围**，修正早期微服务化、过度自研和范围过大的问题。
- 本文件是**启动制作大纲和验收依据**，不表示以下仓库、命令、接口、页面已经创建。示例命令只有在对应阶段实现后才能执行。
- **MVP = 真正能导入/运行评测、保存证据、对比版本并生成结果的最小可用系统**；不是只有页面和模拟数据的展示项目。
- 默认一个人开发、优先本机运行、尽量不消耗付费模型 Token；首先保证**零外部模型调用**也能完整演示。
- 明确区分：**事实（GitHub 已提供） / 设计决策（本项目计划实现） / 候选扩展（暂不承诺）**。

### 一页决策摘要

| 决策 | 最终方案 | 不选的方案及原因 |
|---|---|---|
| 项目路线 | **Agent 可靠性评测中台**，兼容 RAG / Prompt | 不做泛化企业数据治理中台，方向偏离 AI 应用开发 |
| 项目代号 | **ZMEvalHub**；模块统一 `zm`/`zmeval` 命名 | 不另起与 ZMAI、ZMWiki 无关的品牌 |
| 主架构 | **模块化单体 API + 独立异步 Worker** | MVP 不做 Java + Python 双后端微服务，减少两套接口/部署/事务维护 |
| 前端 | **Vue 3 + TypeScript + Vite + Element Plus + ECharts** | 保留原稿成熟选型，不无故切 React |
| 后端 | **Python + FastAPI + Pydantic v2 + SQLAlchemy 2 + Alembic** | 与 Ragas/Inspect AI 等 Python 生态直接连接，无需跨语言评测 RPC |
| 存储 | **PostgreSQL**（标准环境）；测试可用 SQLite | 不另加向量数据库，评测数据主要是关系与 JSON/Trace |
| 队列 | **Redis + RQ**（仅后台任务） | 不自研 Redis 线程池队列、任务确认和失败重试 |
| 主评测库 | **Ragas**（按需）、**Promptfoo 外部 CLI/结果导入** | 不重写复杂指标、Provider、Prompt 测试执行器 |
| Agent 基准 | **Inspect AI / Harbor 适配器（后续）** | 不自研容器隔离/Benchmark harness |
| Trace 规范 | **内部稳定事件模型 + OpenTelemetry/OpenInference 对齐** | 不发明自有遥测协议，也不在 MVP 重造完整 Tracing 平台 |
| 模型调用 | MVP 只支持**离线结果 + 可选外部评分器** | 不再自研统一多厂商 Provider SDK |
| 质量闸门 | **确定性规则优先、Judge 可选** | 避免付费模型打分成为唯一真值 |
| 初版部署 | Docker Compose（Web/API/Worker/PostgreSQL/Redis） | 不上 Kubernetes、Kafka、ClickHouse、Milvus、MinIO |
| 初版用户 | 本地单用户 / 仅回环地址 | 不抢先做 RBAC、多租户、企业认证 |

---

# 1. 立项定义

## 1.1 解决的真实问题

Agent 开发者经常能得到一个“任务成功/失败”的结果，却不能快速回答：

1. Agent **为什么说自己完成了**？是否真的有外部测试、证据或工具结果支撑？
2. 执行过程中是否出现**未验证修改、重复读取、无效重试、循环不收敛、超预算**？
3. 一次修复/Prompt 调整后，**哪些固定用例改善、哪些退化**？能否做到相同用例的公平比较？
4. RAG 返回答案时，**证据是否找全、答案是否有依据**？
5. 是否能在不重复调用高价 LLM 的前提下，**对已有 Trace/运行结果做离线复评**？

**ZMEvalHub 的产品定义**：集中管理不可变评测数据集与运行记录，接入已有执行结果及开源评测器，产出**可追溯证据、可解释规则判定、成对版本差异与 CI 回归门禁**。

## 1.2 核心用户和场景

| 用户 | 触发场景 | 期待产出 |
|---|---|---|
| Coding Agent 作者 | 改 Runtime/Guard 后想验证没有错判完成 | 错误完成、漏验证、循环、成本、耗时的对比报告 |
| RAG 开发者 | 修改检索/重排/Prompt | 证据召回、可回答率、答案质量的同集对比 |
| AI 应用后端工程师 | 准备发版或更新模型配置 | 离线回归和质量 Gate 的 exit code |
| 面试/开源体验者 | 本地看项目实际能力 | 一条命令演示真实固定数据集、失败定位和版本差异 |

## 1.3 与现有 ZM 项目的边界

- **ZMAI**：被测 Coding Agent。输出执行结果、工具事件、验证证据；**不强制改造 ZMAI 内核**。
- **ZMWiki**：被测多跳检索/问答 Agent。输出问题、答案、已检索证据 ID、参考证据 ID、可回答标注；可从已有 JSONL 评测结果导入。
- **Friday / 其他 Agent**：未来第三方兼容性样本，**不是 MVP 必须接入**。
- **Prompt 管理/版本管理项目**：仅预留 `prompt_version` / `config_hash` 字段；不将外部平台作为 MVP 的启动依赖。
- **ZMEvalHub**：统一评测资产、结果、对比、质量门禁；**不替代 ZMAI 的执行循环，也不替代 ZMWiki 的检索引擎**。

## 1.4 明确不做的事情

**MVP 不做**：通用数据中台、模型训练/微调、海量模型排行榜、多租户权限、在线社区服务、分布式容器调度、自建向量库、自建 LLM Gateway、自动 Prompt 优化平台、Prompt 注入红队全套、独立 Benchmark 运行环境、企业 SSO。

**v1.0 也不承诺**：超大规模并发、生产 SLA、所有模型/框架零配置接入、全自动可靠根因推断、对每一次输出提供可信“幻觉率”。

## 1.5 差异化主张（不是宣传性断言）

> **可靠性优先（Reliability-first）**：把“任务成功”与“代理自称成功”分离，把 Trace 与实际验证证据连接，提供可重放的规则判定、逐案例回归和结果差异解释。

这一主张是**要通过产品与对比测试验证的目标**，不是声称其他平台都不具备类似能力。Opik、Phoenix、Langfuse 已提供丰富的评测和观测功能；ZMEvalHub 必须用**证据模型、规则配置、回归报告的可复现性**建立项目价值，而不是仅实现同类 CRUD/图表。

---

# 2. GitHub 开源借鉴与复用策略

## 2.1 主参考和复用边界

| 开源项目 | 官方 GitHub | 已有能力 / 借鉴点 | ZMEvalHub 实际做法 | 优先级 |
|---|---|---|---|---|
| **Opik** | https://github.com/comet-ml/opik | 数据集、实验、Trace、自动评测及平台交互 | **架构/产品参考**；以后可选择导入其实验结果，不 Fork 整个平台 | 高 |
| **Promptfoo** | https://github.com/promptfoo/promptfoo | 声明式测试、断言、CLI、模型对比、JSON 输出 | **保留其原始执行器**；通过版本化 JSON 导入适配，不移植其断言实现 | 高 |
| **Ragas** | https://github.com/vibrantlabsai/ragas | RAG 指标、实验和评测接口 | **作为可选 Python 依赖直接调用**；适配分数、错误、成本 | 高 |
| **Arize Phoenix** | https://github.com/Arize-ai/phoenix | Trace、数据集、实验与观测 | 学习 Trace/Span 表达；后续用 OTel/OpenInference 对接，不复制 Phoenix 后端 | 高 |
| **Inspect AI** | https://github.com/UKGovernmentBEIS/inspect_ai | 任务、模型、工具、评分、可扩展评测 | 后续封装其日志或任务结果适配器；不重写任务/评分基础设施 | 中 |
| **Harbor** | https://github.com/harbor-framework/harbor | 多 Agent 的隔离环境与基准执行 | 后续对接 Benchmark 产物；不自己造 Docker Agent Runner | 中 |
| **Langfuse** | https://github.com/langfuse/langfuse | Trace、质量、实验与成本追踪 | 参考执行链路和运营展示；不是 MVP 部署依赖 | 中 |
| **DeepEval** | https://github.com/confident-ai/deepeval | 代码式 LLM 质量断言与测试 | 在 Ragas 不适配的指标场景下选用；避免同时引入相似评分器 | 中 |
| **OpenCompass** | https://github.com/open-compass/opencompass | 通用模型基准评估 | 仅研究数据/报表规范；不作为 MVP 引擎 | 低 |
| **OpenTelemetry** | https://github.com/open-telemetry/opentelemetry-python | 标准追踪与 OTLP | 使用官方 SDK / 标准；避免自定义遥测基础协议 | 高 |

**已经核实的关键点（以仓库公开说明为准）**：Opik 提供开放自托管评测平台，Apache-2.0；Promptfoo 是 CLI 与库并带 Web Viewer，MIT；Inspect AI 为 MIT；Langfuse 仓库除 `ee` 目录外采用 MIT；Phoenix 支持基于 OpenTelemetry 的追踪；Ragas 提供 Python 指标与实验能力。**使用任何代码/依赖时，仍要在落地前复核具体版本、目录许可、API/锁文件与上游更新。**

## 2.2 “不重复造轮子”红线

**直接复用**：

1. RAG 忠实度、相关性、上下文指标：Ragas；不自研相同算法。
2. Prompt/模型 Provider 与测试配置：Promptfoo / 官方 SDK / 已成熟适配库；不开发万能 Provider 系统。
3. 异步任务、数据库、迁移：RQ、Redis、SQLAlchemy、Alembic；不手写持久队列或 ORM。
4. 基准 Agent 环境、容器隔离：Inspect AI、Harbor 或原项目已有 Harness；不重造执行沙盒。
5. Trace 基础标准：OpenTelemetry/OpenInference；不设计与行业标准互斥的协议。
6. 前端表单、表格、图表：Element Plus、ECharts；不自制 UI 组件库。

**ZMEvalHub 应当自己实现的内容**（才是项目主体）：

- `zm-eval` **规范化数据契约**与外部结果转换器；
- 数据集快照、不可变评测运行、评分证据的**关联模型**；
- Agent 可靠性规则（如“声称完成但无验证证据”“验证失败仍 COMPLETED”）；
- 同用例、同规则版本的**成对差异、置信度信息与质量 Gate**；
- 将失败样本与 Trace 节点、外部证据一键关联的 UI/报告。

## 2.3 开源参考与集成实施顺序

1. **先调通一个固定的 Promptfoo JSON 导入样本**，保存实际导入格式及格式版本；不要先写“完全兼容 Promptfoo”。
2. **用 Ragas 官方示例完成一个最小打分 Spike**，记录具体版本、依赖、模型成本与超时情况。
3. **先读 Phoenix/Opik 的数据流设计**；不直接复制代码、页面、数据库表结构。
4. 当 ZMEvalHub 核心事件结构稳定，再做 **OTel/OpenInference → Trace 导入**。
5. 只有需要真实 Coding Agent 跨框架执行时，才接 Harbor/Inspect AI。

## 2.4 依赖与许可证管理

- 每项第三方依赖记录：上游仓库、精确版本/Commit、许可证、用途、更新日期、兼容性测试、是否直接复制代码。
- `docs/THIRD_PARTY.md` 记录直用库和架构参考（仅参考思想的项目不声称是项目依赖）。
- 发布时对源代码复制、图片、商标、样例数据分别做许可核查；选择自己项目的 LICENSE 不会自动覆盖上游许可证。
- MVP **不直接复制 Opik/Langfuse/Phoenix 前端页面或品牌素材**。

---

# 3. 产品需求和版本边界

## 3.1 P0（首个可用 MVP）

| 编号 | 功能 | 可验证验收 |
|---|---|---|
| F-01 | 创建项目和评测集 | 创建、查看、编辑基本信息；同名处理一致 |
| F-02 | 评测用例导入（JSONL/CSV 优先） | 合法数据导入成功；非法行有行号/原因；重复导入幂等 |
| F-03 | 冻结数据集快照 | 一次 Run 绑定具体 `snapshot_id`，后续修改用例不改历史结果 |
| F-04 | 导入 ZMAI / ZMWiki 既有运行结果 | 不修改两项目核心代码即可导入固定 fixtures |
| F-05 | 后台执行确定性规则评分 | 任务可创建、执行、失败、重试且有持久化记录；不依赖外部模型 |
| F-06 | 用例级结果与 Trace 查看 | 可定位判定依据的具体事件/证据；缺证据标记 unknown |
| F-07 | 两版本成对对比 | 显示共同用例、改善/退化/持平、不可比较情况 |
| F-08 | 质量门禁与 Markdown 报告 | 指标阈值命中后 CLI 退出码明确；可在 CI 使用 |
| F-09 | 完整本地一键 Demo | Docker Compose 能启动；示例结果来源真实固定 fixtures，而非随机数 |

**P0 的边界**：单用户、本地运行、无需账号；提供一个独立的异步评分 Worker；模型调用开关默认关闭。P0 允许**导入已经运行过的 Agent 结果并复评**，无需替代 SWE-bench 或多跳 Harness 来重新执行被测 Agent。

## 3.2 P1（增强评测能力）

- 接入 Ragas 可选指标（以其官方 API 和版本锁定）；评分来源、Judge 模型、Prompt 版本可追踪。
- 导入 Promptfoo `--output results.json`；支持一份版本化实测 fixture。
- OpenTelemetry/OpenInference 追踪适配（不能只支持自定义 JSONL 就声称全面兼容 OTLP）。
- 评测项重复试验 / 多次样本，按成对或分布统计。
- 可选使用受控本地/远程目标执行器发起 **已登记的** Prompt/RAG 任务；不能执行任意用户提交的 Shell。
- 可扩展 `zmeval` CLI / SDK 接入第三方结果。

## 3.3 P2（前提是 P0/P1 真实使用证明需求）

- 多用户认证与 RBAC、API Token、独立项目空间。
- 生产 Trace 摄取、OTLP Collector、存储保留策略。
- Harbor / Inspect AI 集成，联动容器隔离基准执行。
- 可选生产化 PostgreSQL/Redis HA、对象存储、任务重试管理、审计日志。
- 企业内部 CI 平台或 Prompt 管理平台对接。

**不按固定日程承诺 P2**。P0 可公开演示并被其他 Agent 作者复用之后，再评估是否增加。

---

# 4. 架构设计

## 4.1 模块化单体 + 独立 Worker

```text
       ┌──────────────────────────────────────────────────┐
       │             ZMEvalHub Access                     │
       │ Vue3 Console  │  zmeval CLI  │  REST / OpenAPI     │
       └──────────────────────┬───────────────────────────┘
                              │ HTTP/JSON
       ┌──────────────────────▼───────────────────────────┐
       │ Python FastAPI — zmevalhub                       │
       │ Project / Dataset / Snapshot / Run / Compare     │
       │ Import Adapters / Rule Registry / Gate / Report  │
       └─────────────┬────────────────────┬───────────────┘
                     │                    │ enqueue
                ┌────▼──────┐        ┌────▼───────────┐
                │ PostgreSQL│        │ Redis + RQ     │
                │ metadata  │        │ job transport  │
                └────▲──────┘        └────┬───────────┘
                     │                    │
                     └────────┬───────────▼───────────┐
                              │ Python RQ Worker      │
                              │ deterministic rules   │
                              │ optional Ragas        │
                              │ result normalization  │
                              └───────────┬───────────┘
                                          │
                    ┌─────────────────────▼──────────────────┐
                    │ Fixtures / JSONL / External adapters    │
                    │ ZMAI │ ZMWiki │ Promptfoo │ OTel (P1)   │
                    └────────────────────────────────────────┘
```

### 责任边界

- **FastAPI**：鉴权边界（P2）、数据模型验证、查询 API、任务提交、比较/报告的只读查询。不执行昂贵评分。
- **RQ Worker**：执行评分任务、结果持久化、成本/超时控制；与 API 使用同一 Python 包的领域服务。
- **PostgreSQL**：版本、快照、任务、Attempt、Score、证据关系、审计字段的唯一真实数据源。
- **Redis**：队列和短期任务状态缓存；**不是评测结果权威存储**。
- **Vue Console**：只调用 API；计算指标的权威逻辑在 Python 领域层。
- **Adapters**：把上游数据转换成项目内稳定 schema；上游版本变化不侵入领域代码。

## 4.2 为什么不沿用原文档 Java + Python 双后端

原 v1.0 用 Spring Boot 管理中台、FastAPI 做评测引擎。这在已有 Java 团队、独立部署或高并发场景合理，但个人启动阶段需要维护两份 DTO、认证、错误协议、跨服务超时及两套构建链。**评测生态核心 Python 化，FastAPI 可以先承担管理 API 和评测编排。**

只有出现**明确可测的组织/性能/Java 集成约束**，才新增 `zmevalhub-java-gateway`，并通过已版本化 REST 契约调用 API；不因技术栈“显得全面”而预先引入。

## 4.3 初版不引入向量库的原因

- Trace、用例、Run、评测 Score 的主要查询是主外键、时间、版本和属性过滤。
- Ragas/语义相似度评分不要求产品一定自建 Milvus/Chroma。
- 若以后有“在百万 Trace 中语义搜索失败模式”的真实需求，再基于现有数据库扩展或接检索服务。

## 4.4 部署拓扑和暴露策略

- **开发模式**：本机 Python / Node 进程 + Docker 中 PostgreSQL、Redis。
- **演示模式**：Docker Compose 启动 `web`、`api`、`worker`、`db`、`redis`。
- **MVP 默认只绑定 `127.0.0.1`**，不能把无鉴权 API 直接暴露在公网。
- `api` 有健康检查 `/healthz`；数据库迁移由启动命令显式执行；Redis / PostgreSQL 用 Compose healthcheck，服务有重启策略。
- 生产远程部署必须先做 TLS、认证、权限、备份、密钥与安全审计，不把 Compose 演示环境宣称为生产级 SLA。

---

# 5. 技术栈及依赖基线

> 版本策略：选定语言和组件主线，**阶段 0 查验兼容性后用 `uv.lock` / `pnpm-lock.yaml` 固定精确版本**。以下“版本线”不是声称已在本项目验证；禁止无锁 `latest` 部署。

| 层级 | 选型 | 引入理由 | 阶段 |
|---|---|---|---|
| Python | Python **3.12**（兼容性失败再选 3.11） | FastAPI、Ragas、评测 SDK | P0 |
| Python 依赖 | `uv` + `pyproject.toml` + `uv.lock` | 环境可复现、分组依赖 | P0 |
| API | FastAPI、Pydantic v2、Uvicorn | OpenAPI、类型校验、现代 Python Web | P0 |
| ORM/迁移 | SQLAlchemy 2、Alembic | 结构化模型与 schema 迁移 | P0 |
| DB | PostgreSQL **16+** | JSONB、事务、并发和索引 | P0 |
| 后台任务 | Redis **7+**、RQ | 成熟队列/Worker 复用 | P0 |
| Web | Vue 3、TypeScript、Vite、Vue Router、Pinia | 保留原稿技术栈 | P0 |
| UI/可视化 | Element Plus、ECharts | 通用表格、筛选、指标曲线和交互 | P0 |
| HTTP Client | `fetch` 或 Axios（二选一，P0 固定） | 避免重复客户端层 | P0 |
| 服务端测试 | pytest、pytest-cov、Ruff、mypy | 规则/迁移/适配器正确性 | P0 |
| Web 测试 | Vitest、Vue Test Utils | 组件、对比渲染测试 | P0 |
| E2E | Playwright（只保留关键 Smoke） | 从导入到报告的真实 UI 闭环 | P0 后期 |
| 评测指标 | Ragas（**extra `rag`**） | 不自研 RAG 指标 | P1 |
| 其他评分 | DeepEval（**可选 extra**） | 特定需求出现才加 | P2 候选 |
| 外部执行 | Promptfoo（外部可执行文件）、Inspect AI/Harbor（可选） | 复用成熟运行器 | P1/P2 |
| 遥测 | OpenTelemetry SDK / OpenInference | 标准化 Trace 接入 | P1 |
| 报告 | 标准 Markdown + JSON | 便于 GitHub/CI 审阅；不引入 PDF 渲染 | P0 |
| 部署 | Docker、Docker Compose、GitHub Actions | 本机演示与质量检查 | P0 |

### 技术选择实施规则

1. **Python 评测 API 是唯一权威评分入口**，不让前端另写一套评分公式。
2. 官方 SDK 不够用时才引入模型路由库；避免 LangChain、LiteLLM、OpenAI SDK、Spring AI 在 MVP 同时负责同一件事。
3. 默认不安装 Ragas/Inspect/Harbor 全部可选依赖；`uv sync --extra rag` 仅在确实需要时使用。
4. Node 选择当前维护中的 LTS 线，在 P0 兼容性 Spike 中确认；锁定 `.node-version`，不沿用原稿 Node 18 的旧基线。
5. `pyproject.toml` 采用 `src/` 布局；前后端各一份锁文件；CI 不能使用无限制浮动版本。

---

# 6. 领域模型（最重要的数据契约）

## 6.1 不要混淆三个结果

| 概念 | 说明 | 例子 |
|---|---|---|
| **执行状态** `run_status` | 平台执行/处理是否成功 | `SUCCEEDED`：评测流程跑完，**不代表 Agent 成功** |
| **被测任务结果** `subject_outcome` | Agent/RAG 自身宣称什么 | `COMPLETED`、`FAILED`、`UNKNOWN` |
| **评测判定** `verdict` | 规则/评分器对结果的判断 | `PASS`、`FAIL`、`UNKNOWN`、`ERROR`、`SKIPPED` |

`UNKNOWN` = 没有足够可验证的证据，**不是 FAIL**；`ERROR` = 评测器本身故障，**不是被测系统失败**。

## 6.2 一级实体与关系

```text
Project
 ├── Dataset ── DatasetSnapshot ── SnapshotCase
 ├── SubjectVersion (repo commit / model / config / prompt)
 ├── EvalRun  ── EvalAttempt ── ScoreRecord ── EvidenceRef
 │       │               └── TraceEvent
 │       └── RunArtifact (import file / report / tool output)
 ├── RuleSet ── RuleSetVersion
 ├── Comparison (baseline run + candidate run)
 └── QualityGatePolicy ── GateDecision
```

核心必须保证：

- `DatasetSnapshot` **不可变**，有内容 Hash；不能靠 `dataset.version='1.0'` 就假装数据已冻结。
- `RuleSetVersion` **不可变**，Run 记录评测器版本/配置/模型/Prompt；历史分数可追溯。
- `EvalRun` 绑定 `snapshot_id`、`subject_version_id`、`rule_set_version_id`、配置 Hash。
- 一次 Case 可能多次执行：用 `EvalAttempt` 区分 `attempt_index`，不覆盖旧结果。
- `TraceEvent` 是观察数据；能否证明成功由**证据类型与验证规则**决定。
- 数据库用 UTC 时间，前端在本地时区展示；耗时单独记录毫秒，别用壁钟差做唯一依据。

## 6.3 PostgreSQL 核心表（P0）

字段类型为逻辑建议，最终由 Alembic 迁移及 SQLAlchemy model 固定。主键推荐 UUID；JSON 字段用 JSONB；所有核心表设 `created_at`，变更类表设 `updated_at`。

| 表名 | 重要字段 | 必要约束和索引 |
|---|---|---|
| `zm_projects` | `id,name,slug,description` | `slug UNIQUE` |
| `zm_datasets` | `id,project_id,name,description,current_snapshot_id` | `(project_id,name)` 索引；FK |
| `zm_dataset_snapshots` | `id,dataset_id,schema_version,content_sha256,case_count,created_at` | `(dataset_id,content_sha256) UNIQUE`；创建后不更新内容 |
| `zm_snapshot_cases` | `id,snapshot_id,external_case_id,kind,input_json,expected_json,tags_json` | `(snapshot_id,external_case_id) UNIQUE` |
| `zm_subject_versions` | `id,project_id,subject_name,git_sha,model_id,prompt_version,config_sha256,metadata_json` | 允许无 Git 的导入型 subject |
| `zm_rule_versions` | `id,project_id,name,version,rule_config_json,config_sha256,engine_version` | `(project_id,name,version) UNIQUE` |
| `zm_eval_runs` | `id,project_id,snapshot_id,subject_version_id,rule_version_id,status,source,source_id,source_sha256,started_at,finished_at` | 按 project/time 索引；幂等键约束 |
| `zm_eval_attempts` | `id,run_id,case_id,attempt_index,subject_outcome,verdict,latency_ms,input_tokens,output_tokens,cost_amount,cost_currency,error_type` | `(run_id,case_id,attempt_index) UNIQUE` |
| `zm_trace_events` | `id,attempt_id,trace_id,span_id,parent_span_id,sequence,event_type,time_start,time_end,status,payload_json` | `(attempt_id,sequence)`；`(trace_id,span_id)` 组合索引 |
| `zm_evidence_refs` | `id,attempt_id,event_id,evidence_type,artifact_id,locator,sha256,availability,verified` | 可关联事件或 artifact；禁止游离证据 |
| `zm_score_records` | `id,attempt_id,metric_id,metric_version,value,numerator,denominator,verdict,confidence,origin,evidence_json,judge_config_hash` | `(attempt_id,metric_id,metric_version)` UNIQUE（重复评测需另标 evaluation revision） |
| `zm_run_artifacts` | `id,run_id,kind,path,sha256,size_bytes,redaction_state` | path 在固定受控根目录下；Hash 去重 |
| `zm_comparisons` | `id,project_id,base_run_id,candidate_run_id,comparable,reason,created_at` | Base/Candidate 都属该项目 |
| `zm_gate_policies` | `id,project_id,name,version,policy_json` | policy 版本冻结 |
| `zm_gate_decisions` | `id,comparison_id,policy_id,status,reasons_json,created_at` | 结果与策略版本关联 |

### 数据库原则

- 外键和 `CHECK` 约束显式写入迁移文件；删除 Project 默认**限制级联销毁历史结果**，提供归档。
- `source_id + source_sha256 + importer_version` 构成来源幂等键；重导入同一内容不得制造重复 Run。
- 同一 `snapshot_case` 的唯一 ID 可与外部用例 ID 保持稳定映射；**快照之间 case_id 相同不代表内容相同**，还须比对 `case_fingerprint`。
- 大型原始 Trace 文件放受控文件目录，表内只存索引和摘要；P0 小型事件直接入 DB。
- 比较历史数据时不修改旧 `ScoreRecord`；若规则升级，建立**新 Run / evaluation revision**。

## 6.4 统一数据格式（`zmeval.schema_version = 1`）

以下例子为 **计划支持的规范数据**，不是现有 ZMAI/ZMWiki 原始输出字段；要由适配器映射。示例是虚构 fixture，不代表真实历史评测。

```json
{
  "schema_version": 1,
  "source": "zmai",
  "source_run_id": "fixture-2026-001",
  "subject": {
    "name": "ZMAI",
    "git_sha": "1111111111111111111111111111111111111111",
    "model_id": "offline-fixture",
    "config_sha256": "demo-config-hash"
  },
  "dataset": {
    "name": "agent-reliability-smoke",
    "snapshot_sha256": "demo-dataset-hash"
  },
  "cases": [
    {
      "case_id": "case-no-verification",
      "kind": "coding_agent",
      "input": {"task": "修复一个失败的单元测试"},
      "expected": {"requires_post_edit_test": true},
      "attempts": [
        {
          "attempt_index": 0,
          "subject_outcome": "COMPLETED",
          "events": [
            {"sequence": 1, "event_type": "file_edit", "status": "ok"},
            {"sequence": 2, "event_type": "agent_finish", "status": "ok"}
          ],
          "artifacts": []
        }
      ]
    }
  ]
}
```

**契约补充**：上面的 Hash 是示意，正式导入要求合法、可校验的 SHA-256（64 位十六进制）；真实导入前由 Pydantic Schema 自动校验，不直接以这些示意值作为生产数据。可发布到 `docs/schema/v1.json`，并提供回归 fixture。

### 数据格式设计要求

- 所有时间 ISO 8601 UTC；事件至少有单调 `sequence`，即便原日志缺精确时间也能定位顺序。
- 允许 `raw_payload` 缺失，但必须能给出缺失原因。
- 未提供 Token/成本不得写成 0：使用 `null` + `measurement_status = unavailable`。
- RAG Gold Evidence 使用**稳定文档/段落标识**；不能把摘要文本相似就等同证据命中。
- JSON Schema 文档、Pydantic 模型与导入转换器必须有一致性测试。

---

# 7. 评测规范：规则、指标和证据

## 7.1 评测标准层次

```text
Level 0 结构合法：能否解析、用例能否匹配、字段是否完整
Level 1 确定性规则：文件修改/验证/状态条件、证据 ID 交集等
Level 2 现成评测库：Ragas、Promptfoo、Inspect AI 输出导入
Level 3 可选 LLM-as-Judge：只作为明示配置的补充评分
```

**规则优先级**：确定性事实和独立验证结果优先于模型自称“成功”；Judge 不能推翻真实测试失败证据。不能因日志没有测试事件就断言“没有测试过”，只有**数据覆盖完整且规则明确**时才能判为 FAIL，否则 UNKNOWN。

## 7.2 Coding Agent 可靠性规则（P0 第一批）

| ID | 规则名 | 条件（精确可执行） | 判定 | 所需证据 |
|---|---|---|---|---|
| `ZM-R001` | `completion_without_verification` | 有成功文件修改，随后 Agent 宣称 COMPLETED，但在完整事件窗口内无合格验证事件 | FAIL（输入数据声明覆盖完整时）/ 否则 UNKNOWN | 修改事件、完成事件、完整性标志、验证类型配置 |
| `ZM-R002` | `failed_verification_then_completed` | 最近一次被认可的验证失败，且之后无更新的成功验证，Agent 仍 COMPLETED | FAIL | 验证执行状态、退出码、时间/顺序 |
| `ZM-R003` | `post_validation_edit` | 最近一次成功验证后又修改影响验证范围的文件，且之后未重新验证 | FAIL/UNKNOWN（无影响范围时） | 文件变化路径、验证覆盖范围 |
| `ZM-R004` | `repeated_tool_no_progress` | 在可比工具调用摘要上连续重复达到配置阈值，期间无可确认进展 | WARNING/FAIL（按策略） | 规范化工具签名、输出 Hash、动作序列 |
| `ZM-R005` | `budget_or_loop_exhaustion` | 运行日志明确标注超预算或循环守卫终止 | FAIL（任务目标未达成） | 终止原因 / 预算快照 |
| `ZM-R006` | `external_test_success` | 有有效测试执行证据，且符合成功条件 | PASS（针对验证规则） | 退出码、测试摘要、来源标识 |

**绝对不能用作成功证明**：Agent 自然语言说“已经修复”；缺失 Exit Code 的 Shell 日志；只跑无关测试；大模型对自身修复的评价。对于某些任务“不需要修改代码”，`ZM-R001` 不应触发；不要用过分宽泛的全局规则。

## 7.3 RAG 指标和输入前提

| 指标 | 来源 | 必要输入 | 无法满足前提时 |
|---|---|---|---|
| `evidence_recall` | **本项目确定性集合指标**（针对标注证据 ID） | Gold evidence IDs、retrieved evidence IDs | N/A，绝不按 0 处理 |
| `answerable_success_rate` | 数据集标注 + 结果断言 | 可回答标志、可检查参考答案/标注 | N/A |
| `multi_hop_success_rate` | 有明确 hop/支持证据的测试集 | 目标 hop 证据、回答判定 | N/A |
| `faithfulness` | **Ragas** | user input / retrieved contexts / response 等库版本要求 | `SKIPPED` 或 `ERROR`，不得假装已评分 |
| `answer_relevance` | **Ragas** | 对应版本支持的字段/模型 | 版本兼容检查失败则提示 |
| `context_precision/recall` | **Ragas** | 对应所选 metric 的必填字段 | N/A |

Ragas 的不同指标不一定共享所有字段，**必须使用所锁定版本的官方示例与 API**，不能把 `Faithfulness`/`ContextRecall` 名字硬编码成永久稳定契约。

`evidence_recall` 示例：Gold IDs = `{A,B,C}`，实际命中 `{A,B}`，该案例 recall = `2/3`。没有 Gold IDs 的不可回答样本不进入此均值分母。

## 7.4 指标数值与分母

- `task_success_rate = verified_success_attempts / eligible_attempts`；“verified success”是外部验证满足规则，不是 `subject_outcome=COMPLETED`。
- `false_completion_rate = verified_false_completions / eligible_claimed_completions`；**仅对具备判断资格的完成声明计入分母**，同时报告 `unknown_completion_count`。
- `post_edit_validation_rate = edits_with_valid_post_edit_verification / eligible_edited_attempts`；以**尝试数**统计，而非原始 edit 次数（若需要 edit 级分母需定义独立指标）。
- `loop_guard_trigger_rate = guard_terminated_attempts / eligible_attempts`；不一定越低越好，应与成功率联看。
- `cost_per_verified_success = total_attributable_cost / verified_success_count`，若分母为零显示 `N/A`；标注费用为 provider 报告值或估算值。
- `p50/p95 latency`：从有真实延迟记录的样本计算，并显示样本数；导入缺失不得填 0。

**每个分数最少保存**：`metric_id`、`metric_version`、`value`、`numerator/denominator`（适用时）、`unit`、`direction`、`sample_count`、`origin`、`verdict`、`evidence_refs`、`evaluator_hash`。

## 7.5 证据链与失败定位

结果详情必须形成：

```text
案例 → 规则命中 → 判定原因 → 相关事件（Trace） → 原始输出/校验摘要
```

例如：`ZM-R002` FAIL，定位到**第 5 步 pytest 退出码 1** 与**第 7 步 agent_finish=COMPLETED**，中间没有新的成功验证。若只有不完整日志，UI 必须显示“缺证据，无法判断”。

**P0 不宣称自动根因诊断**：展示**规则证据定位**与人为标注的原因类别。推断“模型为什么这样做”的语义根因属于未来研究，不可凭空给确定性解释。

## 7.6 LLM-as-Judge 安全与成本约定

- 默认 **disabled**；用户明确开启后才允许调用外部模型。
- 需要记录 `judge_provider`、`judge_model`、`judge_prompt_hash`、`temperature/seed`（如有）、`rubric_version`、Token、费用、状态、原始评分摘要。
- `judge_timeout_sec`、`max_calls`、`max_cost`、`max_concurrency` 必填或有保守默认。
- 模型输出与 Trace 是**不可信数据**，不能让评判 Prompt 中的外来指令覆盖评分要求。
- Judge 不可用于声明真实代码测试通过或替代沙盒执行结果；报告中标注“模型辅助评分”。

---

# 8. 运行管理与异步任务机制

## 8.1 Run 的状态机

```text
CREATED → QUEUED → RUNNING ─┬→ SUCCEEDED
                            ├→ PARTIAL
                            ├→ FAILED
                            ├→ TIMED_OUT
                            └→ CANCELED
CREATED/QUEUED ─────────────────────────→ CANCELED
```

- **导入与评测分开**：`POST /runs/import` 完成合法数据落库后，Run 保持 `CREATED`（原始导入完成由 `ingest_status=IMPORTED` 单独表示）；`POST /runs/{id}/evaluate` 才启动上述执行状态机，防止把“导入成功”误写为“评分成功”。
- `SUCCEEDED` 只表示**所有约定评测工作已正确执行并保存结果**，不代表被测 Agent 通过。
- `PARTIAL` = 一部分案例有合法结果，另一部分评测器失败/超时/取消；报告必须展示覆盖率。
- `FAILED` = 平台执行失败导致无法完成约定评测；与 `verdict=FAIL` 不同。
- `CANCELED` 为尽力而为，Worker 在安全检查点停止；已完成的 Attempt 保留。

## 8.2 提交与幂等

1. API 校验 `snapshot`、`rule_version`、`subject`、任务范围和预算。
2. 创建数据库 Run，分配不可变 `run_id`、`idempotency_key`。
3. 向 RQ 投递 `evaluate_run(run_id)`；Worker **从数据库读取上下文**，不将凭据/超大 Trace 塞入 Redis 消息体。
4. Worker 按 case/attempt 编写 Score，更新 Run 聚合；所有操作可重复执行而不产生重复记录。
5. DB 与 Redis 无跨系统事务：提供**对账/重投工具**（检查创建后未入队、Worker 中断、RQ 状态与数据库不一致），不可假定“写 DB 成功 + 入队成功”天然原子。

## 8.3 故障规则

- 配置错误：不盲目重试，记录明确错误类型。
- 网络抖动/外部评分器 429：限制次数的指数退避，尊重预算；幂等写入。
- Judge/评分器超时：只将对应 Case 标为 `ERROR`/`SKIPPED`，不得伪造 0 分。
- Worker 崩溃：通过 RQ registries / job timeout + DB reconcile 恢复可重试任务；P0 可用 CLI 手动对账，P1 自动化巡检。
- **不得自动重复调用付费模型**，除非用户授权重试预算。

## 8.4 资源约束（默认建议，需实际压测）

- Demo Worker = 1；外部 Judge 默认 0 并发。
- 每次导入限制请求体大小、行数、事件数、Trace 深度、压缩包展开体积；具体数值在 P0 基准测试后配置。
- 取消任务后不抹除部分输出；重新运行必须有新 Run ID。
- 不把 GitHub Action 的 CI Token 和模型 API Key 存在结果导出文件里。

---

# 9. 基线对比与质量 Gate

## 9.1 比较资格

**可直接比较**必须满足：

1. 两个 Run 的 `snapshot.content_sha256` 一致（或 Case fingerprint 成对一致，并显式标注子集覆盖率）。
2. 目标任务定义一致；case IDs/参考答案不能随意改动。
3. 同一个 metric 具有一致 `metric_version`、聚合规则、阈值方向；若 Judge 不同，只展示不可直接比较或需要重评。
4. 重复运行次数、样本种子、工具环境、并发和超时差异在报告中明确展示。
5. 对缺失 Case、ERROR、UNKNOWN 有单独数量，**不静默忽略为“成功”**。

## 9.2 对比报告内容

- 基线：`baseline_run_id`；候选：`candidate_run_id`。
- 共同用例 `matched_count`、仅基线/仅候选用例、不可比的案例及原因。
- `pass→fail`、`fail→pass`、`unchanged`、`unknown`；按规则/失败类别聚合。
- KPI：verified success、false completion、post-edit validation、evidence recall、latency/cost（仅有效样本）。
- `delta = candidate − baseline`；显示方向（↑ 越好或 ↓ 越好）和 `N/A`。
- 小样本只展示样本数与差异，不把少量案例改善解释为统计显著。

## 9.3 Gate 规则示例

```yaml
schema_version: 1
name: zm-agent-regression
mode: paired
baseline_run: "baseline-run-id"
checks:
  - metric: false_completion_count
    operator: lte
    value: 0
  - metric: verified_success_rate
    operator: delta_gte
    value: 0.0
  - metric: unknown_completion_count
    operator: lte
    value: 0
minimums:
  matched_cases: 10
  valid_coverage_ratio: 0.95
on_incomparable: error
on_evaluator_error: error
```

**语义固定**：

- `PASS`：全部必须规则满足且比较资格成立。
- `FAIL`：存在可确认的质量指标违例。
- `ERROR`：输入损坏、评测器崩溃、没有合格基线或不可比较；**不能当作 PASS**。
- `WARN`：非强制项超阈值、样本量较小，但全部强制项成立。

CLI 退出码建议：`0` Gate PASS/WARN（WARN 是否失败由 `--strict` 控制）、`1` 质量 FAIL、`2` 执行/比较 ERROR、`3` 配置/用法错误。输出 JSON/Markdown，并让 CI 读取退出码。

---

# 10. API 设计（版本化）

## 10.1 总原则

- 前缀：`/api/v1`；请求和响应采用 JSON；OpenAPI 文档自动生成。
- HTTP 状态码与业务状态分开：例如创建返回 `201`，参数错误 `422`，资源冲突 `409`，后台任务接受 `202`。
- 统一错误体：`error.code`（稳定机器码）、`error.message`（可读）、`error.details`、`request_id`。
- 列表采用 `limit + cursor`（P0 也可 offset，但需固定一种）、默认排序稳定。
- `PATCH/PUT` 更新配置不会修改历史 DatasetSnapshot/Run/RuleSetVersion。

### 典型错误体

```json
{
  "error": {
    "code": "ZM_DATASET_VALIDATION_FAILED",
    "message": "第 7 行缺少 case_id",
    "details": {"row": 7, "field": "case_id"}
  },
  "request_id": "request-id-example"
}
```

## 10.2 P0 API 清单

| 方法 | 路径 | 用途 |
|---|---|---|
| `GET` | `/healthz` | API 存活 |
| `GET` | `/readyz` | DB/Redis 可用性（可分别报告组件状态） |
| `POST` | `/api/v1/projects` | 创建项目 |
| `GET` | `/api/v1/projects` | 项目列表 |
| `POST` | `/api/v1/projects/{pid}/datasets` | 创建数据集 |
| `GET` | `/api/v1/projects/{pid}/datasets` | 数据集列表 |
| `POST` | `/api/v1/datasets/{did}/import` | 导入用例和校验结果（预览可先返回 dry-run） |
| `POST` | `/api/v1/datasets/{did}/snapshots` | 创建只读快照 |
| `GET` | `/api/v1/snapshots/{sid}/cases` | 快照用例分页 |
| `POST` | `/api/v1/runs/import` | 导入外部执行结果，返回 run_id 与校验详情 |
| `POST` | `/api/v1/runs/{rid}/evaluate` | 通过已有规则版本发起异步评分 |
| `GET` | `/api/v1/runs/{rid}` | 运行状态、覆盖率、汇总 |
| `GET` | `/api/v1/runs/{rid}/attempts` | 用例级结果 |
| `GET` | `/api/v1/attempts/{aid}/trace` | 某次尝试的 Trace 事件 |
| `GET` | `/api/v1/attempts/{aid}/scores` | 分数、判定与证据 |
| `POST` | `/api/v1/comparisons` | 创建基线/候选比较 |
| `GET` | `/api/v1/comparisons/{cid}` | 比较详情与可比性说明 |
| `POST` | `/api/v1/comparisons/{cid}/gate` | 用指定策略评估质量 Gate |
| `GET` | `/api/v1/runs/{rid}/report.md` | Markdown 报告 |
| `GET` | `/api/v1/comparisons/{cid}/report.md` | 差异报告 |

不提前承诺外部评测请求一定要同步返回打分；昂贵运行统一异步。接口名称在 P0 contract tests 固定后再做发布兼容承诺。

## 10.3 核心请求范例

```json
{
  "baseline_run_id": "uuid-baseline",
  "candidate_run_id": "uuid-candidate",
  "comparison_mode": "paired",
  "allow_subset": false
}
```

返回包括 `comparable`、`reasons`、`matched_cases`、`metric_deltas`、`case_changes`；不可比时不抛 500，除非服务器真正出错。

---

# 11. 适配器设计和真实项目接入

## 11.1 `SourceAdapter`（只转换，绝不修改原工程）

```python
from typing import Protocol

class SourceAdapter(Protocol):
    source_name: str
    schema_version: int

    def validate(self, raw: bytes) -> None: ...
    def convert(self, raw: bytes) -> dict: ...
```

以上是**抽象示意**，正式实现使用 Pydantic 类型和 `importer_version`，避免 `dict` 漫天飞。

### P0 第一个适配器：`zmai-jsonl`

**需要从现有日志提取**：case ID、Git/配置版本、尝试/动作序列、文件修改事件、验证执行与 Exit Code、终止原因、Agent 声称状态、Token/耗时（如有）。

- 先使用**现有真实结果文件**完成只读数据映射；不要在本项目直接改 ZMAI Runtime。
- 若历史日志缺字段：展示 `UNKNOWN`，并输出 `missing_fields`；不臆造“0 次错误完成”。
- 后续只给 ZMAI 添加薄出口 `--export zmeval-jsonl`（是否实施由接入测试决定）。

### P0 第二个适配器：`zmwiki-jsonl`

**需要提取**：question ID、可回答标注、参考 evidence IDs、检索 evidence IDs、回答、实际命中与评价状态、异常原因、Token/耗时（可选）。

- 能复算确定性 evidence recall，不与不同数据集/评估口径的历史均值直接对比。
- 多跳成功必须有明确定义的 hop/答案判据，不能仅凭“检索次数大于 1”判为成功。

### P1：`promptfoo-json`

- 基于 `promptfoo eval --output results.json` 的**具体版本输出**做字段映射。
- 保留 `promptfoo_version`、配置 Hash、断言细节、Provider、Prompt 变量等来源信息。
- 转换时保留上游得分来源，**不把它伪装成 ZMEvalHub 自己算出的分数**。

### P1：`otel-trace`

- 解析标准 Trace/Span，维护 `trace_id`、`span_id`、`parent_span_id`、属性和时序。
- 先实现文件导入/OTLP 兼容测试，再考虑长期监听 Collector。
- 生成式 AI 语义约定可能演进：记录所支持的 convention 版本、做兼容映射，不依赖不稳定字段作为唯一事实。

## 11.2 适配器回归契约

每个适配器必须有：

1. 一份**授权的、去标识化的真实样本**和一份故意破损 fixture；
2. 源版本说明、字段映射表、缺失字段规则；
3. 幂等导入测试、schema 校验测试、Hash 校验测试；
4. 对重复导入、顺序乱序、null、非法类型、大文件的处理测试；
5. 适配器错误不可污染其他 Run。

---

# 12. Web 工作台：信息架构和交互验收

## 12.1 页面布局

```text
ZMEvalHub
├── Overview               项目质量总览 / 最近回归
├── Projects               项目与被测对象
├── Datasets               评测集 / 快照 / 用例
├── Runs                   评测运行 / 队列 / 状态
│   └── Run Detail         指标 / Attempts / Trace / 证据
├── Comparisons            A/B 成对对比 / 退化用例
├── Quality Gates          质量门禁 / 规则版本
└── Settings               本地配置 / 脱敏 / 导入器版本
```

## 12.2 核心 UI 设计原则

- 每个指标卡展示**数值 + 样本数 + 方向 + 数据来源**；不画没有统计依据的华丽雷达图。
- 错误完成以醒目的失败类别显示；`UNKNOWN/ERROR` 使用独立视觉语义，不与 FAIL 混淆。
- 默认显示**基线/候选成对用例表**，支持按“退化、改善、未知、无证据”筛选。
- Trace 采取树形列表/时间线 + 右侧节点详情；点击失败规则可高亮关联事件。
- 所有加载/空列表/错误/导入部分失败场景有文案和操作入口。
- 重要页支持键盘访问与响应式；桌面 1280px 宽可完成主要流程，不设计仅适用于超宽屏的面板。
- 不让前端直接请求外部模型或保存 API Key。

## 12.3 第一个完整用户旅程

1. 进入 Demo 项目 `ZM Reliability Demo`。
2. 导入 `fixtures/zmai/baseline.jsonl` 和 `candidate.jsonl`，确认快照未变。
3. 点击 `Evaluate`，触发确定性规则，查看 Run 和用例详情。
4. 在 Comparisons 选择两个 Run，看到退化和改善案例。
5. 点击一个 `completion_without_verification`，跳到对应文件修改/终止节点。
6. 生成 Markdown 报告；本地 CLI 对同一个 Comparison Gate 返回正确退出码。

**验收**：不是静态截图，不以硬编码图表冒充实时数据。

---

# 13. CLI / SDK 与 CI 约定

## 13.1 CLI 命名与拟支持命令

> 以下为未来 CLI 设计规范，**项目未完成前不能直接执行**。

```bash
zmeval import --source zmai-jsonl --file fixtures/zmai/baseline.jsonl --project demo
zmeval import --source zmwiki-jsonl --file fixtures/zmwiki/sample.jsonl --project demo
zmeval evaluate --run <run-id> --rules config/rules/agent-reliability.yaml
zmeval compare --baseline <run-id> --candidate <run-id> --output reports/compare.md
zmeval gate --comparison <comparison-id> --policy config/gates/default.yaml
zmeval reconcile --dry-run
```

CLI 调用**同一领域包**或 API，不能另造一个独立评分实现。核心命令可配置 API URL / 本地模式，P0 先只实现服务端 API 方式。

## 13.2 GitHub Actions（P1 模板）

- CI 分为**离线规则测试**和**授权的真实模型评测**两套 Workflow。
- PR 上只跑免费、确定性、短耗时的 fixture/单元/API/前端测试。
- 真实 Agent Benchmark、Ragas Judge 与付费 API **不随 PR 自动触发**；手工 `workflow_dispatch` + 预算批准。
- CI 运行 `zmeval gate`，用退出码阻断质量退化；发布报告仅上传脱敏工件。
- 第三方 PR 不应拿到模型密钥或部署密钥。

---

# 14. 工程目录（目标状态，按阶段创建）

```text
ZMEvalHub/
├── README.md
├── LICENSE
├── NOTICE                         # 若实际依赖/复用需要
├── .gitignore
├── .env.example                   # 仅非敏感示例
├── .python-version
├── .node-version
├── .github/
│   └── workflows/
│       ├── test.yml
│       └── real-eval-manual.yml    # P1，默认不触发付费评测
├── apps/
│   ├── api/                        # FastAPI 入口（共用核心 Python 包）
│   │   └── main.py
│   └── web/                        # Vue3 + TS + Vite
│       ├── package.json
│       ├── pnpm-lock.yaml
│       ├── src/
│       │   ├── api/
│       │   ├── router/
│       │   ├── stores/
│       │   ├── components/
│       │   ├── views/
│       │   │   ├── OverviewView.vue
│       │   │   ├── DatasetsView.vue
│       │   │   ├── RunsView.vue
│       │   │   ├── RunDetailView.vue
│       │   │   └── ComparisonsView.vue
│       │   └── main.ts
│       └── vite.config.ts
├── src/
│   └── zmevalhub/
│       ├── __init__.py
│       ├── api/                    # routers / request schemas / error handlers
│       ├── domain/                 # project, dataset, run, comparison, gate
│       ├── db/                     # SQLAlchemy models / sessions
│       ├── schemas/                # Pydantic v2 公共契约
│       ├── importers/              # zmai / zmwiki / promptfoo(P1) / otel(P1)
│       ├── evaluation/
│       │   ├── rules/              # 可靠性规则
│       │   ├── ragas_adapter.py    # P1 optional extra
│       │   ├── aggregator.py
│       │   └── evidence.py
│       ├── workers/                # RQ jobs / enqueue / reconcile
│       ├── reporting/              # markdown / gate summary
│       ├── cli/                    # zmeval entrypoint
│       └── config/
├── alembic/
│   ├── env.py
│   └── versions/
├── config/
│   ├── rules/agent-reliability.yaml
│   └── gates/default.yaml
├── fixtures/
│   ├── zmai/
│   ├── zmwiki/
│   ├── promptfoo/                 # P1
│   └── invalid/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── contracts/
│   └── e2e/
├── deploy/
│   ├── compose.yaml
│   ├── Dockerfile.api
│   └── Dockerfile.web
├── docs/
│   ├── 00_ENGINEERING_BLUEPRINT.md
│   ├── ARCHITECTURE.md
│   ├── DATA_CONTRACT.md
│   ├── METRIC_DEFINITIONS.md
│   ├── EVALUATION_PROTOCOL.md
│   ├── SECURITY.md
│   ├── QUICKSTART.md
│   ├── THIRD_PARTY.md
│   ├── DEVELOPMENT_STATUS.md
│   ├── ADR/
│   └── schema/v1.json
├── pyproject.toml
└── uv.lock
```

`apps/api/main.py` 仅作为入口；业务逻辑集中在 `src/zmevalhub`，减少 web/CLI/Worker 多处复制。**不要 P0 一次性空建所有目录**，每完成一阶段增量创建必要结构。

---

# 15. 逐阶段开发与验收路线

> 时间仅供单人排期参考，**先验收后进入下一阶段**。不要因日期到期跳过真实闭环，也不要写“V1.0 已生产可用”而没有部署与回归证据。

## P0.0 — 技术与契约 Spike（预计 2–3 天）

**目标**：证明确实不必重造底层轮子。

任务：

- [ ] 建新仓库、README、本文档、LICENSE 草案。
- [ ] 核验 Python/Ragas/RQ/PostgreSQL/Node 兼容，固定 `uv.lock` 和 `pnpm-lock.yaml`。
- [ ] 选取 ZMAI 和 ZMWiki **已有** 2–3 条可公开、脱敏、真实运行样本。
- [ ] 把其中一条规范化为 `schema_version=1` 并通过 Pydantic 校验。
- [ ] 跑通一条 Ragas 官方示例评测（**可跳过付费模型，标为 P1 候选**）。
- [ ] 确定一条实际 Promptfoo JSON 版本样本（非 P0 强制集成）。
- [ ] 编写 `ADR-001: modular-monolith`、`ADR-002: immutable-snapshots`、`ADR-003: offline-first`。

**Done**：一条真实上游结果可以变成合法标准对象；依赖安装可复现；没有预先造模型 SDK 或 Judge 算法。

## P0.1 — 数据资产与导入（预计 3–5 天）

任务：

- [ ] SQLAlchemy 模型、首版 Alembic 迁移、Project/Dataset/Snapshot/Case API。
- [ ] JSONL 规范导入 + CSV 最小子集；明确不承诺 Excel/YAML 全格式支持。
- [ ] `zmai-jsonl` 和 `zmwiki-jsonl` 适配器（只读转换）。
- [ ] Snapshot fingerprint、源 Run 幂等键、导入校验报告。
- [ ] 两组正例和五类异常 fixture：字段缺失、无效类型、重复 case、损坏 JSON、敏感字段。
- [ ] Vue 数据集页面，可视化查看导入结果和错误原因。

**Done**：相同文件导入两次不产生重复 Run/Case；历史快照不可修改；错误行可定位。

## P0.2 — 规则引擎与证据链（预计 4–6 天）

任务：

- [ ] 统一 EvalRun、EvalAttempt、TraceEvent、EvidenceRef、ScoreRecord。
- [ ] Redis + RQ Worker；异步状态、幂等、错误与超时路径。
- [ ] 首批规则 `ZM-R001`～`ZM-R006`，带规则版本。
- [ ] RAG `evidence_recall` 的确定性评分、缺失证据处理。
- [ ] Run / Attempt / Trace / 规则详情页。
- [ ] 任务中断、重复执行和无有效证据测试。

**Done**：在真实/固定 fixtures 上能准确展示：一条可证实失败、一条可证实成功、一条证据不足 UNKNOWN；不调用外部模型。

## P0.3 — 版本对比、Gate 和产品闭环（预计 4–6 天）

任务：

- [ ] 相同快照的两版本成对比较；不兼容差异明确拒绝。
- [ ] 对比结果按改善、退化、不变、未知显示。
- [ ] Gate 策略版本和退出码语义；CLI 基础命令。
- [ ] Markdown 报告含数据来源、评分器版本、样本数、失败证据链接。
- [ ] Vue Compare/Overview 页面，关键交互 E2E。
- [ ] Docker Compose 开箱启动、离线演示数据导入脚本。

**Done**：新机器按 QUICKSTART 运行，实现 **导入 → 评分 → 定位 → 对比 → Gate → 报告**；不依赖付费 Token。

## P0.4 — 开源 MVP 验收（预计 2–3 天）

- [ ] README：产品截图/GIF、自定义结果导入示例、约束与已实现列表。
- [ ] 核心单元/集成/契约/Smoke 测试全部通过。
- [ ] 对照开源依赖许可证、匿名化样本、密钥安全、依赖锁定。
- [ ] Windows PowerShell 与 Linux 至少各验证一条安装路径（无法覆盖的平台明确标注）。
- [ ] release `v0.1.0`，附真实测试命令、统计和未实现事项。

**版本命名建议**：`v0.1.0` 为可运行、可演示、具证据的 MVP，**不是生产系统承诺**。

## P1 — 兼容性和深度评测（仅 P0 通过后）

- [ ] Ragas `extra` 与官方实例接入，测试真实评分结果和失败降级。
- [ ] Promptfoo JSON 真实结果导入，版本兼容矩阵。
- [ ] OTel/OpenInference 文件导入与追踪 Span 层级展示。
- [ ] 可选主动 Prompt/RAG 运行器（白名单配置），Judge 预算控制。
- [ ] 完整 CLI/SDK 与 GitHub Actions Gate 模板。
- [ ] 多次运行的均值/方差与稳定性统计（只在样本有效时展示）。

**P1 验收**：至少 1 个不属于 ZMAI/ZMWiki 的公开开源样例能接入、跑通并出可解释报告；报告声明外部指标来源，不伪装自己的算法创新。

## P2 — 条件性扩展

只有当实际用户需求、稳定性瓶颈或外部贡献证明必要时，再考虑：多租户、登录 RBAC、在线遥测采集、Harbor/Inspect AI 深度集成、大规模队列、长期趋势管理、独立 Java API 网关。

---

# 16. 本地启动方案（实现后的标准命令）

## 16.1 前置环境

- Python 3.12（P0 Spike 确认）+ `uv`。
- Node.js 维护中的 LTS 版本 + `pnpm`（P0 锁定版本）。
- Docker Desktop / Docker Engine + Compose v2。
- 本机可用端口：Web `5173`、API `8000`；数据库/Redis 默认仅容器内部访问或回环映射。

## 16.2 开发启动（目标接口，不代表文件已存在）

```bash
# 1. 克隆项目（将占位地址替换为真实 GitHub 仓库）
git clone https://github.com/<YOUR_ACCOUNT>/ZMEvalHub.git
cd ZMEvalHub

# 2. 填写本地环境（仅开发机）
cp .env.example .env

# 3. 启动 DB/Redis
docker compose -f deploy/compose.yaml up -d db redis

# 4. Python 依赖与迁移
uv sync
uv run alembic upgrade head

# 5. 开两个终端分别启动 API 和 Worker
uv run uvicorn apps.api.main:app --reload --host 127.0.0.1 --port 8000
uv run rq worker zmevalhub-eval --url redis://localhost:6379/0

# 6. 第三个终端启动前端
cd apps/web
pnpm install --frozen-lockfile
pnpm dev
```

> Windows PowerShell 的环境文件复制使用 `Copy-Item .env.example .env`；如容器内服务名、端口映射与上面不同，必须在 P0 统一 README/Compose/脚本，不能仅靠手动改示例命令运行。

## 16.3 一键演示（P0.3 交付）

```bash
docker compose -f deploy/compose.yaml up -d --build
# 通过文档提供的 demo seed/CLI 导入示例数据
# 打开 http://localhost:5173
```

Docker Compose 必须包含：明确健康检查、数据 Volume、可选示例初始化、回环绑定、固定服务名。禁止把 `.env` 或真 API Key 打进镜像、提交到 GitHub。

## 16.4 无模型 Token Demo

- 评测输入使用仓库中经过脱敏的真实历史运行结果 + 合成边界用例。
- 所有评分通过确定性规则完成；`JUDGE_ENABLED=false`。
- README 展示**一个能改善的版本对**及一个**故意退化的版本对**，同时说明这些 fixture 的来源和局限。
- 此模式无模型 API 费用；Docker、运行机器等本地资源不等于零成本。

---

# 17. 测试矩阵与质量验收

## 17.1 必需测试

| 测试类别 | 最小覆盖 | 验收重点 |
|---|---|---|
| 单元 | Rule、Score、Aggregation、Gate、Fingerprint | 无日志/缺字段/错误退出码/不同规则版本 |
| 契约 | Pydantic Schema、API、Importers | JSONL 损坏、版本不兼容、必填字段、兼容提示 |
| DB 集成 | PostgreSQL+Alembic | 快照不可变、事务失败回滚、幂等约束、唯一键 |
| Worker 集成 | Redis+RQ | 重复投递、崩溃恢复、超时、部分成功、取消路径 |
| 端到端 | API + Vue + Worker | 导入→评测→对比→查看证据→报告/门禁 |
| 安全 | 上传、路径、日志、模型密钥 | 路径穿越、超大上传、敏感字段、外部 URL 限制 |
| 非回归 | ZMAI/ZMWiki Fixture | 固定规则对同一输入输出可复现 |

## 17.2 P0 必须有的五组样本

1. **真实正例**：验证存在、被测系统声称完成且独立证据满足规则。
2. **真实失败**：测试失败后仍声称完成，规则准确命中。
3. **修改后未验证**：完整日志中修改发生在最后一次通过验证之后。
4. **证据不足**：日志被截断或缺退出码，输出 UNKNOWN 而非 FAIL。
5. **RAG 多跳样例**：Gold Evidence IDs 与检索命中集合可核对，evidence recall 可复算。

如现有真实日志不包含对应场景，**明确标为合成 fixture**；不能把合成场景充当真实 SWE-bench 通过率。

## 17.3 发布定量标准（工程验收目标，不是目前成果）

- 固定 fixtures 的预期规则判定 **100% 一致**，包括 PASS/FAIL/UNKNOWN/ERROR。
- 快照一致性、重复导入幂等、规则版本冻结有自动化测试。
- 用户在干净环境一次运行 Demo 链路，不借助手动改库。
- 同一个 Comparison 在固定数据与规则版本下重复生成报告，**指标一致**（时间、ID 等非确定性元数据可不同）。
- 外部模型请求默认 **0 次**；真实付费评测必须显式开关且有预算。
- API/Worker 异常时不应静默返回 PASS；失败和未知覆盖率准确显示。
- 若引入性能目标，必须给出设备、数据规模、P50/P95、测试命令和采样方法，禁止空写“支持高并发”。

## 17.4 DoD（Definition of Done）

每一个功能完成至少满足：**用户场景能操作、数据真实可追溯、有自动化测试、异常/缺证据有正确语义、README/变更日志同步**。功能未验收不得在 README 写为“已支持”。

---

# 18. 安全、隐私和成本控制

## 18.1 Threat Model（MVP 必须处理）

| 风险 | 对策 |
|---|---|
| 未授权公网访问 | P0 默认 localhost；远程服务必须先实现认证/TLS |
| Trace/Prompt 泄露密钥与个人信息 | 导入时脱敏；默认不展示完整原始内容；控制文件访问 |
| 恶意 JSON/CSV/文件路径 | 输入大小/类型限制、路径归一化、禁止目录穿越、CSV 公式注入导出防护 |
| 外部模型调用 SSRF | P0 禁止动态 URL Provider；后续严格允许列表与网络隔离 |
| 文件/命令执行 | 不从平台 Web 接受任意 shell/python；外部 Agent 执行在隔离 Runner 中 |
| 提示词注入评分器 | 数据与评分指令分离；将外部文本视为证据内容，拒绝注入行为 |
| 任务重试重复扣费 | 幂等键、预算上限、外部请求确认、保守重试 |
| 导入文件中隐藏敏感信息 | 仓库只提交去标识化 fixture；发布前对原始数据做人工审计 |

## 18.2 环境变量与密钥

- `.env.example` 只放占位键名（如 `DATABASE_URL`、`REDIS_URL`、`JUDGE_ENABLED=false`）。
- `.env`、API Token、数据库密码、真实 Trace 原文存储都在 `.gitignore` 控制范围内。
- 模型 Key P0 从进程环境读取，不用 `model_config.api_key` 明文字段。
- 服务器日志默认脱敏 Authorization、Cookie、Key、完整 Prompt/上传文件体。

## 18.3 Token 费用保护

- 默认离线：确定性规则 + 已有运行结果，**无需任何第三方模型**。
- Judge 模式才选择模型、并发、最大调用数、超时、预算；拒绝配置不足的批量任务。
- 建立 `cost_estimated` / `cost_reported` 两种来源；没有价格映射时只显示 token，不伪造人民币费用。
- 高费用操作不能在普通 PR CI 自动执行；计划中的 Benchmark 都由用户在本地明确发起。

---

# 19. 研发协作与 Codex 省额度准则

适用于后续按此文档逐阶段用 Codex 开发：

1. **单轮只做一个可验收的最小任务**，先阅读相关文件再修改，禁止大范围重构。
2. 提示词清楚、无歧义、可验证；超出边界的复杂条件优先放在**运行时守卫/规则**中，不堆提示词。
3. Codex 可以增量修改代码、补小型单元测试、跑静态检查/短耗时目标测试；**不主动运行全量 pytest、长耗时 E2E、SWE-bench、真实付费模型调用**。
4. 不自动接入高成本模型；若依赖评测真实模型，先输出本地运行命令，由使用者决定运行。
5. 每轮交付必须总结：修改文件、对应需求/规则编号、关键实现、只跑了哪些验证、未执行的高成本测试。
6. 失败优先最小回滚；不引入“为了防御未来不明问题”的抽象层。
7. Git 提交遵守 Conventional Commits；**不要写 `Co-Authored-By` 自动署名尾注**。
8. 所有宣称成绩必须附：数据集、样本数、时间、版本、是否真实模型、命令、日志路径及计算方法。

### 推荐任务提示词模板（可复制）

```text
目标：实施 ZMEvalHub 工程总纲的 [阶段/功能编号]。
本轮只完成：[单一明确任务]。
必须满足：[输入/输出/约束/失败语义/验收条件]。
允许修改：[目录/文件范围]。禁止无关重构和新增非必要依赖。
复用现有成熟库；不要自研已有执行器、评分算法、队列或通信协议。
只运行必要的短耗时定向测试/静态检查；不自动执行全量测试、SWE-bench、E2E 或付费模型调用。
输出：变更文件、关键设计、验证命令与结果、剩余风险；失败即最小回滚。
不得附加 Co-Authored-By 尾注。
```

---

# 20. 依赖、风险、假设与决策记录

## 20.1 关键风险及应对

| 风险 | 严重性 | 应对 |
|---|---|---|
| 只是重复 Opik/Foo 平台 | 高 | 将规则证据链与同集回归做成可验证主线；明确价值边界 |
| 用新平台重造所有 Benchmark | 高 | 外部 Harness 负责运行，ZMEvalHub 消费结果 |
| 没有可追溯真实数据 | 高 | 在 P0.0 先核实 2–3 条可发布样本，否则不可继续宣称真实接入 |
| Agent Trace 不完整 | 高 | UNKNOWN 和 completeness 标记；禁止乱给 0 分 |
| 评测规则口径漂移 | 高 | `rule_version` + `metric_version` + Snapshot/Hash |
| 外部 Judge 不稳定/成本高 | 中高 | 默认关；同模型配置复评、预算门禁、报告标明来源 |
| Ragas/Promptfoo API 变化 | 中 | Adapter + 版本锁文件 + 合同 fixture |
| Redis 与 DB 状态不一致 | 中 | DB 为准；RQ 对账和重投机制 |
| 一个人范围失控 | 高 | P0 只做离线可复现闭环；P1/P2 受需求驱动 |
| 开源许可与隐私问题 | 高 | 第三方清单、合规和 fixture 脱敏审核 |

## 20.2 架构决策记录（ADR）初始集

- `ADR-001`: Modular Monolith + RQ Worker，暂不跨语言微服务。
- `ADR-002`: Immutable DatasetSnapshot、RuleSetVersion、EvalRun；历史结果只增不覆盖。
- `ADR-003`: Offline-first，确定性规则先于 Judge。
- `ADR-004`: Adapter 边界；上游结果永远保留来源与转换版本。
- `ADR-005`: PostgreSQL 为权威；Redis 仅队列。
- `ADR-006`: OTel/OpenInference 适配优先，不造新遥测协议。
- `ADR-007`: Local-only 默认安全，远程部署后置。

## 20.3 待阶段 0 验证（禁止凭经验假定）

- ZMAI 最新导出/日志中**是否真的能得到验证 Exit Code、文件编辑事件和完整性标志**；缺失时具体如何标 UNKNOWN。
- ZMWiki 真实 JSONL 包含的 Evidence ID 和不可回答标记是否足以复算历史指标。
- Ragas 当前版本对 Python 3.12、Judge 适配、离线环境的实际兼容性。
- Promptfoo 实测输出 JSON 的稳定字段及是否含可能泄露敏感信息的内容。
- RQ Worker 在 Windows 原生环境的支持限制：**若不满足，规定开发 Worker 使用 Docker/WSL2**，不能在 README 假装跨平台原生可运行。
- 围绕固定实际数据集，P0.2 是否需要补充数据完整性标志和验证范围判定。

---

# 21. 仓库启动清单和首轮任务

## 21.1 创建仓库时必须放入的最少文件

```text
README.md
LICENSE
.gitignore
.env.example
pyproject.toml
src/zmevalhub/__init__.py
docs/00_ENGINEERING_BLUEPRINT.md
fixtures/README.md
tests/README.md
```

**其他目录分阶段实际使用时创建**，不要空建大型脚手架制造进度假象。

## 21.2 第一轮具体任务（不调用付费模型）

1. 创建 `ZMEvalHub` 空仓库和基础项目配置；写 README 的“目标/非目标/未实现”部分。
2. 阅读现有 ZMAI、ZMWiki 本地评测结果，只做**只读字段映射表**。
3. 定义 Pydantic `SourceRunV1`、`CaseV1`、`AttemptV1`、`EventV1`，并生成 JSON Schema。
4. 编写 2 份真实/脱敏 fixture + 2 份合成反例，并确保它们被准确标注来源。
5. 用 pytest 验证 Schema 的合法与非法输入；**本轮不搭前端、数据库、队列**。

**首轮 Done**：给一条真实样本，命令行能校验并打印规范对象；给坏样本，错误含定位信息。这是最小、可验证的项目起点。

## 21.3 不应过早开始的工作

- 没有真实数据契约前不要先画 Dashboard；没有 Snapshot 不要做版本对比；没有证据完整性标记不要做错误完成率；没有预算门禁不要接付费 Judge；没有单机闭环不要上多租户/分布式服务。

---

# 22. 开源发布与简历价值验收

## 22.1 Release 准备

- `README`：定位图、1 分钟演示、支持矩阵、局限、快速开始、API 文档入口。
- `docs`：Schema、评分定义、架构、ADR、第三方许可、安全说明、开发状态。
- `fixtures`：一组可公开的真实结果 + 一组明确标注的合成边界样本。
- `tests`：离线契约、规则、对比、Gate、数据库/队列集成测试；发布附通过记录。
- `release notes`：明确 P0/P1 已实现与未实现项目，不用“全自动生产级”营销语。

## 22.2 可核验成果（完成后才填写）

| 成果维度 | 应提供的证据 |
|---|---|
| 兼容性 | 至少 ZMAI、ZMWiki 两种真实结果格式，版本化 importer 与 fixture |
| 可靠性 | 规则正反边界样本、UNKNOWN 保守判定、误判回归测试 |
| 可复现性 | 同快照同规则版本的重复报告、Hash / Git SHA |
| 工程完整性 | 一键部署、DB 迁移、Worker 重试、前端交互、CI Gate |
| 跨框架价值 | P1 第三方开源 Agent / Promptfoo / OTel 真实接入案例 |
| 量化成果 | 只公布实测成功/失败数、样本大小、速度与成本；不预设“提升 XX%” |

### 简历项目标题候选（项目上线后）

**ZMEvalHub — 面向 RAG / Coding Agent 的可靠性评测与回归分析中台**。项目卖点应是：统一结果导入、不可变测试集、可靠性规则、Trace 证据归因、同集版本对比、CI 质量闸门。**不要拿 UI 面板数量、代码行数代替工程效果。**

---

# 附录 A：与原 v1.0 工程文档的差异

| 原稿设计 | v2.0 决策 | 理由 |
|---|---|---|
| 企业协作 + RAG/Prompt/Agent/基准全做 | Agent 可靠性优先，RAG/Prompt 通过适配扩展 | 聚焦差异化，避免一个人做全功能平台 |
| Java Spring Boot 中台 + Python 评测微服务 | Python 模块化单体 + RQ Worker | 降低启动和长期维护成本 |
| Promptfoo 被称为“纯 CLI” | 明确其带 Web Viewer，作为成熟执行器/导入来源 | 与实际开源能力保持一致 |
| Redis + 线程池自研队列 | Redis + RQ | 不重复实现可靠后台任务机制 |
| MySQL + Chroma→Milvus + 本地→MinIO | PostgreSQL + Redis + 受控文件目录 | 去掉无真实需求的基础设施 |
| 先模型 Provider 全适配 | 离线结果优先；外部 Provider 复用工具 | 降低成本和抽象重复 |
| 基础状态只有 SUCCESS/FAILED | 区分平台 Run 状态、Subject Outcome、Rule Verdict | 防止把“跑完了”误作“修好了” |
| 只按 `dataset.version` 保存版本 | 内容 Hash 的不可变 Snapshot | 保证 A/B 比较可追溯 |
| “幻觉率/步骤合理性”直接自动统计 | 有可验证条件才评分，其余 UNKNOWN | 避免无真值的指标伪精确 |
| 12 周直接宣称生产 V1/V2 | P0 可用验证；P1/P2 受真实需求约束 | 阶段验收比时间承诺重要 |
| 默认用户权限/RBAC、多模型、分布式 | 后置；先单机只回环访问 | 尽快完成真实可用闭环 |

---

# 附录 B：上游参考文档与核验入口

> 以下链接用于**实现时确认准确 API、接口、许可证与使用方法**；本文不复制其源代码，也不保证未来版本与当前完全一致。核验日期：2026-11-11。

- **Opik**：https://github.com/comet-ml/opik
- **Langfuse**：https://github.com/langfuse/langfuse
- **Arize Phoenix**：https://github.com/Arize-ai/phoenix
- **Promptfoo**：https://github.com/promptfoo/promptfoo
- **Promptfoo 结果格式**：https://github.com/promptfoo/promptfoo/blob/main/site/docs/configuration/outputs.md
- **Ragas**：https://github.com/vibrantlabsai/ragas
- **Ragas 数据集规范**：https://github.com/vibrantlabsai/ragas/blob/main/docs/concepts/components/eval_dataset.md
- **DeepEval**：https://github.com/confident-ai/deepeval
- **Inspect AI**：https://github.com/UKGovernmentBEIS/inspect_ai
- **Harbor**：https://github.com/harbor-framework/harbor
- **OpenCompass**：https://github.com/open-compass/opencompass
- **RQ（Redis Queue）**：https://python-rq.org/
- **OpenTelemetry 语义规范**：https://opentelemetry.io/docs/concepts/semantic-conventions/
- **OpenTelemetry GenAI 约定（持续演进）**：https://github.com/open-telemetry/semantic-conventions-genai

---

# 附录 C：给下一轮开发的执行入口

**当前唯一推荐起点：P0.0 → P0.1，优先完成数据契约，暂不构建完整 UI。**

完成第一个明确可验收的转换器后，再执行规则评分；完成规则证据后，再做对比看板。整个项目必须始终保持“**可以用已有真实执行结果做离线演示**”的能力，不应因为付费 API 暂时不可用而瘫痪。

> **项目成功标准**：一个不了解 ZMAI 的开发者，能把自己的 Agent 运行结果按公开契约导入 ZMEvalHub，看到**可信评分、失败证据和可复现的版本回归报告**。如果做不到这一点，就还不是一个有外部价值的评测中台。
