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
pf: <platform/channel>
X-Zhiyuan-External-Request-Id: <external-request-id>
```

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

```json
{
  "externalRequestId": "partner-20260509-0001",
  "createSession": {
    "...": "CreateSessionReq 原有字段"
  },
  "generationOptions": {
    "generateCandidatePool": true,
    "generateInitialRecommendation": true,
    "generateOrderedPlan": true,
    "runReview": true,
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
| `generationOptions` | 否 | 控制是否同步生成候选池、初始推荐、排序和审查。默认全开。 |
| `returnOptions.pathMode` | 否 | `assistant-pc` 或 `root`，用于返回页面 URL。正式生产默认 `assistant-pc`。 |

用户身份不放在 body 中，以 `tk/pf` 授权结果为准。`createSession.userName` 仅作为会话展示名称。

## 5. 响应结构

```json
{
  "chatSessionId": 1002,
  "tenantId": 1,
  "externalRequestId": "partner-20260509-0001",
  "created": true,
  "sessionUrl": "https://www.gaotuzhiyuan.com/assistant-pc/sessionDetailV2?chatSessionId=1002",
  "legacySessionUrl": "https://www.gaotuzhiyuan.com/assistant-pc/sessionDetailLegacy?chatSessionId=1002",
  "planning": {
    "phase": "ordered",
    "version": 3,
    "candidateTotal": 200,
    "draftTotal": 45,
    "orderedTotal": 45,
    "tierCounts": {
      "sprint": 18,
      "steady": 13,
      "protect": 14
    }
  },
  "apis": {
    "workspaceState": "/gaotu-assistant-bot/inner/planning/1/session/workspace-state?chatSessionId=1002",
    "orderedPlan": "/gaotu-assistant-bot/inner/planning/1/session/ordered-plan?chatSessionId=1002",
    "export": "/gaotu-assistant-bot/inner/chat/1/volunteer/export?chatSessionId=1002"
  }
}
```

`created=false` 表示命中幂等记录，返回之前创建的会话定位信息。

## 6. 执行流程

1. 校验集成授权。
2. 根据 `externalRequestId` 查幂等记录。
3. 从 `UserInfoThreadLocal` 读取授权用户，禁止 body 覆盖用户身份。
4. 调用 `createChatSession(tenantId, createSessionReq)`。
5. 调用 `generateCandidatePool()`。
6. 调用 `generateInitialRecommendation()`。
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

页面定位：

```text
/assistant-pc/sessionDetailV2?chatSessionId={id}
/assistant-pc/sessionDetailLegacy?chatSessionId={id}
```

## 9. 测试要求

后端单测：

- 授权失败返回明确错误。
- 参数缺失返回明确错误。
- 首次调用创建会话并生成方案。
- 同一 `externalRequestId` 重试返回同一 `chatSessionId`。
- 同一 `externalRequestId` 但请求体不同返回冲突。
- 生成失败时记录失败状态，不留下误判为成功的幂等记录。

集成验证：

- 使用一份真实 `CreateSessionReq` 初始化会话。
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
