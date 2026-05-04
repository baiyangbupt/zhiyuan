# Session Create Timeout Resilience

## Context

`sessionDetailV2` 切为默认入口后，创建会话成功与否直接决定是否能进入对话工作台。

本轮联调中出现两类表象：

- 创建后前端提示失败，无法进入对话页
- 后端最终日志显示 `session/create` 为 `200`，但伴随 `Broken pipe`

最终确认根因不是前端路由本身，而是创建链路过长，前端先超时断开。

## Problem Split

### 1. Request Timeout

前端默认请求超时原为 `30000ms`。

而后端真实链路里：

- 全量志愿数据查询约 `20s`
- OSS 上传约 `70s`

总耗时远超 `30s`，导致前端一定先报错。

### 2. Empty Create Response Handling

在部分超时或异常场景下，前端侧表现为：

- `code === 0`
- 但 `data` 缺失或当前分支未能直接消费到 `data.id`

旧逻辑把它直接判成创建失败，无法回查已成功落库的会话。

### 3. Browser Compatibility on V2

`sessionDetailV2` 新增 `useMediaQuery()`，使用 `matchMedia.addEventListener('change', ...)`。

在低版本 WebView / Safari 中该 API 不稳定，可能在刚进入 V2 页面时直接抛运行时错误。

## Decision

前端先做三层兜底：

1. 临时把全局请求超时提升到 `180000ms`
2. 创建会话成功但缺少返回实体时，回查最新会话继续进入 V2
3. `useMediaQuery()` 兼容 `addListener/removeListener`
4. Next 开发环境 rewrite 代理超时同步提升到 `180000ms`

## Implementation

### 1. Raise Request Timeout

在 `src/service/index.ts` 中把全局请求超时从 `30000ms` 调整为 `180000ms`。

这是当前联调阶段的止血方案，不等价于后端性能问题已经解决。

### 2. Raise Next Dev Proxy Timeout

在 `next.config.mjs` 中设置 `experimental.proxyTimeout = 180000`。

原因是 Next 开发环境对 rewrite 代理默认只给 `30000ms`，即使 axios 自身超时已放宽，`next dev` 代理层仍会先以 `socket hang up / ECONNRESET` 终止请求。

### 3. Add Created-Session Resolver

新增 `src/utils/session.ts`：

- 正常情况直接使用 `createSession` 返回的会话实体
- 若返回体缺失，则调用会话列表接口回查最新会话

当前由以下创建入口复用：

- `src/pages/session/index.tsx`
- `src/pages/customerDetail/index.tsx`
- `src/pageComponents/customerDetail/CustomerDetailFlow/index.tsx`

### 4. Harden `useMediaQuery`

在 `src/hooks/useMediaQuery.ts` 中：

- 先判断 `window.matchMedia` 是否存在
- 优先使用 `addEventListener/removeEventListener`
- 不支持时回退到 `addListener/removeListener`

## Expected Result

当前前端应具备以下行为：

- backend 耗时在 `180s` 内时，不再因前端默认超时直接失败
- 即使创建响应体不完整，也能尽量回查并进入 `sessionDetailV2`
- 低版本 WebView 不再因 `matchMedia` 监听 API 差异在 V2 首屏报错

## Follow-Up

后续仍需以后端优化为主：

1. 把 `session/create` 主链路压缩到正常首屏可接受范围
2. 在 backend 异步化 OSS 上传后，再视情况把前端超时回收
3. 若创建返回体仍偶发缺失，需要补查 backend / gateway 的响应链路
