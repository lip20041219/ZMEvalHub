# ZMEvalHub — AI 应用评测中台 工程启动文档

> 面向 RAG / Agent / Prompt 开发者的一站式评测中台，覆盖用例管理、多维度评测、版本对比、回归测试与质量可视化，打造 AI 应用的质量保障平台。
>
> 项目代号：ZMEvalHub（zm 前缀，与 ZMAI、ZMWiki 项目体系统一）
> 文档版本：v1.0
> 文档性质：初始启动制作大纲（架构设计 + 模块划分 + 技术选型 + 分阶段执行计划）

---

## 目录

- [一、项目概述](#一项目概述)
- [二、核心借鉴开源项目说明](#二核心借鉴开源项目说明)
- [三、整体架构设计](#三整体架构设计)
- [四、技术栈选型](#四技术栈选型)
- [五、核心模块设计](#五核心模块设计)
- [六、数据库表结构设计](#六数据库表结构设计)
- [七、接口设计规范](#七接口设计规范)
- [八、项目初始目录结构](#八项目初始目录结构)
- [九、分阶段开发执行大纲](#九分阶段开发执行大纲)
- [十、本地开发环境启动指南](#十本地开发环境启动指南)
- [十一、开发规范](#十一开发规范)
- [十二、风险与避坑指南](#十二风险与避坑指南)
- [十三、开源运营初步规划](#十三开源运营初步规划)

---

## 一、项目概述

### 1.1 项目定位

ZMEvalHub 是一款开源的 AI 应用评测中台，聚焦大语言模型应用层质量评估，为 RAG 问答系统、智能 Agent、Prompt 工程提供标准化、可复用、可协作的评测解决方案。项目采用「业务中台 + 评测引擎」双栈架构，兼顾企业级协作管理与专业评测能力，支持私有化部署与生态扩展。

### 1.2 核心能力

- **多场景评测**：覆盖 RAG 质量评测、Prompt 效果对比、Agent 链路评测、大模型基准跑分。
- **用例资产管理**：可视化管理评测数据集，支持 YAML / CSV / Excel 批量导入导出，兼容主流评测工具格式。
- **多模型适配**：开箱支持主流商用大模型、开源本地模型，插件化扩展新模型。
- **多版本对比**：支持不同模型、Prompt 版本、应用版本的横向得分对比，高亮劣化用例。
- **全链路追踪**：对接 RAG / Agent 执行链路，实现「得分 → 节点 → 根因」的问题定位。
- **CI/CD 集成**：提供 API 与 CLI 工具，支持接入开发流水线做自动化回归测试。

### 1.3 适用场景

- RAG 系统开发中的检索效果与回答质量迭代。
- Prompt 工程师的多版本 Prompt 效果对比与回归。
- AI Agent 的工具调用、任务规划能力评测。
- 团队协作的评测资产沉淀与质量基线管理。
- 企业私有化 AI 应用的质量保障与合规校验。

### 1.4 差异化优势

1. **中台化协作**：不止于评测工具库，提供完整的项目管理、用户权限、资产沉淀能力，适配团队协作场景。
2. **全生态闭环**：原生支持对接 Prompt 管理平台、RAG 系统、Agent 框架，覆盖 AI 应用开发全流程。
3. **中文场景优化**：针对中文语料优化评判逻辑与数据集，填补主流评测框架的中文短板。
4. **轻量化部署**：Docker Compose 一键启动，低资源占用，适配中小团队与个人开发者。

### 1.5 与现有项目的关系

| 现有项目 | 在 ZMEvalHub 闭环中的角色 |
|---|---|
| ZMAI（Agent 应用） | 作为被评测对象，接入 Agent 链路追踪与任务完成度评测 |
| ZMWiki（RAG 系统） | 作为被评测对象，拉取检索链路数据做端到端 RAG 质量评测 |
| Prompt 管理与版本控制平台（毕设） | 与评测中台双向打通：选择 Prompt 版本发起评测，评测结果反向关联版本 |

---

## 二、核心借鉴开源项目说明

本项目基于业界成熟开源项目做架构与能力参考，聚焦中台层产品化创新，不重复造底层评测轮子。整体策略为「2 个核心主借鉴 + 3 个辅助分模块借鉴」。

### 2.1 核心主借鉴项目

| 项目仓库 | 项目定位 | 核心借鉴内容 | 落地区域 |
|---|---|---|---|
| [promptfoo/promptfoo](https://github.com/promptfoo/promptfoo) | Prompt / RAG 评测 CLI 工具 | 1. YAML 声明式评测用例规范<br>2. 多模型 Provider 插件化抽象层<br>3. 内置断言规则引擎设计<br>4. 多版本输出对比交互逻辑<br>5. CI/CD 集成接口设计 | 用例管理模块、模型适配层、断言引擎、前端结果对比页 |
| [explodinggradients/ragas](https://github.com/explodinggradients/ragas) | RAG 评测算法库 | 1. 四大核心 RAG 评测指标体系<br>2. LLM-as-Judge 工程化实现<br>3. 无监督评测方法论<br>4. 打分归一化与鲁棒性处理 | Python 评测引擎层、RAG 评测核心能力 |

### 2.2 辅助分模块借鉴项目

| 项目仓库 | 项目定位 | 核心借鉴内容 | 落地区域 |
|---|---|---|---|
| [confident-ai/deepeval](https://github.com/confident-ai/deepeval) | LLM 应用测试框架 | 类 pytest 代码式用例 API、测试套件组织方式 | Python SDK、单元测试集成能力 |
| [Arize-ai/phoenix](https://github.com/Arize-ai/phoenix) | AI 可观测性平台 | RAG / Agent 全链路 Trace 埋点规范、检索质量可视化、根因定位逻辑 | Agent 评测模块、链路追踪功能 |
| [open-compass/opencompass](https://github.com/open-compass/opencompass) | 大模型基准评测体系 | 评测任务分片并行调度、多维度榜单生成、标准化结果输出 | 分布式任务调度、模型排行榜、批量报告 |

### 2.3 组合借鉴的核心逻辑

之所以不直接照搬单个项目，原因如下：

- Promptfoo 是纯 CLI 工具，缺少中台化的项目管理、团队协作、资产沉淀能力。
- RAGAS 是纯算法库，没有产品界面和业务流程。
- OpenCompass 偏重基础模型基准跑分，不适合 RAG / Agent 应用级评测。

最终方案取各家所长：用 Promptfoo 做产品骨架，用 RAGAS 做评测内核，用另外三个项目补充分模块能力，聚焦「中台化、团队协作、与 Prompt / RAG / Agent 生态打通」的差异化价值。

### 2.4 借鉴边界（不重复造轮子）

- 核心评测指标直接复用 RAGAS 官方库，仅做业务封装、参数配置化、结果标准化，不修改核心算法。
- 模型调用能力复用各模型官方 SDK 与 Spring AI / LangChain 生态，不自研通信协议。
- 底层存储、队列、向量库直接使用成熟开源组件，不自研基础设施。

---

## 三、整体架构设计

### 3.1 架构总览

采用分层解耦的微服务架构，评测引擎与业务中台独立部署，支持横向扩展。

```
┌───────────────────────────────────────────────────────────┐
│ 接入层 Access Layer                                        │
│  Web 控制台  │  CLI 命令行  │  REST API  │  Python SDK     │
├───────────────────────────────────────────────────────────┤
│ 业务中台层 Business Layer (Java / Spring Boot)             │
│ ┌─────────┬─────────┬─────────┬─────────┬─────────┐      │
│ │项目管理 │用例管理 │任务调度 │结果管理 │系统管理 │      │
│ └─────────┴─────────┴─────────┴─────────┴─────────┘      │
├───────────────────────────────────────────────────────────┤
│ 评测引擎层 Evaluation Layer (Python / FastAPI)             │
│ ┌─────────┬─────────┬─────────┬─────────┬─────────┐      │
│ │RAG评测  │Agent评测│断言引擎 │模型适配 │指标插件 │      │
│ └─────────┴─────────┴─────────┴─────────┴─────────┘      │
├───────────────────────────────────────────────────────────┤
│ 基础设施层 Infrastructure Layer                           │
│   MySQL 8.0   │   Redis   │  向量数据库  │  对象存储      │
└───────────────────────────────────────────────────────────┘
```

### 3.2 分层职责说明

1. **接入层**：面向用户与外部系统的交互入口，提供可视化控制台、命令行工具、开放 API 与开发者 SDK。
2. **业务中台层**：负责核心业务逻辑与数据管理，包含项目、用例、任务、结果、用户权限等中台能力。
3. **评测引擎层**：专职执行评测计算，封装所有评测算法、模型调用与指标计算，独立扩容与升级。
4. **基础设施层**：提供数据存储、缓存、队列、文件存储等基础支撑能力。

### 3.3 核心设计原则

1. **评测与业务分离**：评测引擎独立成服务，不和业务逻辑耦合，方便横向扩容与版本升级。
2. **全插件化扩展**：模型、数据集、评测指标、断言规则全部支持插件式扩展。
3. **标准化数据格式**：统一评测输入输出规范，方便对接第三方系统。
4. **轻量化起步**：MVP 阶段裁剪非核心组件，优先跑通核心评测闭环。

### 3.4 双栈通信约定

- Java 业务中台与 Python 评测引擎通过 REST API + JSON 通信，避免引入复杂 RPC 依赖；后期视规模可升级为 gRPC。
- 评测引擎无状态化，任务上下文由业务中台下发，执行结果统一回传。
- 通信异常采用重试 + 降级兜底，任务状态在业务中台侧持久化，引擎重启不丢任务。

---

## 四、技术栈选型

| 层级 | 技术选型 | 选型说明 |
|---|---|---|
| 前端控制台 | Vue 3 + Vite + Element Plus + ECharts | 主流前端技术栈，组件生态成熟，满足可视化图表与后台管理需求 |
| 业务中台后端 | Java 17 + Spring Boot 3 + Spring AI + MyBatis-Plus | 复用 Java 生态企业级开发能力，Spring AI 简化大模型对接 |
| 评测引擎服务 | Python 3.11 + FastAPI + RAGAS + LangChain | Python 原生适配 AI 评测生态，FastAPI 高性能异步接口 |
| 关系型数据库 | MySQL 8.0 | 存储业务元数据、用户、项目、用例、任务、评测结果等结构化数据 |
| 缓存与队列 | Redis 7.x | 热点数据缓存、异步评测任务队列、分布式锁 |
| 向量数据库 | Chroma（MVP）→ Milvus（正式版） | 语义相似度计算、嵌入质量评测，MVP 阶段轻量化部署 |
| 文件存储 | 本地存储（MVP）→ MinIO | 存放评测数据集、报告文件、Trace 日志 |
| 部署方式 | Docker + Docker Compose → Kubernetes Helm | 提供一键部署脚本，降低用户使用门槛 |
| 接口文档 | Knife4j（Java） + Swagger UI（Python） | 自动生成接口文档，方便联调与第三方对接 |

### 4.1 关键依赖版本基线（建议）

| 组件 | 版本基线 | 备注 |
|---|---|---|
| JDK | 17 LTS | Spring Boot 3 最低要求 |
| Spring Boot | 3.2.x | 稳定主线版本 |
| Node.js | 18 LTS | Vite 3 / 4 兼容基线 |
| Python | 3.11 | RAGAS 与 FastAPI 兼容基线 |
| MySQL | 8.0 | utf8mb4 字符集 |
| Redis | 7.x | 队列与缓存 |

---

## 五、核心模块设计

### 5.1 评测用例管理模块

- **核心功能**：评测集创建、用例增删改查、批量导入导出、标签分组、版本快照。
- **实现思路**：
  - 支持可视化表单配置 + YAML 文本编辑两种模式，完全兼容 Promptfoo 用例格式。
  - 单条用例包含：测试问题、参考上下文、预期答案、断言规则、标签、备注。
  - 支持 CSV / Excel 批量导入，支持评测集版本快照与回滚。
- **借鉴来源**：Promptfoo 用例规范。

### 5.2 多模型适配层

- **核心功能**：模型配置管理、密钥管理、统一调用接口、限流熔断、计费统计。
- **实现思路**：
  - 抽象 `BaseModelProvider` 标准接口，定义 chat、embed、token 统计等通用方法。
  - 内置支持：OpenAI、通义千问、文心一言、豆包、Ollama、本地开源模型。
  - 新增模型仅需实现接口 + 配置参数，无需修改核心流程。
- **借鉴来源**：Promptfoo Provider 插件体系。

### 5.3 RAG 评测引擎

- **核心功能**：RAG 全链路质量评测、多指标组合计算、结果标准化输出。
- **实现思路**：
  - 内置核心指标：忠实度（Faithfulness）、答案相关性（Answer Relevancy）、上下文精确率（Context Precision）、上下文召回率（Context Recall）。
  - 执行流程：加载用例 → 调用目标模型生成答案 → 逐项指标计算 → 结果归一化汇总。
  - 底层直接集成 RAGAS 官方库，封装业务配置与异常兜底。
- **借鉴来源**：RAGAS 指标体系与工程实现。

### 5.4 Agent 评测与链路追踪模块

- **核心功能**：Agent 任务完成度评测、工具调用准确率统计、链路可视化、根因定位。
- **实现思路**：
  - 定义标准 Trace 数据格式：规划 → 思考 → 工具调用 → 结果返回 全链路节点。
  - 用户侧按规范上报执行链路，平台自动计算步骤合理性、错误重试次数、幻觉率等指标。
  - 支持链路节点与评测得分关联，快速定位问题环节。
- **借鉴来源**：Arize Phoenix 链路追踪设计。

### 5.5 评测任务调度模块

- **核心功能**：即时评测、定时评测、对比评测、回归评测、任务分片并行。
- **实现思路**：
  - MVP 阶段基于 Redis + 线程池实现异步任务队列，支持任务状态实时更新。
  - 任务自动分片，多进程并行执行评测，提升批量任务效率。
  - 支持任务暂停、取消、重试，失败自动兜底与日志记录。
- **借鉴来源**：OpenCompass 任务分片调度逻辑。

### 5.6 结果可视化与报告模块

- **核心功能**：得分总览、用例详情、多版本对比、质量趋势、报告导出。
- **实现思路**：
  - 单任务结果：整体得分、各维度得分分布、坏例高亮、断言命中详情。
  - 对比评测：雷达图多维度对比、得分差异表格、劣化用例自动标记。
  - 趋势分析：版本迭代质量曲线、通过率变化趋势。
  - 支持 Markdown / PDF 格式报告导出，支持公开分享链接。
- **借鉴来源**：Promptfoo 对比视图 + OpenCompass 榜单展示。

### 5.7 系统管理模块

- **核心功能**：用户管理、角色权限、项目成员、系统配置、操作日志。
- **实现思路**：基于 RBAC 权限模型，支持超级管理员、项目管理员、普通用户三级角色。

---

## 六、数据库表结构设计

### 6.1 核心 ER 关系

```
user（用户）
  └── project_member（项目成员）── project（项目）
                                        ├── dataset（评测集）
                                        │       └── eval_case（评测用例）
                                        ├── eval_task（评测任务）
                                        │       ├── eval_task_item（任务用例明细）
                                        │       └── eval_result（评测结果）
                                        └── model_config（模型配置）
```

### 6.2 核心表设计

#### 6.2.1 sys_user 用户表

| 字段名 | 类型 | 说明 |
|---|---|---|
| id | BIGINT PK | 主键 |
| username | VARCHAR(64) | 登录账号，唯一 |
| password | VARCHAR(128) | 加密存储密码 |
| nickname | VARCHAR(64) | 昵称 |
| email | VARCHAR(128) | 邮箱 |
| role | VARCHAR(32) | 角色：ADMIN / PROJECT_ADMIN / MEMBER |
| status | TINYINT | 状态：0 禁用，1 启用 |
| create_time | DATETIME | 创建时间 |
| update_time | DATETIME | 更新时间 |

#### 6.2.2 project 项目表

| 字段名 | 类型 | 说明 |
|---|---|---|
| id | BIGINT PK | 主键 |
| name | VARCHAR(128) | 项目名称 |
| description | TEXT | 项目描述 |
| owner_id | BIGINT | 负责人 ID |
| status | TINYINT | 状态：0 归档，1 正常 |
| create_time | DATETIME | 创建时间 |
| update_time | DATETIME | 更新时间 |

#### 6.2.3 dataset 评测集表

| 字段名 | 类型 | 说明 |
|---|---|---|
| id | BIGINT PK | 主键 |
| project_id | BIGINT | 所属项目 |
| name | VARCHAR(128) | 评测集名称 |
| version | VARCHAR(32) | 版本号 |
| description | TEXT | 描述 |
| case_count | INT | 用例数量（冗余统计） |
| snapshot | TINYINT | 是否快照：0 否，1 是 |
| create_time | DATETIME | 创建时间 |
| update_time | DATETIME | 更新时间 |

#### 6.2.4 eval_case 评测用例表

| 字段名 | 类型 | 说明 |
|---|---|---|
| id | BIGINT PK | 主键 |
| dataset_id | BIGINT | 所属评测集 |
| question | TEXT | 测试问题 |
| context | TEXT | 参考上下文（RAG 场景） |
| expected_answer | TEXT | 预期答案 |
| assertions | JSON | 断言规则配置 |
| tags | VARCHAR(256) | 标签，逗号分隔 |
| remark | TEXT | 备注 |
| create_time | DATETIME | 创建时间 |
| update_time | DATETIME | 更新时间 |

#### 6.2.5 model_config 模型配置表

| 字段名 | 类型 | 说明 |
|---|---|---|
| id | BIGINT PK | 主键 |
| project_id | BIGINT | 所属项目（可为空，全局配置） |
| provider | VARCHAR(32) | 模型厂商：openai / qwen / ollama 等 |
| model_name | VARCHAR(64) | 模型名称 |
| api_key | VARCHAR(256) | 加密存储密钥 |
| base_url | VARCHAR(256) | 接口地址 |
| params | JSON | 模型参数（temperature、max_tokens 等） |
| status | TINYINT | 状态：0 停用，1 启用 |
| create_time | DATETIME | 创建时间 |

#### 6.2.6 eval_task 评测任务表

| 字段名 | 类型 | 说明 |
|---|---|---|
| id | BIGINT PK | 主键 |
| project_id | BIGINT | 所属项目 |
| dataset_id | BIGINT | 评测集 ID |
| model_config_id | BIGINT | 目标模型配置 ID |
| task_type | VARCHAR(32) | 类型：RAG / AGENT / PROMPT / COMPARE |
| status | VARCHAR(16) | 状态：PENDING / RUNNING / SUCCESS / FAILED / CANCELED |
| total_count | INT | 用例总数 |
| success_count | INT | 通过数 |
| fail_count | INT | 未通过数 |
| score | DECIMAL(5,2) | 综合得分 |
| metrics | JSON | 各维度指标得分 |
| trigger_type | VARCHAR(16) | 触发方式：MANUAL / SCHEDULE / CI |
| error_message | TEXT | 失败原因 |
| create_by | BIGINT | 创建人 |
| create_time | DATETIME | 创建时间 |
| finish_time | DATETIME | 完成时间 |

#### 6.2.7 eval_task_item 任务用例明细表

| 字段名 | 类型 | 说明 |
|---|---|---|
| id | BIGINT PK | 主键 |
| task_id | BIGINT | 所属任务 |
| case_id | BIGINT | 用例 ID |
| actual_answer | TEXT | 模型实际输出 |
| trace | JSON | Agent / RAG 链路 Trace |
| item_score | DECIMAL(5,2) | 本条得分 |
| assertions_result | JSON | 各断言命中结果 |
| metrics | JSON | 本条各指标明细 |
| status | VARCHAR(16) | 状态：PENDING / SUCCESS / FAILED |
| create_time | DATETIME | 创建时间 |

#### 6.2.8 eval_result 评测结果汇总表（对比与趋势用）

| 字段名 | 类型 | 说明 |
|---|---|---|
| id | BIGINT PK | 主键 |
| task_id | BIGINT | 关联任务 |
| project_id | BIGINT | 所属项目 |
| dimension | VARCHAR(32) | 指标维度 |
| score | DECIMAL(5,2) | 维度得分 |
| detail | JSON | 指标明细数据 |
| create_time | DATETIME | 创建时间 |

### 6.3 索引规划

- `eval_case.dataset_id`：按评测集查询用例。
- `eval_task.project_id + create_time`：项目维度任务列表与趋势查询。
- `eval_task_item.task_id`：任务明细分页查询。
- `model_config.project_id`：项目模型配置查询。

---

## 七、接口设计规范

### 7.1 统一返回体格式

```json
{
  "code": 200,
  "message": "success",
  "data": {}
}
```

- `code`：200 成功；4xx 客户端错误；5xx 服务端错误。
- `message`：提示信息，失败时返回可读原因。
- `data`：业务数据对象，列表场景包含 `list` 与 `total`。

### 7.2 核心接口清单（业务中台 REST API）

#### 项目管理

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/projects | 创建项目 |
| GET | /api/projects | 项目分页列表 |
| GET | /api/projects/{id} | 项目详情 |
| PUT | /api/projects/{id} | 更新项目 |
| DELETE | /api/projects/{id} | 删除项目 |

#### 评测集与用例

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/datasets | 创建评测集 |
| GET | /api/datasets | 评测集列表 |
| POST | /api/cases | 新增用例 |
| PUT | /api/cases/{id} | 更新用例 |
| DELETE | /api/cases/{id} | 删除用例 |
| POST | /api/datasets/{id}/import | 批量导入（YAML / CSV / Excel） |
| GET | /api/datasets/{id}/export | 批量导出 |

#### 模型配置

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/models | 新增模型配置 |
| GET | /api/models | 模型配置列表 |
| PUT | /api/models/{id} | 更新模型配置 |
| DELETE | /api/models/{id} | 删除模型配置 |

#### 评测任务与结果

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/tasks | 提交评测任务 |
| GET | /api/tasks | 任务列表 |
| GET | /api/tasks/{id} | 任务详情与得分汇总 |
| GET | /api/tasks/{id}/items | 任务用例明细分页 |
| POST | /api/tasks/{id}/cancel | 取消任务 |
| GET | /api/tasks/compare | 多任务对比结果 |
| GET | /api/tasks/{id}/report | 导出评测报告 |

### 7.3 评测引擎内部接口（Python FastAPI）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /eval/rag | 提交单批 RAG 评测 |
| POST | /eval/agent | 提交单批 Agent 链路评测 |
| POST | /eval/assertions | 执行断言校验 |
| GET | /eval/tasks/{id}/status | 查询引擎侧任务状态 |
| GET | /health | 健康检查 |

### 7.4 错误码规划（分模块段）

| 段 | 模块 | 示例 |
|---|---|---|
| 10001-10099 | 通用 / 参数校验 | 10001 参数缺失 |
| 20001-20099 | 项目与权限 | 20001 无项目权限 |
| 30001-30099 | 用例与评测集 | 30001 用例格式非法 |
| 40001-40099 | 模型适配 | 40001 模型密钥无效 |
| 50001-50099 | 评测任务 | 50001 任务执行失败 |

---

## 八、项目初始目录结构

### 8.1 整体工程结构

```
zmevalhub/
├── zmevalhub-admin          # 前端控制台（Vue3）
├── zmevalhub-server         # 业务中台后端（Java Spring Boot）
├── zmevalhub-engine         # 评测引擎服务（Python FastAPI）
├── deploy                   # 部署脚本与配置
│   ├── docker-compose.yml
│   └── env-example
├── docs                     # 项目文档
│   ├── quickstart.md
│   ├── api.md
│   └── dev-guide.md
├── README.md
└── LICENSE
```

### 8.2 业务中台后端（Java）

```
zmevalhub-server/
├── src/main/java/com/zmevalhub/
│   ├── common            # 通用工具类、异常、常量
│   ├── config            # 配置类
│   ├── modules
│   │   ├── project       # 项目管理模块
│   │   ├── dataset       # 评测集模块
│   │   ├── case          # 评测用例模块
│   │   ├── task          # 评测任务模块
│   │   ├── result        # 评测结果模块
│   │   ├── model         # 模型配置模块
│   │   └── system        # 系统管理模块
│   └── ZMEvalHubApplication.java
├── src/main/resources
│   ├── application.yml
│   └── mapper
└── pom.xml
```

### 8.3 评测引擎服务（Python）

```
zmevalhub-engine/
├── app/
│   ├── api               # API 路由
│   ├── core              # 核心配置与异常
│   ├── evaluation
│   │   ├── rag           # RAG 评测实现
│   │   ├── agent         # Agent 评测实现
│   │   ├── metrics       # 指标插件集
│   │   └── assertions    # 断言引擎
│   ├── providers         # 模型适配器
│   ├── schemas           # 数据模型
│   └── utils
├── main.py
├── requirements.txt
└── .env.example
```

### 8.4 前端控制台（Vue3）

```
zmevalhub-admin/
├── src/
│   ├── api               # 接口请求
│   ├── assets            # 静态资源
│   ├── components        # 公共组件
│   ├── views
│   │   ├── project       # 项目管理页
│   │   ├── dataset       # 评测集页
│   │   ├── case          # 用例管理页
│   │   ├── task          # 任务管理页
│   │   ├── result        # 结果报告页
│   │   └── system        # 系统管理页
│   ├── router
│   ├── store
│   └── utils
├── package.json
└── vite.config.js
```

---

## 九、分阶段开发执行大纲

总计约 12 周完成正式开源 1.0 版本，每个阶段产出可运行的可用产物。

### 阶段 0：项目初始化与技术验证（第 1 周）

**目标**：搭建工程骨架，验证核心评测链路可行性。

1. 工程初始化
   - 创建前端、业务后端、评测引擎三个工程，配置基础依赖与构建脚本。
   - 设计核心数据库表结构，完成建表脚本与基础实体类。
   - 搭建 Docker Compose 基础编排，包含 MySQL、Redis。
2. 核心技术验证
   - Python 侧集成 RAGAS 库，跑通单条 RAG 评测最简流程。
   - Java 侧通过 HTTP 调用评测引擎接口，完成联调。
   - 前端基础布局与路由搭建，完成首页框架。
3. 交付物
   - 可本地启动的工程骨架。
   - 最简评测链路 Demo：输入问题 + 上下文 → 返回评测得分。
   - 核心数据库设计文档。

### 阶段 1：MVP 版本 — 核心评测闭环（第 2-4 周，共 3 周）

**目标**：完成 RAG / Prompt 评测完整链路，可独立使用。

1. 功能开发
   - 项目管理、评测集管理、用例管理的完整 CRUD。
   - 支持 CSV / YAML 批量导入导出评测用例。
   - 完成 3 款主流模型适配器（OpenAI、通义千问、Ollama）。
   - 异步评测任务队列，支持任务提交、进度查询、结果查看。
   - 基础结果页面：整体得分、用例列表、单条详情。
   - 基础用户登录与权限控制。
2. 工程建设
   - 统一异常处理、全局日志规范、接口文档。
   - 前端交互优化与基础错误提示。
   - 编写本地部署文档与快速开始指南。
3. 交付物
   - 可部署的 MVP 版本。
   - 支持创建评测集、发起 RAG 评测、查看评测结果。
   - 完整的部署与使用文档。

### 阶段 2：V1.0 版本 — 平台化与对比能力（第 5-8 周，共 4 周）

**目标**：完善中台能力，形成产品核心竞争力。

1. 功能开发
   - 多版本对比评测：雷达图对比、得分差异明细、劣化用例高亮。
   - 断言规则引擎：内置关键词、正则、语义相似度、分类打分 4 类断言。
   - Agent 评测初版：支持工具调用准确率、任务完成度评测。
   - 可视化仪表盘：项目质量总览、版本趋势曲线。
   - 评测报告导出：支持 Markdown / PDF 格式。
   - 完善 RBAC 权限体系与项目成员管理。
   - 评测引擎并发优化，支持批量任务并行执行。
2. 工程建设
   - 性能压测与优化。
   - 完善单元测试与集成测试。
   - 官方 Demo 站点搭建。
3. 交付物
   - 正式开源 V1.0 版本。
   - 覆盖 RAG / Prompt / Agent 基础评测能力。
   - 可用于生产环境的稳定版本。

### 阶段 3：V2.0 版本 — 生态打通与差异化能力（第 9-12 周，共 4 周）

**目标**：打造独家优势，形成产品生态闭环。

1. 功能开发
   - 对接 Prompt 版本管理平台：一键选择 Prompt 版本发起评测，结果反向关联。
   - 对接 RAG / Agent 系统：支持拉取执行链路，做端到端全链路评测。
   - CI/CD 集成：提供 GitHub Action、Jenkins 插件。
   - 红队评测：Prompt 注入检测、合规性校验、安全风险评估。
   - 插件市场：支持第三方自定义评测指标、模型适配器。
   - 模型 / Prompt 版本排行榜。
   - CLI 命令行工具发布。
2. 工程建设
   - 插件开发文档与贡献者指南。
   - 最佳实践案例文档。
   - 开源社区运营物料准备。
3. 交付物
   - 具备差异化竞争力的 V2.0 版本。
   - 完整的「Prompt 管理 → 应用开发 → 评测优化」闭环。
   - 活跃的开源社区基础。

### 阶段 4：开源运营与社区迭代（持续）

- 完善 README、快速开始、最佳实践文档。
- 发布技术文章、案例教程，推广到开发者社区。
- 收集社区需求，迭代核心能力，维护版本 roadmap。

---

## 十、本地开发环境启动指南

### 10.1 前置依赖

- JDK 17+
- Python 3.11+
- Node.js 18+
- Docker & Docker Compose
- MySQL 8.0（可使用 Docker 启动）
- Redis 7.x（可使用 Docker 启动）

### 10.2 环境搭建步骤

1. **克隆项目**

```bash
git clone <仓库地址>
cd zmevalhub
```

2. **启动基础依赖**

```bash
cd deploy
docker-compose up -d mysql redis
```

3. **启动评测引擎服务**

```bash
cd ../zmevalhub-engine
pip install -r requirements.txt
cp .env.example .env
# 配置大模型 API Key 等参数
python main.py
# 服务默认启动在 8001 端口
```

4. **启动业务中台后端**

```bash
cd ../zmevalhub-server
# 修改 application.yml 中的数据库、Redis、评测引擎地址
mvn spring-boot:run
# 服务默认启动在 8080 端口
```

5. **启动前端控制台**

```bash
cd ../zmevalhub-admin
npm install
npm run dev
# 前端默认启动在 5173 端口
```

6. **访问验证**

- 前端地址：http://localhost:5173
- 后端接口文档：http://localhost:8080/doc.html
- 评测引擎文档：http://localhost:8001/docs

### 10.3 端口规划

| 服务 | 默认端口 |
|---|---|
| 前端控制台 | 5173 |
| 业务中台后端 | 8080 |
| 评测引擎服务 | 8001 |
| MySQL | 3306 |
| Redis | 6379 |

---

## 十一、开发规范

### 11.1 代码规范

- Java 遵循 Alibaba Java 开发规范。
- Python 遵循 PEP 8 规范，使用 black 格式化。
- 前端遵循 ESLint + Prettier 规范。
- 所有公共方法必须添加注释，核心业务逻辑必须说明设计思路。

### 11.2 Git 提交规范

采用 Conventional Commits 规范：

```
<type>(<scope>): <subject>
```

- type：feat（新功能）、fix（修复）、docs（文档）、style（格式）、refactor（重构）、test（测试）、chore（构建 / 工具）。
- 示例：`feat(case): 支持YAML格式评测集导入`。

### 11.3 接口规范

- 统一 RESTful API 设计风格。
- 统一返回体格式：code、message、data。
- 所有接口必须进行参数校验。
- 错误码统一规划，业务错误码分模块管理。

### 11.4 分支管理策略

- `main`：稳定发布分支。
- `develop`：日常开发集成分支。
- `feature/*`：功能分支，从 develop 切出。
- `fix/*`：修复分支。
- 版本发布打 Tag：v0.1.0（MVP）、v1.0.0（正式版）、v2.0.0（生态版）。

---

## 十二、风险与避坑指南

1. **避免自研评测指标**：核心评测能力复用 RAGAS 等成熟库，聚焦中台产品体验，不做算法重复发明。
2. **MVP 阶段做减法**：优先跑通核心流程，暂缓分布式调度、复杂多租户等非核心功能。
3. **双栈通信简化**：Java 与 Python 优先使用 REST API 通信，避免引入复杂 RPC 框架增加维护成本。
4. **重视中文优化**：主流评测框架对中文支持有限，针对性优化评判 Prompt 与数据集，打造差异化。
5. **数据安全兜底**：支持全私有化部署，评测数据不出本地，满足企业合规需求。
6. **密钥安全**：模型 API Key 在数据库中加密存储，前端不明文回显，日志中脱敏。
7. **评测成本控制**：批量任务支持并发上限与预算阈值，避免大模型调用费用失控。

---

## 十三、开源运营初步规划

1. **发布准备**：完善 README、快速开始文档、最佳实践教程。
2. **社区推广**：在 GitHub、掘金、知乎、AI 开发者社区发布项目介绍与技术文章。
3. **生态对接**：对接主流 AI 开发框架，提供官方集成插件。
4. **版本迭代**：定期发布版本更新，维护公开 Roadmap，积极处理社区 Issue 与 PR。

### 13.1 开源 License 建议

- 优先选择 Apache-2.0 或 MIT 协议，宽松商用友好；若评估存在 copyleft 传染性依赖，需在 LICENSE 与 NOTICE 中注明。

### 13.2 Roadmap 里程碑

| 版本 | 里程碑 | 预期周期 |
|---|---|---|
| v0.1.0 | MVP：RAG / Prompt 评测闭环 | 第 4 周 |
| v1.0.0 | 平台化：对比、断言、Agent 评测、报告导出 | 第 8 周 |
| v2.0.0 | 生态版：Prompt 平台打通、CI 集成、红队评测、插件体系 | 第 12 周 |

---

## 附录 A：术语表

| 术语 | 说明 |
|---|---|
| RAG | 检索增强生成（Retrieval-Augmented Generation） |
| Agent | 具备规划、工具调用能力的智能体 |
| LLM-as-Judge | 以大模型作为评判方对输出打分的评测方式 |
| Trace | 一次 RAG / Agent 执行的全链路调用记录 |
| 断言（Assertion） | 对模型输出是否满足规则的自动校验 |
| 红队评测（Red Teaming） | 主动构造对抗用例，检测安全与合规风险 |

## 附录 B：参考项目链接汇总

- Promptfoo：https://github.com/promptfoo/promptfoo
- RAGAS：https://github.com/explodinggradients/ragas
- DeepEval：https://github.com/confident-ai/deepeval
- Arize Phoenix：https://github.com/Arize-ai/phoenix
- OpenCompass：https://github.com/open-compass/opencompass
