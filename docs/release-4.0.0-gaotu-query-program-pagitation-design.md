# Release 4.0.0 - Gaotu Query Program Pagination Design

> 日期: 2026-07-07
> 参考: `~/20260707全量AI方案分页接口说明-Init与Page.pdf`
> 背景: `prod-3.1.2` 中 `queryAllProgramData` 仍调用上游单次全量接口；该接口在 8000-15000+ 条明细场景下存在响应体过大、耗时长和超时风险。本设计用于接入上游新增的 Init + Page 分页传输链路。

## 1. 结论

分页接口应作为 `queryAllProgramData` 内部传输层优化接入，不改变当前业务层和 Agent 层看到的数据契约。

也就是说，上游由一次全量请求拆成:

1. `generateAllExpertAIProgramInit`: 初始化分页会话，返回 `sessionId`、`total`、`pages`、`pageSize`、`model` 等方案头信息。
2. `generateAllExpertAIProgramPage`: 按 `sessionId + current` 拉取分页明细 `detailList`。

但 `GaotuService.queryAllProgramData(ProgramPageReq req)` 仍返回旧全量接口等价的 `JSONObject`:

```json
{
  "model": "<Init.model>",
  "type": "<Init.type>",
  "policy": "<Init.policy>",
  "isLatestPolicy": "<Init.isLatestPolicy>",
  "detailList": "<Page1.detailList + Page2.detailList + ...>"
}
```

下游 `ChatSessionBizService`、`VolunteerSourceDataSyncService`、数据清洗、文件落盘、候选池解析和 Agent 对话链路不应感知分页 `sessionId`。

## 2. 当前调用链

当前全量方案数据入口集中在服务端:

- `GaotuService.queryAllProgramData(ProgramPageReq req)`
  - 校验 `areaId`、`prepareType`。
  - 新疆 `areaId=650000` 时设置 `subjects=null`。
  - 调用 `gaotuClient.getProgramFullList(req)`。
  - 检查 `code != 0` 和 `data == null`。
  - 返回上游 `JSONObject data`。
- `GaotuClient.getProgramFullList(ProgramPageReq req)`
  - 当前路径: `/hl-wish/ci/ci_feign/volunteer/generateAllExpertAIProgram`
  - baseUrl 优先使用 `gaotu.zhiyuan.program-data-url`，没有时回退 `gaotu.zhiyuan.zhiyuan-url`。
- 主要调用方:
  - `ChatSessionBizService.createChatSession`: 建会话时拉取全量候选，清洗后写入 `session_volunteer_{chatSessionId}.json`。
  - `VolunteerSourceDataSyncService.fetchLatestSourceData`: 刷新最新源数据，清洗、hash、可选持久化。

因此分页改造应收敛在 `GaotuClient + GaotuService`，避免把分页细节扩散到创建会话、数据刷新和 Agent 层。

## 3. 上游新接口

### 3.1 Init

接口:

```text
POST /hl-wish/ci/ci_feign/volunteer/generateAllExpertAIProgramInit
```

入参与旧 `generateAllExpertAIProgram` 一致，即当前 `ProgramPageReq` 对应的 `VolunteerQueryReq`:

- `memberId`
- `areaId`
- `batch`
- `score`
- `subjects`
- `subjectType`
- `year`
- `prepareType`
- `tabType`
- `areas`
- `cities`
- `majorIdList`
- `classifyList`
- `natureList`
- `specialFilterList`
- `registrationConditionList`
- `sortEnum`
- `minTuitionFeeM`
- `maxTuitionFeeM`

核心出参:

| 字段 | 说明 |
| --- | --- |
| `sessionId` | 分页会话 ID，传给 Page 接口。不是用户登录 token |
| `total` | 展开后的明细总条数，即最终合并后 `detailList` 应达到的数量 |
| `pages` | 总页数，Page 需要从 `1` 拉到 `pages` |
| `pageSize` | 建议每页条数，文档示例为 1000 |
| `expireSeconds` | 分页会话有效秒数，当前默认 3600 |
| `type` | 页面展示类型 |
| `model` | 方案头信息，Page 不再返回 |
| `isLatestPolicy` | 是否最新策略 |
| `policy` | 选科策略编码 |

