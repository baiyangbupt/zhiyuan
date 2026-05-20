# 外部授权初始化会话接口设计

本文档记录“外部系统携带授权用户与采集参数，初始化智愿会话并生成方案”的后端接口设计与当前实现。目标是在不模拟浏览器多步操作的情况下，让外部系统一次请求完成会话创建、用户采集信息写入、初始方案生成，并拿到可定位会话和获取方案的能力。

当前实现状态：第一阶段已落地同步接口、幂等表、DTO、Controller、Service 和单测。

## 1. 目标

外部系统调用一个后端接口，传入授权用户和前端采集流程等价的配置参数，系统完成：

1. 创建会话。
2. 写入成绩、选科、批次、省份、意向专业、意向地域、身体约束等采集信息。
3. 生成候选池、初始推荐和排序方案。
4. 写入欢迎语或初始化对话上下文。
5. 返回 `chatSessionId`、页面定位 URL、工作台摘要和后续获取方案的接口信息。

该接口面向系统集成，不直接暴露给普通前端页面。

## 2. 当前可复用链路

现有能力：

- `POST /gaotu-assistant-bot/chat/{tenantId}/session/create`
  - 入参：`CreateSessionReq`
  - 已完成会话创建、权益校验、成绩信息保存、全量志愿数据拉取、本地 JSON 文件写入、OSS 异步上传、用户画像初始化和欢迎语写入。
- `POST /gaotu-assistant-bot/inner/planning/{tenantId}/session/candidate-pool/generate`
  - 生成候选池。
- `POST /gaotu-assistant-bot/inner/planning/{tenantId}/session/initial-recommendation/generate`
  - 生成初始推荐。
- `POST /gaotu-assistant-bot/inner/planning/{tenantId}/session/ordered-plan/generate`
  - 生成排序方案。
- `GET /gaotu-assistant-bot/inner/planning/{tenantId}/session/workspace-state`
  - 返回工作台轻量状态，适合外部初始化后做摘要回传。

新接口应优先编排这些既有 service 方法，不复制采集、拉数据、画像和规划生成逻辑。

## 3. 接口定义

### 3.1 URL

```http
POST /gaotu-assistant-bot/chat/{tenantId}/integration/session/initialize
```

示例：

```http
POST https://www.gaotuzhiyuan.com/gaotu-assistant-bot/chat/1/integration/session/initialize
```

### 3.1.1 稳定版本入口

从 `3.0.2` 开始，对外部系统建议使用版本化稳定入口：

```http
POST /gaotu-assistant-bot/chat/{tenantId}/integration/v1/session/initialize
```

兼容策略：

- `v1` 的请求和响应结构与当前 `session/initialize` 保持兼容。
- 既有无版本路径 `POST /integration/session/initialize` 作为兼容别名保留至少一个发布周期。
- 新增可选字段必须保持向后兼容；字段缺失时按默认行为处理。
- 后续破坏性变更必须新开 `v2`，不能直接改变 `v1` 语义。

### 3.2 授权

当前生产已有一条通过 token 自动完成用户授权的链路：

1. 外部系统或前端先调用：

   ```http
   POST /gaotu-assistant-bot/chat/user/login/by-token
   ```

   入参为 `UserTokenLoginRequest`，后端会调用高途 `getUserInfoByToken` 获取用户信息，并写入或更新本系统用户与 `UserCredential`。

2. 登录成功后返回本系统 `loginToken`。

3. 后续业务接口通过请求头进入 `LoginInterceptor`：

   ```http
   tk: <loginToken>
   pf: <platform/channel>
   ```

   拦截器会校验 `UserCredential.loginToken`，并写入 `UserInfoThreadLocal`，后续 `ChatSessionBizService.createChatSession()` 直接使用当前授权用户。

因此新接口第一版应复用现有登录态，不新增独立 `X-Zhiyuan-Integration-Key`。接口路径不要放在 `/inner/**` 下，因为当前 `WebConfig` 对 `/inner/**` 排除了 `LoginInterceptor`，无法自动获得当前授权用户。

调用要求：

```http
tk: <loginToken>
pf: WEB
X-Zhiyuan-External-Request-Id: <external-request-id>
```

说明：

- `tk` 为 `login/by-token` 返回的本系统 `loginToken`。
- `pf` 为登录后业务请求头，当前联调请固定传 `WEB`。后端按 `AuthTypeEnum` 枚举名校验，不能传小写 `web`。
- `X-Zhiyuan-External-Request-Id` 建议与 body 中 `externalRequestId` 保持一致，第一版实现以 body 字段为准。

后端校验：

