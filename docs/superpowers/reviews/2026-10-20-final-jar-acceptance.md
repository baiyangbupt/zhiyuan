# 最终 jar 验收（新求解器默认值 + 审查修复链）

日期：2026-10-20。运行时提交：`c6827d8`（此前的 `3801a5f`、`b541c46`
仅测试/文档；`c6827d8` 修复真实模型验收发现的复合单元号问题）。
验收使用 `zhiyuan-server/target/zhiyuan-server.jar`。

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

### 仍需关注

- **内容梯度**：10041991 最终 45 组为 32 冲 / 13 稳 / **0 保**，而候选池存在
  保档；模型回复声称“保底会放足”，与实际结果不一致。10041989 的候选池本身
  全为冲档。前者不是写入失败，但属于需要继续排查的选档/内容质量问题。
- 模型在“45 条 + 浙江优先”复合表述下先产出了 `user_goal_unclear` 的 blocked
  proposal，却口头描述为可确认卡片；随后才拆成单独要求。工具/模型话术需要
  继续观察。
- **浏览器确认卡片未验收**：本轮只走 WS，未在 3201 浏览器端点击卡片。
- 隔离环境未启动 Agent；失败命令独立事务审计/outbox 等发布级项不在本批。

## 6. 收尾

- 源环境 18290 保持普通启动（review 开关关闭），pid `7368`。
- 源库 900045/900700 planningState 哈希保持验收前值；真实模型验收只使用
  新建的 900002 测试会话。
- Python 单元全量：**2978 passed / 32 skipped / 20 warnings**。
- 未推送、未部署；隔离 schema 保留用于复核。