文档示例山东 2026 年场景:

```text
areaId=370000, batch=17, score=516, subjects=010506, prepareType=VOLUNTEER
Init total=15526, pages=16, pageSize=1000
```

注意: `total` 是展开后的分页明细数；`model.majorTotalNum` 是轻量候选集上的冲稳保统计，两者口径不同，不应强行要求相等。

### 3.2 Page

接口:

```text
POST /hl-wish/ci/ci_feign/volunteer/generateAllExpertAIProgramPage
```

入参:

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `sessionId` | 是 | Init 返回的分页会话 ID |
| `current` | 是 | 页码，从 `1` 开始 |
| `size` | 否 | 每页条数，不传默认使用 Init 的 `pageSize`，最大 8000 |

核心出参:

| 字段 | 说明 |
| --- | --- |
| `sessionId` | 分页会话 ID |
| `current` | 当前页码 |
| `size` | 当前页大小 |
| `total` | 明细总条数，理论上与 Init.total 一致 |
| `pages` | 总页数 |
| `detailList` | 当前页院校专业明细，单条结构与旧全量接口 `detailList` 元素一致 |

Page 不返回 `model`，最终方案头必须使用 Init 返回的数据。

## 4. 接入设计

### 4.1 客户端方法

在 `GaotuClient` 中保留旧方法:

```java
ResponseDTO<JSONObject> getProgramFullList(ProgramPageReq req)
```

新增分页方法:

```java
ResponseDTO<JSONObject> getProgramFullListInit(ProgramPageReq req)
ResponseDTO<JSONObject> getProgramFullListPage(ExpertAIProgramPageReq req)
```

首版可以继续使用 `JSONObject` 承接返回，降低 DTO 扩散成本。若后续要增强类型安全，可补充 DTO:

- `ExpertAIProgramPageReq`
  - `String sessionId`
  - `Long current`
  - `Long size`
- `ExpertAIProgramInitResp`
  - `String sessionId`
  - `Long total`
  - `Long pages`
  - `Long pageSize`
  - `Long expireSeconds`
  - `JSONObject type`
  - `JSONObject model`
  - `Boolean isLatestPolicy`
  - `String policy`
- `ExpertAIProgramPageResp`
  - `String sessionId`
  - `Long current`
  - `Long size`
  - `Long total`
  - `Long pages`
  - `JSONArray detailList`

路径常量按当前代码风格保留 `/hl-wish/ci` 前缀:

```java
private static final String PROGRAM_LIST_ALL_INIT_PATH =
        "/hl-wish/ci/ci_feign/volunteer/generateAllExpertAIProgramInit";

private static final String PROGRAM_LIST_ALL_PAGE_PATH =
        "/hl-wish/ci/ci_feign/volunteer/generateAllExpertAIProgramPage";
```

baseUrl 仍沿用旧全量接口逻辑:

```java
String baseUrl = Strings.isNullOrEmpty(gaotuProperties.getProgramDataUrl())
        ? gaotuProperties.getZhiyuanUrl()
        : gaotuProperties.getProgramDataUrl();
```

### 4.2 服务层流程

`GaotuService.queryAllProgramData(req)` 建议流程:

1. 保留当前参数校验。
2. 保留新疆 `subjects=null` 特殊逻辑。
3. 如果分页开关未开启，直接走旧 `getProgramFullList(req)`。
4. 调用 Init。
5. 校验 Init:
   - `code == 0`
   - `data != null`
   - `sessionId` 非空
   - `total >= 0`
   - `pages >= 0`
   - `pageSize > 0`
   - `model != null`
6. 从 `current=1` 到 `pages` 依次调用 Page。
7. 对每页校验:
   - `code == 0`
   - `data != null`
   - `detailList != null`
   - `current` 与请求页码一致，至少打告警。
   - `total/pages` 与 Init 不一致时打告警；是否中断由校验策略决定。