- 复用 `LoginInterceptor` 校验 `tk/pf`。
- 从 `UserInfoThreadLocal` 读取当前授权用户。
- `externalRequestId` 用于幂等，避免外部系统重试创建重复会话。
- 需要记录调用方渠道、授权用户 ID、外部请求 ID、会话 ID、耗时和生成结果。

如后续需要系统级防伪，可在现有用户 token 登录态之外再叠加 HMAC：

```http
X-Zhiyuan-Timestamp: 1710000000000
X-Zhiyuan-Signature: hmac_sha256(secret, timestamp + "\n" + body)
```

## 4. 请求结构

### 4.1 字段结构

```json
{
  "externalRequestId": "partner-20260509-0001",
  "createSession": {
    "...": "CreateSessionReq 原有字段"
  },
  "generationOptions": {
    "generateCandidatePool": true,
    "generateInitialPlan": true,
    "generateOrderedPlan": true,
    "forceRegenerate": false,
    "returnWorkspaceState": true
  },
  "returnOptions": {
    "webBaseUrl": "https://www.gaotuzhiyuan.com",
    "pathMode": "assistant-pc"
  }
}
```

字段说明：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `externalRequestId` | 是 | 外部请求幂等键。 |
| `createSession` | 是 | 复用前端采集创建会话的 `CreateSessionReq`。 |
| `generationOptions` | 否 | 控制是否同步生成候选池、初始方案、排序方案，并返回工作台轻量状态。默认全开。 |
| `returnOptions.pathMode` | 否 | `assistant-pc` 或 `root`，用于返回页面 URL。正式生产默认 `assistant-pc`。 |

用户身份不放在 body 中，以 `tk/pf` 授权结果为准。`createSession.userName` 仅作为当前被服务学员的展示姓名，不参与授权身份判断。

### 4.1.1 学员展示姓名

外部系统如果希望详情页展示所服务学员姓名，可在 `createSession.userName` 中传入姓名：

```json
{
  "externalRequestId": "partner-20260509-0001",
  "createSession": {
    "botId": 1,
    "userName": "高翔",
    "...": "其他采集字段"
  }
}
```

展示规则：

- 后端将 `createSession.userName` 写入会话 `userName`。
- 前端详情页读取会话详情中的 `userName`，在填报类型标签前展示，例如：`高翔` `模拟填报`。
- `userName` 缺失、为空字符串或仅空白时，前端不展示姓名标签。
- 该字段表达“当前方案服务的学员”，不表示当前授权调用方身份；授权身份仍以 `tk/pf` 登录态为准。

### 4.2 完整请求示例

```bash
curl -X POST 'https://www.gaotuzhiyuan.com/gaotu-assistant-bot/chat/1/integration/session/initialize' \
  -H 'Content-Type: application/json' \
  -H 'tk: ${LOGIN_TOKEN}' \
  -H 'pf: WEB' \
  -H 'X-Zhiyuan-External-Request-Id: partner-20260509-0001' \
  -d '{
    "externalRequestId": "partner-20260509-0001",
    "createSession": {
      "botId": 1,
      "userName": "张同学",
      "province": {
        "code": "130000",
        "name": "河北"
      },
      "examYear": 2026,
      "sex": {
        "code": "female",
        "name": "女"
      },
      "subjectType": {
        "code": "WL",
        "desc": "物理"
      },
      "subjectList": [
        {
          "isFirst": 1,
          "subjectType": "first",
          "value": "01",
          "name": "物理"
        },
        {
          "isFirst": 0,
          "subjectType": "optional",
          "value": "05",
          "name": "化学"
        },
        {
          "isFirst": 0,
          "subjectType": "optional",
          "value": "06",
          "name": "生物"
        }
      ],
      "subjectScoreList": [
        {
          "subject": "01",
          "subjectName": "物理",
          "score": 85
        },
        {
          "subject": "05",
          "subjectName": "化学",
          "score": 82
        },
        {
          "subject": "06",
          "subjectName": "生物",
          "score": 80
        }
      ],
      "prepareType": {
        "code": "PREDICT",
        "desc": "模拟填报"
      },
      "batch": {
        "code": "B1",
        "name": "本科批",
        "score": 448,
        "level": "本科",
        "pos": 120000
      },
      "totalScore": 560,
      "totalScorePos": 58000,
      "filterType": "2",
      "specialPlan": false,
      "minority": false,
      "colorBlindness": false,
      "bonusPolicy": false,
      "bonusScore": 0,
      "preferredMajors": [
        {
          "majorSubId": "0201",
          "majorSubName": "经济学类"
        },
        {
          "majorSubId": "0301",
          "majorSubName": "法学类"
        }
      ],
      "unacceptableMajors": [
        {
          "majorId": "101101",
          "majorName": "护理学"
        }
      ],
      "preferredRegions": [
        {
          "provinceId": "110000",
          "provinceName": "北京"
        },
        {
          "provinceId": "120000",
          "provinceName": "天津"
        }
      ],
      "strategyType": {
        "code": "balanced",
        "name": "稳妥型"
      },
      "tuitionRange": {
        "min": 0,
        "max": 30000
      },
      "acceptForeignSchool": false
    },
    "generationOptions": {
      "generateCandidatePool": true,
      "generateInitialPlan": true,
      "generateOrderedPlan": true,
      "returnWorkspaceState": true,
      "forceRegenerate": false
    },
    "returnOptions": {
      "webBaseUrl": "https://www.gaotuzhiyuan.com",
      "pathMode": "assistant-pc"
    }
  }'
```

