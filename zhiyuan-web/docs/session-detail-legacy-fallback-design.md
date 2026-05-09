# sessionDetail Legacy 兜底入口设计

## 背景

老版本线上会话详情页已经稳定承接过移动端和桌面端的最终方案展示。V2 升级后，默认入口切到 `sessionDetailV2`，由对话区和工作台共同承接候选、草稿、排序方案、审查和对话联动。

迁移期需要考虑两类风险：

- 老会话懒迁移失败，V2 无法正确展示历史方案。
- V2 移动端工作台过重，短期内可能不如老版最终方案页稳定。

因此可以保留老版会话详情页作为兜底入口，但不建议恢复为新版本主链路。

## 结论

保留 legacy 能力的目标是“可回看、可兜底、可回滚”，不是继续扩展两套主流程。

- V2 主链路继续使用 `/sessionDetailV2`。
- Legacy 页面只作为迁移期兜底，不承接 V2 的候选筛选、草稿、排序调整、审查和对话联动。
- Legacy 页面优先只读展示老方案；提交、导出等写操作是否开放需要单独确认。
- 灰度完成并确认 V2 移动端稳定后，legacy 入口应逐步下线。

## 老版参考代码

线上老版本代码位于：

```text
/Users/baiyang/git/zhiyuan.bak/gaokao-volunteer-pc
```

主要参考文件：

```text
src/pages/sessionDetail/index.tsx
src/pages/sessionDetail/style.module.scss
src/pageComponents/sessionDetail/Volunteer/index.tsx
src/pageComponents/sessionDetail/Volunteer/style.module.scss
src/pageComponents/sessionDetail/MessageList/index.tsx
src/pageComponents/sessionDetail/MessageList/style.module.scss
```

其中 `Volunteer` 的移动端做法主要是：

- 顶部标题、按钮和学费筛选纵向堆叠。
- 冲稳保 tab 三等分压缩展示。
- 院校/专业组头部允许换行，右侧录取率块缩小。
- 专业明细仍保留 `Table`，移动端通过横向滚动查看。
- 历年分数线通过弹层查看。

这些原则可以参考，但不应直接复制到 V2 工作台，因为 V2 还包含候选筛选、草稿篮、方案调整等交互。

## 路由方案

建议新增明确的 legacy 路由：

```text
/sessionDetailLegacy
```

可选兼容参数：

```text
/sessionDetailLegacy?tenantId=...&chatSessionId=...
/sessionDetailV2?legacy=1
```

不建议重新占用 `/sessionDetail` 作为默认入口，避免新老入口语义混淆。

## 入口策略

### 1. V2 迁移失败兜底

当 V2 工作台加载失败、懒迁移失败或 `planningState` 异常时，页面可展示轻量提示：

```text
当前工作台暂时无法展示历史方案，可以先查看旧版方案。
```

按钮跳转：

```text
查看旧版方案 -> /sessionDetailLegacy?tenantId=...&chatSessionId=...
```

### 2. 内部灰度入口

灰度期间可在 V2 页头或调试区保留内部入口：

```text
旧版方案
```

仅对内部账号、灰度环境或带调试参数时展示，避免普通用户看到两套入口。

### 3. 移动端临时兜底

如果移动端 V2 工作台仍存在严重展示问题，可以短期对移动端失败态提供 legacy 入口。不要默认把所有移动端用户切回 legacy，否则会绕开 V2 迁移验证。

## 功能边界

Legacy 页面第一阶段建议只保留：

- 历史消息查看。
- 老方案展示。
- 冲稳保切换。
- 院校/专业组折叠。
- 历年分数线弹层。
- 导出入口。

第一阶段建议禁用或隐藏：

- 重新生成推荐。
- 提交方案。
- 修改学费范围后重算。
- 对话触发方案修改。
- V2 草稿、排序、审查相关操作。

原因是这些写操作可能继续修改老 JSON 或会话状态，与 V2 `planningState` 产生双写不一致。

## 数据接口

Legacy 页面应继续使用老接口作为只读兜底：

```text
GET /gaotu-assistant-bot/chat/{tenantId}/volunteer/recommend-list?chatSessionId=...
POST /gaotu-assistant-bot/chat/{tenantId}/volunteer/export?chatSessionId=...
```

如需开放提交，需要单独确认：

```text
POST /gaotu-assistant-bot/chat/{tenantId}/volunteer/submit?chatSessionId=...
```

默认不建议在 legacy 兜底页开放提交，除非明确要求保留老流程的完整闭环。

## 代码落地建议

建议新建独立目录，避免和 V2 主链路互相污染：

```text
src/pages/sessionDetailLegacy/index.tsx
src/pages/sessionDetailLegacy/style.module.scss
src/pageComponents/sessionDetailLegacy/
```

迁移老代码时遵循：

- 复制老版展示组件后最小改造路径别名、接口 import 和类型。
- 移除或隐藏会产生写入的按钮。
- 保留老版移动端样式，但删除和当前项目无关的入口逻辑。
- 不复用 V2 `WorkspacePanel` 内部状态。
- 不把 legacy 页面写入 `planningState`。

## 移动端对齐口径

`gaotu-mobile-v2.0.6` 的移动端优化不是把志愿表和对话平铺成两个常驻 tab，而是：

- 以对话沉浸页作为移动端主视图。
- 通过快捷入口打开“志愿方案”“用户信息”“会话列表”。
- 志愿方案在全屏 `Drawer` 中展示。
- PC 端仍保留左右分栏。

因此 legacy 兜底页和 V2 移动端都应优先沿用这个外壳逻辑：

- `/sessionDetailLegacy` 移动端默认展示对话，通过“志愿方案”快捷入口打开老版志愿表抽屉。
- `/sessionDetailV2` 移动端默认展示对话，通过“看看现在的方案”或对话联动打开工作台抽屉。
- 工作台/志愿表内部继续分别使用自己的内容结构，不能强行复用彼此的数据模型。

## 验证清单

1. 老会话有最终方案：legacy 可展示最终方案。
2. 老会话只有临时方案：legacy 可展示临时推荐。
3. 方案文件缺失：legacy 显示空态，不阻断 V2。
4. 移动端 375px：冲稳保 tab、院校头、专业表格横滑可用。
5. 桌面端：旧版折叠列表和历年分数线弹层可用。
6. 从 V2 跳 legacy 后，浏览器返回能回到 V2。
7. legacy 不写入 `planningState`。
8. legacy 不自动触发推荐重算。

## 下线标准

满足以下条件后，可以移除或隐藏 legacy 入口：

- V2 懒迁移真实样本通过率稳定。
- V2 移动端可以查看方案且无横向撑屏。
- 灰度日志中迁移失败率低于可接受阈值。
- 线上客服或用户反馈不再依赖旧版方案页兜底。
- 已确认老接口的导出、提交等能力不再需要给用户直接访问。
