# Session Create Performance Optimization

## Context

`POST /gaotu-assistant-bot/chat/{tenantId}/session/create` 在切到 `sessionDetailV2` 后成为更敏感的首屏关键链路。

本轮排查中，前端创建会话后经常在跳转对话页前失败。进一步排查发现并不是 `createSession` 业务失败，而是后端同步链路过长，前端先超时断开，最终在服务端日志中表现为 `Broken pipe`。

## Observed Bottleneck

以一次真实请求为例：

- `queryAllProgramData`: `20786ms`
- `cleanVolunteerData`: `624ms`
- `writeLocalVolunteerFile`: `225ms`
- `uploadVolunteerFileToOss`: `69659ms`

可以看到同步上传 OSS 是主瓶颈，单步接近 `70s`，已经足以让前端默认 `30s` 超时必现。

## Existing File Supply Chain

当前原始志愿数据链路如下：

1. `createChatSession()`
2. 调高途全量接口获取原始志愿数据
3. 清洗结构
4. 写本地文件 `session_volunteer_{chatSessionId}.json`
5. 上传同一份文件到 OSS
6. 返回会话信息

后续读取 `loadChatSessionVolunteerData()` 的策略是：

1. 优先读取本地文件
2. 本地文件不存在时，再从 OSS 下载到本地
3. 解析本地文件并返回

这意味着：

- 创建会话成功并不依赖“上传完成”
- 只要本地文件已经落盘，当前机器上的后续对话/推荐链路就可以继续工作
- OSS 更偏向跨实例、重启恢复、文件兜底

## Decision

将 `createSession` 中的 OSS 上传从同步链路改为异步分发。

保留同步步骤：

- 落库会话
- 保存用户分数信息
- 拉取全量志愿数据
- 清洗
- 本地写文件

改为异步步骤：

- 上传原始志愿文件到 OSS

## Implementation

### 1. Add Step Timing Logs

在 `ChatSessionBizService.createChatSession()` 中补充分段耗时日志，覆盖：

- `saveSession`
- `getRecommendProgramNum`
- `saveScoreInfo`
- `queryAllProgramData`
- `cleanVolunteerData`
- `writeLocalVolunteerFile`
- `dispatchUploadVolunteerFileToOss`
- `saveUserInitProfile`
- `sendWelcome`
- `updateSessionStatus`
- `getBot`
- `finish`

### 2. Async Upload Service

新增 `VolunteerFileAsyncService`：

- 使用现有 Spring `@Async` 线程池
- 后台执行 `AliOSSService.uploadFile()`
- 上传失败只记录日志，不打断已经成功创建的会话

### 3. Main-Path Change

`ChatSessionBizService.createChatSession()` 在本地写文件后：

- 仅派发异步上传任务
- 不再等待 OSS 返回

## Failure Semantics

异步上传后，失败语义调整为：

- 本地写文件失败：仍然视为创建失败
- OSS 上传失败：会话创建成功，但失去“跨实例 / 本地文件缺失时的 OSS 兜底”

这是可接受的，因为：

- 当前联调环境主要问题是首屏创建超时
- OSS 上传失败可以后续补偿
- 本地文件已经满足当前会话主链路运行条件

## Follow-Up

后续建议继续推进：

1. 为异步上传增加补偿任务或重试机制
2. 在文件元数据中标记 OSS 上传状态，便于观测
3. 继续优化 `queryAllProgramData`，把建会话总耗时压到稳定的首屏可接受范围
4. 在创建次数统计中排除明显失败或废弃的测试会话，避免超时重试放大限额问题