最小必需字段以现有 `session/create` 能成功创建会话为准。通常至少需要：

- `botId`
- `province.code/name`
- `examYear`
- `subjectType.code`
- `subjectList`
- `subjectScoreList`
- `batch.code/name/level`
- `totalScore`
- `totalScorePos`

## 5. 响应结构

### 5.1 成功响应示例

实际接口外层仍使用统一 `BaseResponse`：

```json
{
  "code": 0,
  "msg": "success",
  "data": {
    "chatSessionId": 1002,
    "tenantId": 1,
    "externalRequestId": "partner-20260509-0001",
    "created": true,
    "studentName": "高翔",
    "sessionUrl": "https://www.gaotuzhiyuan.com/assistant-pc/sessionDetailV2?chatSessionId=1002",
    "legacySessionUrl": "https://www.gaotuzhiyuan.com/assistant-pc/sessionDetailLegacy?chatSessionId=1002",
    "planning": {
      "phase": "ordered",
      "version": 3,
      "candidateTotal": 200,
      "draftTotal": 45,
      "orderedTotal": 45,
      "tierCounts": {
        "冲": 18,
        "稳": 13,
        "保": 14
      }
    },
    "apis": {
      "workspaceState": "/gaotu-assistant-bot/inner/planning/1/session/workspace-state?chatSessionId=1002",
      "orderedPlan": "/gaotu-assistant-bot/inner/planning/1/session/ordered-plan?chatSessionId=1002",
      "export": "/gaotu-assistant-bot/inner/chat/1/volunteer/export?chatSessionId=1002"
    }
  }
}
```

`created=false` 表示命中幂等记录，返回之前创建的会话定位信息。`studentName` 为展示字段，取首次成功创建会话时保存的 `userName`；如果创建时未提供姓名，则该字段可为空或省略。

### 5.2 幂等命中示例

同一个授权用户、同一个 `externalRequestId`、同一个请求体重复调用：

```json
{
  "code": 0,
  "msg": "success",
  "data": {
    "chatSessionId": 1002,
    "tenantId": 1,
    "externalRequestId": "partner-20260509-0001",
    "created": false,
    "sessionUrl": "https://www.gaotuzhiyuan.com/assistant-pc/sessionDetailV2?chatSessionId=1002"
  }
}
```

### 5.3 常见错误

未带 `tk/pf` 或 token 无效：

```json
{
  "code": 800,
  "msg": "不合法请求"
}
```

缺少 `externalRequestId`：

```json
{
  "code": 110,
  "msg": "externalRequestId不能为空"
}
```

同一个 `externalRequestId` 使用了不同请求体：

```json
{
  "code": 110,
  "msg": "externalRequestId已被不同请求使用"
}
```

同一个 `externalRequestId` 仍在处理中：

```json
{
  "code": 110,
  "msg": "同一externalRequestId正在处理中"
}
```

## 6. 执行流程

1. 校验集成授权。
2. 根据 `externalRequestId` 查幂等记录。
3. 从 `UserInfoThreadLocal` 读取授权用户，禁止 body 覆盖用户身份。
4. 调用 `createChatSession(tenantId, createSessionReq)`。
5. 调用 `generateCandidatePool()`。
6. 调用 `generateInitialPlan()`。
7. 调用 `generateOrderedPlan()`。
8. 可选调用审查或生成 workspace-state。
9. 保存幂等记录和初始化日志。
10. 返回轻量定位结果，不返回完整 `PlanningStateDTO`。

## 7. 幂等设计

第一版需要新增一张幂等表，或复用已有 extra data 记录外部请求关系。

建议新增表：

```text
integration_session_request
```

核心字段：