8. 按页顺序 append 全部 `detailList`。
9. 构造旧接口等价 JSON:
   - `model = init.model`
   - `type = init.type`
   - `policy = init.policy`
   - `isLatestPolicy = init.isLatestPolicy`
   - `detailList = allDetails`
10. 校验合并结果。
11. 成功时返回合并后的 `JSONObject`。
12. 失败时按配置降级旧全量接口或抛出 `BusinessException`。

### 4.3 合并校验

必须校验:

```text
merged.detailList.size == init.total
```

建议校验:

```text
distinct(planMajorDataId).size == init.total
```

原因:

- 少页、空页、重复页都会直接影响候选池覆盖。
- 候选池不完整会进一步影响方案推荐、候选替换、用户诉求响应和对话质量。
- 这类问题不能静默成功，否则后续 Agent 层会基于错误候选集做正确推理，最终表现为“语义看起来对，但方案结果错”。

`planMajorDataId` 为空的异常记录应单独计数并打告警，不建议首版直接依赖它作为唯一硬校验。

## 5. 异常与降级

旧接口 `generateAllExpertAIProgram` 继续保留为兜底降级。

| 场景 | 处理 |
| --- | --- |
| Init 返回非 0 | 记录失败原因，按配置降级旧全量接口；关闭降级时抛 `BusinessException` |
| Init data 为空 | 同上 |
| Init 缺少 `sessionId/model/pages/pageSize/total` | 同上 |
| Page 单页失败 | 重试当前页 |
| Page 多次失败 | 可重新 Init 一次并从第一页重拉；仍失败则降级旧全量接口 |
| sessionId 过期或无效 | 重新 Init 一次并从第一页重拉 |
| 合并条数不等于 Init.total | 不允许静默返回；降级旧全量接口或抛错 |
| 旧接口也失败 | 沿用当前 `throwVolunteerDataTimeoutIfNeeded` 和 `BusinessException` 逻辑 |

重试建议:

- 单页 Page 重试 `2` 次。
- session 失效时最多重新 Init `1` 次。
- 不建议无限重拉，避免上游压力放大。

## 6. 性能策略

首版建议顺序拉 Page，`pageConcurrency=1`。

理由:

- 当前主要问题是单次响应体过大导致超时；分页后单次请求体积已经显著下降。
- 顺序拉页实现简单，和上游 Redis session 语义最稳定。
- 并发拉页会提升总耗时表现，但会放大上游瞬时压力，并增加 session 过期、单页失败和结果排序处理复杂度。

后续如果建会话耗时仍不可接受，再引入小并发:

- 默认并发 `3` 或 `4`。
- 最终合并必须按 `current` 页码排序。
- 任一页失败仍按页重试，不应返回部分结果。

## 7. 配置建议

建议在 `gaotu.zhiyuan` 下增加:

```yaml
gaotu:
  zhiyuan:
    program-data-paged-enabled: true
    program-data-fallback-enabled: true
    program-data-page-retry-times: 2
    program-data-session-reinit-times: 1
    program-data-page-concurrency: 1
```

含义:

| 配置 | 默认 | 说明 |
| --- | --- | --- |
| `program-data-paged-enabled` | `true` | 是否启用 Init + Page 新链路 |
| `program-data-fallback-enabled` | `true` | 分页失败后是否降级旧全量接口 |
| `program-data-page-retry-times` | `2` | 单页失败重试次数 |
| `program-data-session-reinit-times` | `1` | session 失效后重新 Init 次数 |
| `program-data-page-concurrency` | `1` | Page 拉取并发数，首版保持顺序 |

生产灰度时可以先打开分页和降级；分页稳定后，再评估是否关闭旧全量兜底。

## 8. 日志与观测

日志需要能定位 Init、单页、合并和降级问题，但禁止打印完整大 JSON。

建议日志点:

