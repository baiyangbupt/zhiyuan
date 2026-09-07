# 录取率与 Evidence 可信事实层设计

**日期：** 2026-09-07  
**范围：** 志愿填报对话引擎第二期第一个交付切片  
**状态：** 已确认设计，待实施计划

## 1. 目标

本切片建立招生单元级录取事实和 Evidence 的统一只读契约，使对话引擎能够对每个录取风险结论说明数据来源、适用范围、版本和限制。它先解决“事实可信、口径一致、可解释、可审计”，不在本切片改变推荐排序、Solver 或任何写入流程。

用户最终应能看到并理解：对应哪个招生单元、基于哪一年的哪一批数据、系统计算的录取率是多少、为什么归入冲/稳/保、证据版本是什么，以及数据是否存在限制。

## 2. 已确认的边界

### 2.1 权威来源

- Java 服务和数据库中的招生单元查询是唯一业务事实来源。
- 录取率使用现有系统基于分数/位次计算的结果；Python、模型和前端不重新计算概率。
- 招生单元是最小事实粒度，学校级统计、专业类平均值或模型常识不能替代招生单元事实。

### 2.2 风险口径

系统按招生单元录取率固定分层：

| 录取率 | 风险层 | 说明 |
| --- | --- | --- |
| `<50%` | 冲 | 风险高 |
| `50%~70%` | 稳 | 风险适中 |
| `70%~99%` | 保 | 风险较低 |

边界由服务端校验。模型传入的 tier 不是权威字段，任何冲突都以服务端结果为准；超出支持范围或缺少录取率时不能强行分类。

### 2.3 非目标

本切片不包含：

- Rank/Solver 权重或推荐算法改造；
- 录取率重新计算或概率模型升级；
- Proposal/CAS、确认或任何写工具；
- 最终志愿方案生成、排序和审查规则重构；
- 新增外部数据源或用模型生成数据补洞。

## 3. 统一数据模型

### 3.1 AdmissionFact

每个事实对应一个明确的招生单元，字段语义如下：

| 字段 | 类型 | 必填 | 语义 |
| --- | --- | --- | --- |
| `admissionUnitId` | string | 是 | 招生单元稳定标识 |
| `schoolId` / `schoolName` | string | 是 | 标准院校实体 |
| `majorId` / `majorName` | string | 是 | 标准专业实体或专业组 |
| `provinceCode` | string | 是 | 生源省份 |
| `year` | integer | 是 | 招生年份 |
| `batch` | string | 是 | 批次/招生类型 |
| `scoreRange` | object | 否 | 历史分数范围，存在时包含上下界 |
| `rankRange` | object | 否 | 历史位次范围，存在时包含上下界 |
| `admissionRate` | number | 是 | 系统计算的录取率，单位为百分比 `0~100` |
| `riskTier` | enum | 是 | `冲`、`稳` 或 `保`，由服务端推导并校验 |
| `dataVersion` | string | 是 | 招生数据版本 |
| `algorithmVersion` | string | 是 | 录取率计算算法版本 |
| `observedAt` | datetime | 是 | 数据生成/观测时间 |
| `limitations` | string[] | 否 | 适用范围和缺失说明 |

`scoreRange`、`rankRange` 任一缺失不影响事实有效性，但必须在 `limitations` 中说明。`admissionRate` 缺失、非有限数值或超出 `0~100` 时，事实无效。

### 3.2 EvidenceRef

每个关键录取事实必须提供 Evidence 引用：

```json
{
  "evidenceId": "admission-unit:2026:bj:unit-123:v17",
  "kind": "admission_fact",
  "admissionUnitId": "unit-123",
  "source": "zhiyuan-server.admission",
  "dataVersion": "2026-06-v17",
  "algorithmVersion": "admission-rate-v3",
  "stateVersion": 42,
  "scope": {
    "tenantId": "tenant-1",
    "sessionId": "session-1",
    "year": 2026,
    "batch": "本科批"
  },
  "observedAt": "2026-06-20T10:00:00Z",
  "limitations": []
}
```

Evidence 不承载可执行动作，也不能跨租户或跨会话复用。`stateVersion` 表示该事实与本轮 Snapshot 的绑定版本，`dataVersion` 表示招生数据版本；两者用途不同，均须保留。

### 3.3 MCP 响应 envelope

三个只读工具 `admission.get_history`、`admission.get_current_plan`、`admission.check_eligibility` 使用同一 envelope：

```json
{
  "status": "ok",
  "data": {
    "admissionFacts": [],
    "evidence": [],
    "limitations": []
  },
  "stateVersion": 42,
  "dataVersion": "2026-06-v17"
}
```

`status` 可为 `ok`、`insufficient_data`、`evidence_stale`、`evidence_scope_mismatch` 或 `recoverable_error`。失败响应仍保持结构化字段，不能以自然语言数字替代 `data`。

## 4. 数据流与职责