| 字段 | 说明 |
| --- | --- |
| `tenant_id` | 租户 ID |
| `external_request_id` | 外部幂等键 |
| `user_id` | 现有 token 授权得到的本系统用户 ID |
| `platform` | `pf` 渠道 |
| `chat_session_id` | 创建出的会话 ID |
| `status` | `PROCESSING / SUCCESS / FAILED` |
| `request_hash` | 请求体 hash，用于判断同 key 不同参数 |
| `error_message` | 失败原因 |
| `created_at / updated_at` | 时间 |

幂等规则：

- 同一个 `tenantId + userId + externalRequestId` 成功后再次请求，直接返回原会话。
- 同 key 但 `request_hash` 不同，返回参数冲突错误。
- `PROCESSING` 超时后允许重试或人工清理。

## 8. 返回方案能力

外部系统拿到 `chatSessionId` 后，可以使用：

```http
GET /gaotu-assistant-bot/inner/planning/{tenantId}/session/workspace-state?chatSessionId={id}
GET /gaotu-assistant-bot/inner/planning/{tenantId}/session/ordered-plan?chatSessionId={id}
POST /gaotu-assistant-bot/inner/chat/{tenantId}/volunteer/export?chatSessionId={id}
```

示例：

```bash
curl 'https://www.gaotuzhiyuan.com/gaotu-assistant-bot/inner/planning/1/session/workspace-state?chatSessionId=1002'

curl 'https://www.gaotuzhiyuan.com/gaotu-assistant-bot/inner/planning/1/session/ordered-plan?chatSessionId=1002'

curl -X POST 'https://www.gaotuzhiyuan.com/gaotu-assistant-bot/inner/chat/1/volunteer/export?chatSessionId=1002' \
  --output volunteer-plan.xlsx
```

页面定位：

```text
/assistant-pc/sessionDetailV2?chatSessionId={id}
/assistant-pc/sessionDetailLegacy?chatSessionId={id}
```

如果部署在根路径环境，`returnOptions.pathMode` 可传 `root`，返回 URL 会变为：

```text
/sessionDetailV2?chatSessionId={id}
/sessionDetailLegacy?chatSessionId={id}
```

## 9. 测试要求

后端单测：

- 授权失败返回明确错误。
- 参数缺失返回明确错误。
- 首次调用创建会话并生成方案。
- 同一 `externalRequestId` 重试返回同一 `chatSessionId`。
- 同一 `externalRequestId` 但请求体不同返回冲突。
- 同一 `externalRequestId` 仍在 `PROCESSING` 时返回处理中错误。
- `generationOptions` 关闭候选池、初始方案、排序方案时不会调用对应生成步骤。
- `returnWorkspaceState=false` 时不读取工作台轻量状态。
- `pathMode=root` 时返回根路径页面 URL。
- 生成失败时记录失败状态，不留下误判为成功的幂等记录。
- `createSession.userName` 传入时，会话详情和初始化响应可返回对应学员展示姓名。
- 未传 `createSession.userName` 时，详情页不展示空姓名标签。
- 版本化路径 `/integration/v1/session/initialize` 与无版本兼容路径行为一致。

集成验证：

- 使用一份真实 `CreateSessionReq` 初始化会话。
- 传入 `createSession.userName="高翔"`，打开 `sessionUrl` 后详情页在“模拟填报”前展示“高翔”。
- 检查消息列表有欢迎语。
- 检查 `workspace-state` 有方案摘要。
- 检查 `/assistant-pc/sessionDetailV2` 能定位会话。
- 检查导出接口可用。

## 10. 实现建议

第一阶段实现：

1. 已新增 DTO：
   - `ExternalSessionInitializeReq`
   - `ExternalSessionInitializeRes`
   - `ExternalGenerationOptionsDTO`
   - `ExternalReturnOptionsDTO`
2. 已新增 controller：
   - `IntegrationSessionController`
3. 已新增 service：
   - `IntegrationSessionService`
4. 已复用：
   - `ChatSessionBizService.createChatSession`
   - `PlanningStateService.generateCandidatePool`
   - `PlanningStateService.generateInitialPlan`
   - `PlanningStateService.generateOrderedPlan`
   - `PlanningStateService.getPlanningWorkspaceState`
5. 已新增幂等表和 mapper：
   - `integration_session_request`
   - `IntegrationSessionRequestMapper`
6. 已补充 controller/service 单测：
   - `IntegrationSessionControllerTest`
   - `IntegrationSessionServiceTest`

第二阶段优化：

- 支持异步模式：先返回 `PROCESSING`，外部轮询初始化结果。
- 支持 HMAC 签名。
- 支持按外部用户自动创建或绑定本系统用户。
- 支持返回更完整的结构化方案摘要，但不返回完整候选池明细。
