# 最终 jar 验收（新求解器默认值 + 审查修复链）

日期：2026-10-20。运行时提交：后端 `0d399fe`（含 `c88ba7a` solver-only
档位平衡、`95e1597` 初始档位投影、`c6827d8` 复合单元号修复），Web
`ec2ec0d`（解读卡列表字段降级）与 `0d399fe`（冷刷新提案卡）。验收使用
`zhiyuan-server/target/zhiyuan-server.jar` 与 3201 开发实例。

## 1. 隔离环境

- 独立 schema：`zhiyuan_integrity_acc_20261020_163403`（旧验收克隆库）。
- 临时 Java：18390，仅本 JVM 打开
  `review.fix.command.enabled=true`、`review.fix.search.enabled=true`、
  `review.fix.search.strategies=all`、`initial solver=on`、`group-inner=on`。
- 合成夹具：`/tmp/planning-integrity-acceptance-fixtures/fixtures.json`。
- 未启动 Agent、未调用真实模型、未触碰源库会话行。
- 验收后临时 Java 已停止，18390 无监听。

## 2. 完整确认链（6/6）

每个场景都验证：preview 只读、prepare 只读、public apply 拒绝、未领取
execute 拒绝、claim → execute → replay → complete、postcondition satisfied、
版本只 +1、replay 不二次写入。

| 场景 | 结果 | 最终形状 |
|---|---|---|
| group_count | passed | 46 组 / 92 条，冻结专业 map 46 组 |
| group_coverage | passed | 4 组 / 4 条，冻结专业 map 4 组 |
| group_direct | passed | 3 组 / 3 条，Direct 无 solver map |
| major_count | passed | 82 条 |
| major_coverage | passed | 80 条 |
| major_direct | passed | 3 条 |

组模式额外逐组核对：冻结 ordered units 非空；最终每个 unit 的
`majorItems` 与该 unit 的冻结 `selectedMajorIdsByUnit` 集合一致。

## 3. 默认参数初始方案（源测试库，逐会话 HEX 恢复）

无额外 `-D`，初始 solver 与组内 MILP 均走默认 on：

| 会话 | 结果 | 内容检查 |
|---|---|---|
| 900016 | 45 组 / 123 条 / 单组最大 6 | contentOk=true，风险标签不变 |
| 900045 | 44 组 / 127 条 / 单组最大 6 | contentOk=true |
| 10041984 | 45 组 / 122 条 / 单组最大 6 | contentOk=true，preferred 104 不丢 |

## 4. 真实历史会话的只读预览

临时打开 review command/search 后，对 900045、900700 调只读预览：

- HTTP 200；预览前后 planningState SHA256 与三类 pending 计数完全不变。
- 当前真实方案没有可确认提案：900045 补 45/46 被
  `hard_constraints_unsatisfied` 拒绝；900700 补 82 被
  `review_fix_facts_incomplete` 拒绝；900045 safety finding 无可替换安全单元。
- 这些是真实数据约束导致的显式 blocked，不是 500 或写入失败；成功路径由
  上面的隔离合成夹具覆盖。

## 5. 真实模型 WS 多轮（已推进）

使用本机 test-bypass 账号 `13000000002` / 用户 `900002`，新建测试会话；不触碰
现有用户连接。

### 成功路径

| 会话 | 领域 | 过程 | 结果 |
|---|---|---|---|
| 10041989 | major / 浙江 575 | 自然语言「把方案补齐到45个」→ ready proposal → WS pendingConfirmation 确认 | applied，45 条，version 0→3 |
| 10041991 | majorGroup / 复合单元号 | 同上 | applied，45 组 / 45 条，version 0→3 |

模型自主调用了 `preview_plan_change`，预览卡 `status=ready`、
`requiresConfirmation=true`；确认事件返回 `actionStatus=applied`，说明真实模型
多轮 + 工具选择 + 确认动作至少在 clean prompt 下闭环。

### 发现并修复：复合单元号截断

10041990（majorGroup，候选单元 id 形如 `A_B`）首次确认返回
`solver_frozen_selection_mismatch`。根因：`buildOrderedUnitsFromOrderedItems`
用志愿行键的第一个 `_` 前段反推单元号，把 `planSchoolDataId=A_B` 截成 `A`，
重建后的 ordered units 与冻结选择不一致。