1. Gateway 根据当前会话 Snapshot 构造只读 MCP 请求，传入可信的 tenant/session binding 和期望 `stateVersion`。
2. Java 后端查询招生单元及系统录取率，返回 AdmissionFact、EvidenceRef、数据版本和限制说明。
3. MCP 层执行 envelope、范围和调用预算校验；禁止写工具和模型覆盖身份字段。
4. Gateway 的输出校验器验证招生单元存在性、录取率范围、riskTier 边界、Evidence 引用、tenant/session 范围和 `stateVersion`/`dataVersion` 新鲜度。
5. 只有通过校验的事实才能进入 `TurnOutput` 的 recommendation、artifact 或 `evidence.updated` 事件。
6. 前端从结构化 Artifact/Evidence 渲染录取事实卡片和 Evidence 抽屉，不解析 assistant Markdown。

任何一层校验失败都必须 fail closed：保留已验证事实，剔除无效事实，并返回可恢复的结构化状态。

## 5. 错误处理与降级

### 5.1 数据不足

以下情况返回 `insufficient_data`：招生单元不存在、年份/批次不匹配、录取率缺失、关键字段不完整或数据不在支持范围内。响应列出缺失字段和下一步查询建议，不补零、不猜测、不降级成学校级统计。

### 5.2 版本与范围错误

- Evidence 属于其他 session/tenant：`evidence_scope_mismatch`。
- `stateVersion` 落后于当前 Snapshot，或 `dataVersion` 已失效：`evidence_stale`。
- 版本校验失败时不使用旧缓存冒充当前结果。

### 5.3 格式和口径错误

- `admissionRate` 不是有限数值或不在 `0~100`：拒绝该事实。
- `riskTier` 与固定边界不一致：拒绝模型提供的 tier，并要求服务端重新生成；不得静默展示冲稳保。
- 事实缺少 EvidenceRef：不得进入 recommendation/artifact。

### 5.4 后端故障

后端查询最多进行一次短重试。仍失败时返回 `recoverable_error`，不回退到未经验证的缓存或模型常识。只读问答显示“当前数据暂不可核验”；推荐/方案解释不生成 recommendation/artifact，并保留已验证的其他证据。

### 5.5 可观测性

每次校验记录 `evidenceId`、`admissionUnitId`、`dataVersion`、`stateVersion` 和 `validationCode`，不记录用户隐私原文。Shadow 评测统计未知招生单元、无 Evidence、错误 tier、过期版本和跨会话引用。

## 6. 前端交互

- 录取事实卡片显示院校/专业/招生单元、录取率、冲稳保、年份/批次和数据状态。
- Evidence 抽屉显示来源、数据版本、算法版本、观测时间、适用范围和限制说明。
- `insufficient_data`、`evidence_stale` 和 `recoverable_error` 使用明确状态文案，并提供重新查询入口。
- 前端不从模型文本中提取或计算录取率；缺少结构化字段时不显示数字。

## 7. 测试与验收门禁

### 7.1 Python/MCP/Gateway

- 有效招生单元事实可通过 envelope、Evidence 和版本校验。
- 录取率边界 `<50`、`50~70`、`70~99` 的 tier 结果稳定。
- 非法数值、未知招生单元、缺字段和错误 tier 被拒绝。
- 过期版本、跨会话 Evidence 和 Snapshot 不匹配被拒绝。
- 无 Evidence 的事实不能进入 recommendation/artifact。
- 后端失败仅一次重试，随后返回结构化可恢复错误。
- MCP 工具清单仍为八个只读工具，写工具数为 0。

### 7.2 Java

- DTO 序列化字段与 Python envelope 一致。
- 招生单元查询透传系统录取率、数据版本和算法版本，不改变计算结果。
- 缺失数据、版本不一致和未知招生单元返回稳定错误码。

### 7.3 前端

- 结构化事实卡片和 Evidence 抽屉正确渲染。
- 错误状态不显示未经验证的数字。
- Markdown 中伪造的录取率不会影响展示。

### 7.4 Shadow 与回归

固定案例的未知招生单元、无 Evidence、错误风险分层、过期版本、跨会话引用必须全部为 0。默认 `GATEWAY_MODE=legacy` 行为不变，`codex_shadow` 失败不影响旧链路回复。

## 8. 发布与回退

先在离线 fixture 和 Shadow 中启用校验，再接入只读 Canary。任何 MCP 初始化、Evidence 校验或版本绑定失败均回退到旧链路并保留结构化错误日志。此切片不改变生产写入路径；只有连续 Shadow 批次满足硬门禁后，才评估后续只读 Canary。

## 9. 后续拆分

本切片完成后，另行设计并评审：

1. Plan Review Policy：整合冲稳保框架、梯度保护、有效保底和 repair options；
2. Rank/Solver：拆分 Eligibility、Admission Probability、Preference Fit 和 Data Confidence，继续复用权威录取率；
3. Proposal/CAS：只允许 preview/create，确认时重新读取权威版本并校验 postcondition；
4. 规划工作台：扩展候选、Evidence、Review finding、Plan diff 和最终 Artifact。

