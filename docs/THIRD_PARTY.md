# 第三方组件与许可证边界

本仓库的 MIT 许可只覆盖 ZMEvalHub 自身代码和文档，不改变依赖的许可，也不表示本项目拥有第三方代码。依赖通过 `pyproject.toml` / `uv.lock` 引用，未将其源码复制进仓库。下表按本地已安装版本的包元数据及上游项目说明核对（2026-11-12）。升级依赖或重新分发打包产物时应复核对应版本的许可证与通知要求。

| 组件 | 本地版本 | 许可 | 在本项目中的边界 |
|---|---:|---|---|
| [Arize Phoenix](https://github.com/Arize-ai/phoenix/blob/main/docs/phoenix/self-hosting/license.mdx) `arize-phoenix` | 21.0.0 | Elastic License 2.0 | 可选的独立实验、Trace 与 Evaluation 平台；其许可不被本项目 MIT 覆盖。ELv2 对向第三方提供托管或管理服务等用途设有限制，公开托管前须单独审查。 |
| `arize-phoenix-client`（Phoenix 间接依赖） | 3.7.0 | Apache-2.0 | SDK 按自身许可使用；不能由主包许可推断所有子包许可。 |
| `arize-phoenix-otel` | 0.17.3 | Apache-2.0 | 可选 OpenTelemetry 接入。 |
| [OpenInference](https://github.com/Arize-ai/openinference/blob/main/LICENSE) `openinference-semantic-conventions` | 0.1.43 | Apache-2.0 | 语义约定与 Trace 属性；保留上游版权、许可及适用通知。 |
| [FastAPI](https://github.com/fastapi/fastapi/blob/master/LICENSE) | 0.162.4 | MIT | 可选只读 Web API 框架。 |
| [Pydantic](https://github.com/pydantic/pydantic/blob/main/LICENSE) | 2.14.3 | MIT | 数据校验。 |
| [SQLAlchemy](https://github.com/sqlalchemy/sqlalchemy/blob/main/LICENSE) | 2.1.8 | MIT | 本地导入账本。 |
| [Uvicorn](https://github.com/encode/uvicorn/blob/master/LICENSE.md) | 0.54.0 | BSD-3-Clause | 可选 ASGI 服务。 |

Ragas、Promptfoo 当前未作为项目依赖接入。Phoenix 的数据集、实验、Trace 和 UI 属于上游能力；ZMEvalHub 的原创范围为数据适配、规则、可信采集守卫、成对比较、Gate、导入协调和只读查询。此清单不替代完整的传递依赖许可证清单；如分发包含依赖的安装包，应从实际构建产物生成完整通知清单。