修复（`c6827d8`）：单元身份优先取候选的 `planSchoolDataId`，缺失时才回退
志愿前缀规则；新增复合单元号 group count apply 回归。修复后 10041991
预览→确认→applied 成功。

### 初始档位投影修复（`95e1597`）

初始 solver 之前没有把推荐池的 `requiredTierCounts` 带进选择，默认 on 后
可能整版只选冲/稳。现在无 durable 档位目标时，按目标数投影推荐档位，并用
current + available 的可用供给做上限；投影不可行则保持旧口径，不阻塞。

真栈验证（10041992，浙江，推荐池 5785）：最终 **80 组 = 24 冲 / 24 稳 /
32 保**，不再是单一冲刺档。900045/900016 的候选池本身全为冲档，仍分别
44/45 组全冲，属于数据供给限制。

### 空方案 user-goal fill 档位修复（`c88ba7a`）

`UserGoalProposalBuilder` 现在对**空方案首次补齐**也投影推荐档位，但走
`solverTierBalance` 这一 solver-only 字段：不进入 canonical objective /
solverObjectiveDigest，也不产生 `tier_*` 冻结结果，因此后置校验不会
因“多出来的目标”拒绝。已有条目的普通补齐仍保持“保留存量优先”，不施加
精确档位约束。

真栈 10041994（majorGroup，空方案，5785 候选）：**45 组 = 14 冲 / 13 稳 /
18 保**，WS 确认 `applied`。此前 10041993 的 32/13/0 是修复前结果；
直接把档位加进 `stagedObjectives.tierAllocationConstraint` 会导致 40905
`frozen objective result mismatch`，该尝试已回滚。

### 浏览器确认卡片

3201 开发实例 + Playwright 容器（`zhiyuan-e2e-playwright:1.55.0`，host
network），localStorage 注入 900002 的 `token/botId/tenantId`。会话
10041997（空方案、5785 候选）：

- 真实模型在同一页面流式产出 `proposal.preview`；
- 卡片实时渲染出“补齐到 45 个专业组”的标题、摘要、影响说明和
  **采纳 / 放弃**按钮；
- 点击“采纳”后卡片变为“已生效”，页面无异常；
- 最终方案 45 组 = 14 冲 / 13 稳 / 18 保，version 0→3。

本轮修了一个浏览器崩溃：`InterpretationCard` 收到非数组的
`caveatDetails/scenarios/caveats` 时 `.filter/.map` 抛
`TypeError`，整页空白。修复（`ec2ec0d`）：列表字段先
`Array.isArray` 降级；修复后复跑同一确认路径，PAGE_ERRORS 为空。
Web typecheck 通过；Node 20 下 `codexLocalRewrite.test.mjs` 的
`Unable to deserialize cloned data` 是既有环境问题（Node 22 容器通过），
与本改动无关。

**冷刷新卡片已修（`0d399fe`）**：`LastProposalVo` 现在带冻结提案的
title/summary/impact/status/requiresConfirmation；冷加载兜底卡把
`active` 当作“待确认”而不是已落定，并通过
`buildPendingConfirmationFrame` 发送标准确认帧。真栈 10041998：刷新后
卡片完整显示摘要、影响说明和采纳/放弃按钮；点“采纳”后 pending 变
`applied`，方案达到 45 组，页面无异常。

### 仍需关注

- **内容梯度**：10041994 已按 14/13/18 平衡；10041989 的候选池本身全为冲档，
  因此仍全冲，属于数据供给限制。模型话术仍需确认“实际结果”与“承诺档位”
  一致。
- 模型在“45 条 + 浙江优先”复合表述下先产出了 `user_goal_unclear` 的 blocked
  proposal，却口头描述为可确认卡片；随后才拆成单独要求。工具/模型话术需要
  继续观察。
- **浏览器确认卡片未验收**：本轮只走 WS，未在 3201 浏览器端点击卡片。
- 隔离环境未启动 Agent；失败命令独立事务审计/outbox 等发布级项不在本批。

## 6. 收尾

- 源环境 18290 保持普通启动（review 开关关闭），pid `20015`。
- 源库 900045/900700 planningState 哈希保持验收前值；真实模型验收只使用
  新建的 900002 测试会话。
- Python 单元全量：**2978 passed / 32 skipped / 20 warnings**。
- 未推送、未部署；隔离 schema 保留用于复核。
