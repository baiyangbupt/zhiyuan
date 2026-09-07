# 招生事实与 Evidence 运行手册

## 适用范围

本切片只读接入 Java/数据库提供的招生单元事实。录取率仍由现有招生服务按分数和位次计算，Python、模型和浏览器不重新计算，也不能用模型文本补齐缺失数据。

招生类型是会话级定义：

- `major`：专业+大学，一个专业计划是一个招生单元。
- `major_group`：院校专业组，一个专业组是一个招生单元，组内专业仅作为明细，不能重复计入方案数量。

后端旧值 `majorGroup` 只允许在边界适配，新的 Snapshot、MCP、Evidence 和前端事件统一使用 `major_group`。

## 录取率与风险层

| 招生单元录取率 | 风险层 |
| --- | --- |
| 小于 50% | 冲 |
| 50% 至小于 70% | 稳 |
| 70% 至 99%（含 99%） | 保 |

缺少录取率、不是有限数值或大于 99% 时返回数据不足，不能强行归入冲稳保。专业组主卡片只使用组级 `unitAdmissionRate`；`majorAdmissionRate` 只能显示在组内明细中。

## Evidence 要求

进入事实、推荐或审查输出的关键招生事实必须有同一轮 Evidence，且同时满足：

- `admissionMode` 与当前 Snapshot 一致；
- `admissionUnitId`、专业组代码（如有）一致；
- `stateVersion` 与当前 Snapshot 一致；
- `dataVersion` 与事实来源一致；
- tenant、session、thread 范围一致。

模式切换会使旧事实、候选、审查、Artifact 和 Proposal 失效，必须重新查询。过期、跨会话、跨租户或跨模式引用均 fail closed。

## MCP 使用

三个招生只读工具统一返回 `admissionMode`、`admissionFacts`、`evidence`、`limitations`、`stateVersion` 和 `dataVersion`。请求可以省略 `admissionMode`，此时使用可信会话模式；显式传入时必须与会话一致。

后端故障只允许一次短重试，仍失败返回结构化 `backend_unavailable`。招生单元、年份、批次、录取率或专业组明细不足时返回 `insufficient_data`，不补零、不使用旧缓存冒充当前结果。

## Shadow 门禁

固定案例至少覆盖：未知招生单元、无 Evidence、错误风险层、过期 Evidence、跨会话引用、跨招生类型引用、专业组缺少明细。发布前要求以下计数为零：

- `unknownAdmissionUnits`
- `factsWithoutEvidence`
- `crossSessionProposalUse`
- 未授权写入

默认 `GATEWAY_MODE=legacy` 保持不变；Shadow 或只读 Canary 失败时回退旧链路，并保留结构化错误日志。

## 当前验证

- Python 招生事实、Gateway、Snapshot、MCP、Shadow 目标回归：`82 passed`。
- Java Snapshot DTO 与序列化定向测试：通过。
- 前端结构化会话事件测试：通过。
- 前端全量 TypeScript 检查仍有仓库既有错误，新增事实卡和事件模块未产生新的错误。
