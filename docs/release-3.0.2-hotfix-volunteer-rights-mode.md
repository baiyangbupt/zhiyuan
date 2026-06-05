# release-3.0.2 hotfix: volunteer daily rights limit

## 背景

高考出分后，主站会切入真实智能填报（`prepareType=VOLUNTEER`）数据。此前 3.0.2 版本的权益模型只按用户等级和建会话总量限制判断，不区分模拟填报/智能填报，也不支持按天限制。

历史文档已记录目标规则：智能填报期间，普通用户每天最多创建 2 个智能填报会话。本 hotfix 按该口径实现，不采用“非 SUPER_VIP 全局禁用”的方案。

## hotfix 目标

对 `CreateSession` 增加智能填报每日限制：

- `SUPER_VIP`：不受该每日 2 次限制，仍走原有权益模型。
- 非 `SUPER_VIP`：当本次创建请求 `prepareType.code=VOLUNTEER` 时，每天最多创建 2 个智能填报会话。
- `PREDICT` 模拟填报：本 hotfix 不新增按天限制，继续沿用 3.0.2 原有总量限制。

拒绝提示：

- `智能填报期间，非SUPER_VIP用户每天最多创建2个智能填报会话`

## 代码变更点

1. `ChatSessionBizService.createChatSession(...)`

创建会话的真实入口能拿到 `CreateSessionReq.prepareType`，因此权益检查改为传入当前请求的 `prepareType`：

```java
userBizService.checkRights(userId, OperateCheckPoint.CreateSession, createSessionReq.getPrepareType());
```

同时创建会话参数校验要求 `prepareType.code` 必填，避免缺失时被后续推荐查询默认成 `PREDICT` 而绕过智能填报日限。

2. `UserBizService.checkRights(...)`

保留原有两个参数方法，新增带 `CreateSessionReq.PrepareType` 的重载方法。`/check-rights` 接口增加可选 `prepareType` 参数，未传时保持兼容，传入 `VOLUNTEER` 时可使用同一套日限逻辑做预检查。

当满足以下条件时进入智能填报每日限制：

- `checkPoint=CreateSession`
- `prepareType.code=VOLUNTEER`
- 当前用户等级不是 `SUPER_VIP`

统计方式：

- 查询用户当天创建的会话。
- 读取每个会话的 `userScoreDetail` extra-data。
- 解析其中的 `prepareType.code`，只统计 `VOLUNTEER` 会话。
- 达到 2 个后拒绝本次创建。

3. `GaotuProperties`

移除错误方案中的 `volunteerSuperVipOnly` 配置字段。本 hotfix 不需要新增配置项。

## 为什么不采用全局 SUPER_VIP-only

`volunteer-super-vip-only=true` 会导致所有非 `SUPER_VIP` 用户在 `CreateSession / ModifyScore / DoChat` 上直接不可用，和“每天 2 个智能填报会话”的目标不一致。

该方案也无法区分 `PREDICT` 和 `VOLUNTEER`，会误伤模拟填报和已有会话对话能力，因此已撤销。

## prepareType 来源与一致性

`prepareType` 的权威来源是创建会话请求 `CreateSessionReq.prepareType`：

- PC 前端创建会话时，先由用户选择的填报政策/批次推导填报类型，再随创建会话请求提交。
- 外部集成初始化接口也必须在 `createSession.prepareType` 中传入填报类型，智能填报使用 `code=VOLUNTEER`，模拟填报使用 `code=PREDICT`。
- 后端创建会话入口现在要求 `prepareType.code` 必填；缺失时直接拒绝，避免后续推荐查询默认成 `PREDICT` 导致权益规则不一致。
- 会话创建成功后，完整创建请求会写入 `userScoreDetail` extra-data。后续会话列表、详情、日限统计均以该持久化数据作为会话填报类型来源。
- `/check-rights` 的 `prepareType` 参数是兼容性的预检查能力；最终是否能创建仍以 `createChatSession` 中的校验和权益检查为准。

需要注意：`UserInfoByTokenRes.toCreateSessionReq()` 当前不补 `prepareType`，不能把它作为最终创建会话 payload 直接使用；如果后续新入口复用该转换结果，必须在调用创建接口前补齐 `prepareType`。

## 历史版本和历史数据影响

本 hotfix 不涉及数据库结构变更，也不会修改已有会话数据。直接替换 3.0.2 的 Java 服务后，影响范围如下：

- 已创建的历史会话可以继续打开、对话、导出、排序和审查，不因本次权益规则改变而被重写。
- 日限只作用于新的 `CreateSession` 请求，不限制已有会话的 `DoChat` 和 `ModifyScore`。
- 当天已创建的历史会话只有在 `userScoreDetail.prepareType.code=VOLUNTEER` 且能正常解析时，才会计入当天智能填报 2 次限制。
- 老数据如果没有 `prepareType`，不会被当作 `VOLUNTEER` 计数；但新的创建请求必须传 `prepareType.code`，否则会被拒绝。
- 本 hotfix 移除了 `volunteer-super-vip-only` 配置，不需要在生产配置中新增该项；上线以替换 jar 并重启 Java 服务为准。

上线前需要确认所有生产创建入口都能传入 `prepareType`：PC 创建入口、外部 integration initialize 接口、以及任何后台/脚本创建入口。

## 当前限制与后续 TODO

- 本 hotfix 只限制创建智能填报会话，不处理 `ModifyScore` 和 `DoChat`。
- `/check-rights` 已支持可选 `prepareType` 参数；但现有 3.0.2 前端部分创建入口在打开表单前还不知道填报类型，最终创建接口仍是权威拦截点。
- 模拟填报每天 10 个会话的规则本次未实现，仍沿用 3.0.2 原有总量限制。