```text
queryAllProgramDataPagedInit areaId batch year prepareType total pages pageSize sessionIdPrefix costMs
queryAllProgramDataPagedPage current pages detailCount retry costMs
queryAllProgramDataPagedMerge total mergedCount distinctPlanMajorDataIdCount missingPlanMajorDataIdCount costMs
queryAllProgramDataFallbackFull reason costMs
```

需要重点观察:

- Init 耗时。
- Page 平均耗时和 P95/P99。
- 单页失败率。
- session 失效次数。
- 合并条数不一致次数。
- 分页降级旧接口次数。
- 建会话整体 `queryAllProgramData` 耗时变化。

## 9. 测试与验收

### 9.1 单元测试

建议覆盖 `GaotuService.queryAllProgramData`:

1. Init 返回 3 页，Page 正常，合并顺序与页码一致。
2. 合并后 `detailList.size == total`。
3. Init 失败时降级旧接口。
4. Page 第一次失败、重试成功。
5. Page 多次失败后重新 Init。
6. session 过期后重新 Init 并从第一页重拉。
7. 合并条数少于 Init.total 时不返回部分结果。
8. `planMajorDataId` 重复时打告警或触发降级，按最终实现策略断言。
9. 分页开关关闭时仍走旧全量接口。
10. 旧接口 `code=-9` 时保留当前“批次内没有查到可报志愿”的特殊提示。

### 9.2 集成验证

使用文档山东样例:

```json
{
  "memberId": 2248,
  "areaId": "370000",
  "batch": "17",
  "score": 516,
  "subjects": "010506",
  "subjectType": "N",
  "year": "2026",
  "prepareType": "VOLUNTEER",
  "tabType": "1"
}
```

验收:

- Init 返回 `total=15526`、`pages=16`、`pageSize=1000`，或以联调时上游实时返回为准。
- Page 从 `1` 拉到 `pages`。
- 合并后 `detailList.size == total`。
- 清洗后的 JSON 可以解析为现有 `VolunteerDataDTO`。
- 建会话生成的 `session_volunteer_{chatSessionId}.json` 可被候选池和 Agent 正常消费。

### 9.3 对话链路验证

分页接入后，需要重点跑现有高风险生产回捞 case:

- 候选规模较大的省份和批次。
- 有城市、专业、学校性质、学费、报考要求筛选的会话。
- 需要替换、增补、排除地区、排除学校、排除专业的方案调整会话。
- 之前出现过“候选池不足”“只命中少量候选”“回复数量和实际方案数量不一致”的场景。

验收标准不是只看接口成功，而是:

- 候选池数量完整。
- 筛选和推荐不因分页合并缺失而变少。
- Agent 回复中的数量口径和工作台可见候选一致。
- 方案调整动作仍能基于完整候选池生成可执行 proposal。

## 10. 实施顺序

建议分三步推进:

1. 先实现 `GaotuClient` 新接口和 `GaotuService` 内部 merge，开关默认可配置，旧接口作为降级。
2. 补充单元测试和山东样例联调，确认合并结果形状兼容当前清洗和文件落盘。
3. 部署测试环境跑建会话、生产回捞 case 和并发回归，观察分页失败率、合并完整性和对话效果。

不建议首版同步改 Agent、候选池协议或前端展示协议。当前问题本质是上游全量数据传输方式变化，业务层应继续拿到完整、旧结构兼容的数据。

## 11. 待确认问题

1. Page 接口 `size` 是否建议正式调用时不传，完全使用 Init 的 session pageSize；还是显式传 `init.pageSize` 以便日志和行为更可控。
2. `isSuccess=false` 但 `code=0` 的异常组合是否可能出现；当前 `ResponseDTO` 没有 `isSuccess` 字段，首版可仍以 `code == 0 && data != null` 为主。
3. `planMajorDataId` 是否在所有省份、所有志愿模式下都稳定非空；如果不是，只能作为告警指标，不能作为硬失败唯一依据。
4. 分页稳定后，旧全量接口降级保留多久，是否需要按环境逐步关闭。
5. 大省大批次下顺序拉页的建会话耗时是否满足产品体验；如果不满足，再引入受控 Page 并发。
